"""Command-line entry point.

  swimzh build         --db gold.sqlite     # assemble the gold SQLite (roster LIVE from the WFS)
  swimzh build-catalog --out data/catalog.json  # full pool catalog from the WFS (committed)
  swimzh scrape-gold   --db gold.sqlite     # scrape real schedules onto a built store
  swimzh scrape-lanes  --db gold.sqlite     # attach per-basin Belegungsplan lane plans

Run via: `uv run python -m swimzh.cli <command> ...`
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import assert_never
from zoneinfo import ZoneInfo

from swimzh.build.compose import compose
from swimzh.build.reconcile import crosswalk_from_rows, resolve_all
from swimzh.core.errors import ProviderError, SchemaMismatch, describe
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import PoolId
from swimzh.etl.build import build_store
from swimzh.etl.catalog import build_catalog
from swimzh.etl.lane_plans import (
    UndiscoveredSource,
    scrape_lane_plans,
    undiscovered_authored,
)
from swimzh.etl.roster import fetch_roster
from swimzh.etl.scrape import scrape_indoor_facilities
from swimzh.etl.silver import LanePlanAttachment, attach_lane_plans
from swimzh.providers import geo_sport
from swimzh.providers.page_provider import DiscoveryReport, discover_pages
from swimzh.providers.price_scraper import scrape_prices
from swimzh.storage import catalog_json
from swimzh.storage.atomic import atomic_swap
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_alias_rows,
    load_roster,
    load_xref_rows,
    open_db,
    write_schedules,
)

_ZURICH = ZoneInfo("Europe/Zurich")


def build(*, db_path: Path, data_dir: Path, client: HttpClient) -> int:
    """Assemble a gold store: a LIVE-WFS-sourced roster + curated authoring from `data_dir`.

    Since S3 the ~57-pool roster (identity + geo) comes from the WFS via `fetch_roster`, not a
    committed `catalog.json`. An unreachable/failing WFS aborts the whole build non-zero at the
    roster step — BEFORE any temp DB is opened, so nothing is written. Curated facilities +
    calendar + the registry crosswalk still come from `data_dir`.

    S4 atomic write: the store is assembled in a temp DB beside `db_path` and atomically swapped
    over the live file ONLY on full success (`build_store` returning `Ok`). Any abort — the WFS
    roster failure above, or a curated-input `Err` below — discards the temp and leaves the prior
    gold DB **content-unchanged** (never a partial/half-written store). Returns a process exit
    code."""
    match fetch_roster(client):
        case Err(error):
            print(f"build failed: WFS roster unavailable: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(roster):
            with atomic_swap(db_path) as staging:
                match build_store(data_dir, staging.path, roster):
                    case Ok(repo):
                        count = repo.count()
                        staging.commit()  # success: the temp atomically replaces the live DB
                        print(f"gold store built at {db_path} ({count} facilities)")
                        return 0
                    case Err(error):
                        # No commit: the temp is discarded, the prior gold DB is untouched.
                        print(f"build failed: {describe(error)}", file=sys.stderr)
                        return 1


def build_catalog_file(*, out: Path, client: HttpClient, generated_at: datetime) -> int:
    """Fetch every pool category from the WFS and write the catalog JSON. Exit code."""
    match geo_sport.fetch_all_pools(client):
        case Ok(pools):
            entries = build_catalog(pools)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(catalog_json.dumps(entries, generated_at), encoding="utf-8")
            print(f"catalog written to {out} ({len(entries)} pools)")
            return 0
        case Err(error):
            print(f"catalog build failed: {describe(error)}", file=sys.stderr)
            return 1


def scrape_gold(
    *, db_path: Path, catalog_path: Path, client: HttpClient, fetched_at: datetime
) -> int:
    """Scrape indoor-pool schedules and compose them onto an already-built gold store. Exit code.

    Runs the ONE builder path: scrape emits identity-free ``(SourceRef, aspects)`` extracts;
    ``reconcile`` resolves each ``SourceRef`` to a canonical id against the store's spine (an
    unreconcilable name is a loud typed ``Err``, never a silent wrong-pool write); ``compose``
    folds the scraped aspects onto the curated pool (curated-wins per aspect — a curated pool
    keeps its schedule AND gains a scraped price). There is no second door into a gold row.

    Fail-fast (S4): a declared source (an INDOOR catalog pool) whose page fails to fetch/parse is
    **no longer skipped** — the whole run aborts non-zero carrying the typed ``ProviderError``. All
    writes go into a temp copy of the live store that atomically replaces it ONLY on a completed
    run; any abort leaves the prior gold DB content-unchanged. An unresolved WFS name (a scraped
    pool in no alias) stays a benign partial-success: the resolved pools are written and the run
    exits non-zero with the miss named — not a data hole, a reconcile gap on an extra source.
    """
    if not catalog_path.exists():
        print(f"catalog not found at {catalog_path}; run build-catalog first", file=sys.stderr)
        return 1
    if not db_path.exists():
        print(f"gold store not found at {db_path}; run `swimzh build` first", file=sys.stderr)
        return 1
    catalog = catalog_json.loads(catalog_path.read_text(encoding="utf-8"))
    prices_result = scrape_prices(client, fetched_at.date())
    prices = prices_result.value if isinstance(prices_result, Ok) else None
    report = scrape_indoor_facilities(client, catalog, fetched_at, prices=prices)
    if report.failures:
        # A declared source failed to fetch/parse: abort the whole run, surfacing the typed cause.
        failure = report.failures[0]
        print(
            f"scrape-gold aborted: declared source {failure.name} ({failure.url}) failed: "
            f"{describe(failure.cause)}",
            file=sys.stderr,
        )
        return 1
    if not report.extracts:
        print("no schedules could be scraped", file=sys.stderr)
        return 1

    with atomic_swap(db_path, seed_from=db_path) as staging:
        conn = open_db(staging.path)
        curated = GoldRepository(conn).load_all()
        crosswalk = crosswalk_from_rows(load_alias_rows(conn), load_xref_rows(conn))
        match resolve_all(report.extracts, crosswalk):
            case Err(error):
                # No commit: the ambiguous batch aborts whole, the live store is untouched.
                print(f"scrape reconcile failed: {describe(error)}", file=sys.stderr)
                return 1
            case Ok(outcome):
                composition = compose(curated, outcome.resolved)
                write_schedules(
                    conn,
                    tuple((f.identity.facility_id, f) for f in composition.facilities),
                )
                conn.close()  # release the staging handle before the atomic rename
                staging.commit()  # the resolved scrapes are good — swap them in
                msg = f"scraped {len(outcome.resolved)} indoor pools into {db_path}"
                msg += " (with prices)" if prices is not None else " (prices unavailable)"
                for note in composition.notes:
                    msg += f"; {note}"
                print(msg)
                if outcome.unresolved:
                    print(
                        f"unresolved (no pool matched): {', '.join(sorted(outcome.unresolved))}",
                        file=sys.stderr,
                    )
                    return 1
                return 0


def _report_lane_audit(attachment: LanePlanAttachment) -> int:
    """Print the honest scrape-lanes audit to stderr and return the count of attached lane plans.

    Two non-fatal audit streams (S4 removed the persisted-`unavailable` hole — a fetch/parse miss
    now aborts before attach): (a) each `unbound` parsed section a URL/header no basin claims — a
    discovered sheet no basin authored, not a missing declared fact; (b) each `unmatched section` —
    a declared token that matched no parsed header of its sheet. Post-fail-fast a basin's
    `lane_plan` is only ever a `LanePlan` (attached) or `None`."""
    attached = sum(
        1
        for facility in attachment.facilities
        for basin in facility.basins
        if isinstance(basin.lane_plan, LanePlan)
    )
    for plan in attachment.unbound:
        print(
            f"unbound ({plan.source_url}): {plan.basin_hint!r} — {plan.reason}",
            file=sys.stderr,
        )
    for section in attachment.unmatched_sections:
        print(
            f"unmatched section ({section.basin_id} <- {section.source_url}): "
            f"declared section {section.section!r} matched no parsed header",
            file=sys.stderr,
        )
    for warning in attachment.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return attached


def _undiscovered_error(source: UndiscoveredSource, discovery: DiscoveryReport) -> ProviderError:
    """The typed cause for an authored lane source discovery could not surface: the owning page's
    own fetch failure if that is WHY it wasn't advertised, else a `SchemaMismatch` that the page no
    longer lists the URL. Errors stay typed values even for a 'missing declared fact' abort."""
    for page_miss in discovery.page_misses:
        if page_miss.pool_id == source.pool_id:
            return page_miss.cause
    return SchemaMismatch(
        source="scrape-lanes",
        detail=f"authored lane source not advertised by its pool page: {source.url}",
    )


def scrape_lanes(*, db_path: Path, client: HttpClient, fetched_at: datetime) -> int:
    """Discover each pool page's Belegungsplan links, fetch those DISCOVERED PDFs, and attach the
    parsed plans onto the basin that owns each URL — a deterministic URL-keyed join. The fetch-set
    is a projection of the links `page_provider` discovers on the pool pages (not of any authored
    `lane_plan_source` URL).

    Fail-fast (S4), all writes into a temp copy of the live store swapped in ONLY on a completed
    run — any abort below leaves the prior gold DB content-unchanged:
      * an authored `lane_plan_source.url` its pool page fails to advertise (`authored −
        discovered` non-empty — the stale-store fetch-set invariant, incl. a page that failed to
        fetch) is a HARD abort carrying the typed cause, never a silent drop;
      * a discovered lane source that fails to fetch/parse is a HARD abort carrying its typed
        `ProviderError`, never a persisted `LanePlanUnavailable` that lets the facility build.
    Prints an honest audit to stderr: each un-fetchable page, each `unbound` parsed section (a
    discovered sheet no basin claims — an undeclared extra, non-fatal), and each `unmatched
    section` (a declared token that matched no parsed header). Exit code."""
    if not db_path.exists():
        print(f"gold store not found at {db_path}; build it first", file=sys.stderr)
        return 1

    with atomic_swap(db_path, seed_from=db_path) as staging:
        conn = open_db(staging.path)
        facilities = GoldRepository(conn).load_all()
        if not facilities:
            print(f"gold store {db_path} is empty; build it first", file=sys.stderr)
            return 1

        # The discovery hop: fetch each pool's official page and collect the Belegungsplan links it
        # advertises, stamped with the owning PoolId. The pool page URL is the roster's `url`.
        page_url = {entry.entry.pool_id: entry.entry.url for entry in load_roster(conn)}
        pages: list[tuple[PoolId, str]] = []
        for facility in facilities:
            url = page_url.get(str(facility.identity.facility_id))
            if url is not None:
                pages.append((facility.identity.facility_id, url))
        discovery = discover_pages(client, pages)
        # A page fetch failure is audited; it only ABORTS if it stranded an authored source (caught
        # by `authored − discovered` below). A page with no authored source dropping no declared
        # fact stays a non-fatal audit line.
        for page_miss in discovery.page_misses:
            print(
                f"page discovery failed ({page_miss.pool_id} <- {page_miss.page_url}): "
                f"{describe(page_miss.cause)}",
                file=sys.stderr,
            )

        # Fail-fast: an authored source its page no longer advertises is a declared fact gone
        # missing — abort, never a silent drop (no commit -> live store untouched).
        undiscovered = undiscovered_authored(facilities, discovery.links)
        if undiscovered:
            source = undiscovered[0]
            print(
                f"scrape-lanes aborted: authored lane source not discovered on its page "
                f"({source.pool_id} <- {source.url}): "
                f"{describe(_undiscovered_error(source, discovery))}",
                file=sys.stderr,
            )
            return 1

        report = scrape_lane_plans(client, discovery.links)
        # Fail-fast: a discovered lane source that failed to fetch/parse aborts the whole run
        # carrying its typed cause — no persisted hole (no commit -> live store untouched).
        if report.misses:
            miss = report.misses[0]
            print(
                f"scrape-lanes aborted: lane source {miss.source_url} failed: "
                f"{describe(miss.cause)}",
                file=sys.stderr,
            )
            return 1

        match attach_lane_plans(facilities, report.plans, fetched_at):
            case Err(error):
                print(f"lane-plan reconcile failed: {describe(error)}", file=sys.stderr)
                return 1
            case Ok(attachment):
                attached = _report_lane_audit(attachment)
                if attached == 0:
                    print("no lane plan reconciled to a curated basin", file=sys.stderr)
                    return 1
                # Persist the parsed plans to the read path, then swap the temp store in.
                write_schedules(
                    conn,
                    tuple((f.identity.facility_id, f) for f in attachment.facilities),
                )
                conn.close()  # release the staging handle before the atomic rename
                staging.commit()
                print(f"attached {attached} lane plan(s) into {db_path}")
                return 0
            case _ as unreachable:  # pragma: no cover - exhaustiveness guard
                assert_never(unreachable)


def main(argv: list[str] | None = None, *, client: HttpClient | None = None) -> int:
    """Parse argv and dispatch. `client` is injectable so the WFS-sourced `build` (and the other
    network commands) can be driven from recorded HTTP in tests; when None a live client is
    created for the selected command."""
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)

    roster_build = subparsers.add_parser(
        "build", help="assemble a gold store (pool roster sourced LIVE from the WFS)"
    )
    roster_build.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    roster_build.add_argument(
        "--data", default="data", help="curated data directory (default: data)"
    )

    catalog = subparsers.add_parser("build-catalog", help="build the pool catalog from the WFS")
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    scrape = subparsers.add_parser(
        "scrape-gold", help="scrape indoor-pool schedules into a gold store"
    )
    scrape.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    scrape.add_argument("--catalog", default="data/catalog.json", help="catalog JSON to read")

    lanes = subparsers.add_parser(
        "scrape-lanes", help="attach per-basin Belegungsplan lane plans to a gold store"
    )
    lanes.add_argument("--db", required=True, help="path to the existing gold SQLite file")

    args = parser.parse_args(argv)
    now = datetime.now(_ZURICH)

    # `build` now sources its roster from the WFS, so it needs a network client too. Tests inject
    # a recorded-HTTP client; live runs build one just-in-time.
    if args.command == "build":
        if client is None:  # pragma: no cover - live
            import httpx  # pragma: no cover - live

            with httpx.Client(timeout=30.0) as inner:  # pragma: no cover - live
                client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
                return build(db_path=Path(args.db), data_dir=Path(args.data), client=client)
        return build(db_path=Path(args.db), data_dir=Path(args.data), client=client)

    # The network wiring below is exercised live; the per-command functions are unit-tested
    # with an injected client.
    import httpx  # pragma: no cover

    # follow_redirects: some pool pages (e.g. bad-altstetten.ch) redirect http→https.
    with httpx.Client(timeout=30.0, follow_redirects=True) as inner:  # pragma: no cover - live
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        if args.command == "scrape-gold":
            return scrape_gold(
                db_path=Path(args.db),
                catalog_path=Path(args.catalog),
                client=client,
                fetched_at=now,
            )
        if args.command == "scrape-lanes":
            return scrape_lanes(db_path=Path(args.db), client=client, fetched_at=now)
        return build_catalog_file(out=Path(args.out), client=client, generated_at=now)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
