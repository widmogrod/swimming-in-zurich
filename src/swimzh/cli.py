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
from swimzh.core.errors import describe
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import LanePlanUnavailable, PoolId
from swimzh.etl.build import build_store
from swimzh.etl.catalog import build_catalog
from swimzh.etl.lane_plans import scrape_lane_plans
from swimzh.etl.roster import fetch_roster
from swimzh.etl.scrape import scrape_indoor_facilities
from swimzh.etl.silver import LanePlanAttachment, attach_lane_plans
from swimzh.providers import geo_sport
from swimzh.providers.page_provider import discover_pages
from swimzh.providers.price_scraper import scrape_prices
from swimzh.storage import catalog_json
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
    roster step — the LOCAL abort, BEFORE any DB is opened, so nothing is written (the general
    atomic-swap abort is S4). Curated facilities + calendar + the registry crosswalk still come
    from `data_dir`. Returns a process exit code."""
    match fetch_roster(client):
        case Err(error):
            print(f"build failed: WFS roster unavailable: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(roster):
            match build_store(data_dir, db_path, roster):
                case Ok(repo):
                    print(f"gold store built at {db_path} ({repo.count()} facilities)")
                    return 0
                case Err(error):
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
    if not report.extracts:
        print("no schedules could be scraped", file=sys.stderr)
        return 1

    conn = open_db(db_path)
    curated = GoldRepository(conn).load_all()
    crosswalk = crosswalk_from_rows(load_alias_rows(conn), load_xref_rows(conn))
    match resolve_all(report.extracts, crosswalk):
        case Err(error):
            print(f"scrape reconcile failed: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(outcome):
            # Partial success: compose + write the pools that reconciled, UNCONDITIONALLY —
            # one unmatched WFS name no longer discards every good scrape. Benign misses are
            # reported to stderr and signalled by a non-zero exit (visible, not silent); the
            # good scrapes are still written. Only an ambiguous ref (the `Err` case above) is
            # fatal — never a silent wrong-pool write.
            composition = compose(curated, outcome.resolved)
            write_schedules(
                conn,
                tuple((f.identity.facility_id, f) for f in composition.facilities),
            )
            msg = f"scraped {len(outcome.resolved)} indoor pools into {db_path}"
            msg += " (with prices)" if prices is not None else " (prices unavailable)"
            for note in composition.notes:
                msg += f"; {note}"
            if report.skipped:
                msg += f"; skipped {len(report.skipped)}: {', '.join(report.skipped)}"
            print(msg)
            if outcome.unresolved:
                print(
                    f"unresolved (no pool matched): {', '.join(sorted(outcome.unresolved))}",
                    file=sys.stderr,
                )
                return 1
            return 0


def _report_lane_audit(attachment: LanePlanAttachment) -> tuple[int, int]:
    """Print the honest scrape-lanes audit to stderr and return `(attached, unavailable)` counts.

    Three audit streams: (a) each per-basin `unavailable` extraction with its typed cause; (b) each
    `unbound` parsed section a URL/header no basin claims; (c) each `unmatched section` — a declared
    token that matched no parsed header. `lane_plan` is a closed three-case union, matched
    exhaustively."""
    attached = 0
    unavailable = 0
    for facility in attachment.facilities:
        for basin in facility.basins:
            match basin.lane_plan:
                case LanePlan():
                    attached += 1
                case LanePlanUnavailable() as miss:
                    unavailable += 1
                    print(
                        f"unavailable ({basin.basin_id} <- {miss.source_url}): "
                        f"{describe(miss.cause)}",
                        file=sys.stderr,
                    )
                case None:
                    pass
                case _ as unreachable:  # pragma: no cover - exhaustiveness guard
                    assert_never(unreachable)
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
    return attached, unavailable


def scrape_lanes(*, db_path: Path, client: HttpClient, fetched_at: datetime) -> int:
    """Discover each pool page's Belegungsplan links, fetch those DISCOVERED PDFs, and attach the
    parsed plans onto the basin that owns each URL — a deterministic URL-keyed join. The fetch-set
    is a projection of the links `page_provider` discovers on the pool pages (not of any authored
    `lane_plan_source` URL). A source that fails to fetch/parse is recorded as first-class
    `LanePlanUnavailable` state (never a silent drop). Prints an honest operational audit to
    stderr: each un-fetchable page, each `unbound` parsed section (a URL/header no basin claims),
    each per-basin `unavailable` cause, and each `unmatched section` (a declared token that matched
    no parsed header). Exit code."""
    if not db_path.exists():
        print(f"gold store not found at {db_path}; build it first", file=sys.stderr)
        return 1
    conn = open_db(db_path)
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
    for page_miss in discovery.page_misses:
        print(
            f"page discovery failed ({page_miss.pool_id} <- {page_miss.page_url}): "
            f"{describe(page_miss.cause)}",
            file=sys.stderr,
        )

    report = scrape_lane_plans(client, discovery.links)
    if not report.plans and not report.misses:
        print("no Belegungsplan links discovered; nothing to scrape", file=sys.stderr)
        return 1

    misses = {miss.source_url: miss.cause for miss in report.misses}
    match attach_lane_plans(facilities, report.plans, misses, fetched_at):
        case Err(error):
            print(f"lane-plan reconcile failed: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(attachment):
            attached, unavailable = _report_lane_audit(attachment)
            # Persist the run's outcomes (parsed plans AND recorded failures) to the read path.
            write_schedules(
                conn,
                tuple((f.identity.facility_id, f) for f in attachment.facilities),
            )
            if attached == 0:
                print("no lane plan reconciled to a curated basin", file=sys.stderr)
                return 1
            msg = f"attached {attached} lane plan(s) into {db_path}"
            if unavailable:
                msg += f"; {unavailable} unavailable (recorded)"
            print(msg)
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
