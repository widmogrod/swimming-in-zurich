"""Command-line entry point.

  swimzh build         --db gold.sqlite     # ONE atomic pipeline: WFS roster -> curated assemble
                                            #   -> schedule scrape -> lane scrape -> compose
  swimzh build-catalog --out data/catalog.json  # full pool catalog from the WFS (committed)
  swimzh scrape-gold   --db gold.sqlite     # thin re-layer: re-run just the schedule phase
  swimzh scrape-lanes  --db gold.sqlite     # thin re-layer: re-run just the lane-plan phase

Run via: `uv run python -m swimzh.cli <command> ...`

Since S2 (`delete-curated-schedule-tier`) `build` is a SINGLE ATOMIC PIPELINE: it fetches the WFS
roster, assembles the curated facilities, then scrapes schedules + lane plans and composes them —
all inside ONE temp-DB + `os.replace` swap. A mid-chain provider failure aborts the whole build
non-zero and leaves the prior gold DB content-unchanged. `scrape-gold`/`scrape-lanes` remain as
THIN RE-LAYER commands: each re-runs only its own phase against an already-built store (seeded temp
+ swap), so an operator can refresh schedules or lane plans on their own cadence without a full
WFS+curated rebuild. Both `build` and the thin commands drive the SAME phase functions
(`_compose_schedules` / `_attach_lanes`), so there is no second implementation to drift.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import assert_never
from zoneinfo import ZoneInfo

from swimzh.build.compose import compose
from swimzh.build.reconcile import crosswalk_from_rows, resolve_all
from swimzh.core.errors import ProviderError, SchemaMismatch, describe
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.catalog import PoolCatalogEntry
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


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    """The outcome of one provider phase run against an open staging connection.

    ``code`` is the phase's process-exit contribution (0 clean, 1 a problem worth signalling).
    ``fatal`` decides the atomic swap: a fatal phase means the whole store must be DISCARDED (no
    commit, prior gold content-unchanged); a non-fatal ``code == 1`` (e.g. a benign reconcile miss
    that still wrote the resolved pools) keeps the writes and only surfaces the non-zero exit.
    """

    code: int
    fatal: bool


# ── Phase: schedule scrape → reconcile → compose ────────────────────────────────────────────────


def _compose_schedules(
    conn: sqlite3.Connection,
    *,
    catalog: tuple[PoolCatalogEntry, ...],
    client: HttpClient,
    fetched_at: datetime,
) -> _PhaseResult:
    """Scrape indoor-pool schedules (+ the shared city price) and compose them onto the store.

    Runs the ONE builder path: scrape emits identity-free ``(SourceRef, aspects)`` extracts;
    ``resolve_all`` resolves each ``SourceRef`` to a canonical id against the store's spine (an
    unreconcilable name is a loud typed ``Err``, never a silent wrong-pool write); ``compose``
    folds the scraped aspects onto the curated pool (curated-wins per aspect). Writes the composed
    facilities through the single ``write_schedules`` door.

    Fail-fast: a declared source (an INDOOR catalog pool) whose page fails to fetch/parse aborts
    the phase (``fatal``) carrying the typed cause. An unresolved WFS name (a scraped pool in no
    alias) is a benign partial success — the resolved pools are written and the phase exits 1 with
    the miss named (``fatal=False``), not a data hole.
    """
    prices_result = scrape_prices(client, fetched_at.date())
    prices = prices_result.value if isinstance(prices_result, Ok) else None
    report = scrape_indoor_facilities(client, catalog, fetched_at, prices=prices)
    if report.failures:
        # A declared source failed to fetch/parse: abort, surfacing the typed cause.
        failure = report.failures[0]
        print(
            f"schedule scrape aborted: declared source {failure.name} ({failure.url}) failed: "
            f"{describe(failure.cause)}",
            file=sys.stderr,
        )
        return _PhaseResult(code=1, fatal=True)
    if not report.extracts:
        print("no schedules could be scraped", file=sys.stderr)
        return _PhaseResult(code=1, fatal=True)

    curated = GoldRepository(conn).load_all()
    crosswalk = crosswalk_from_rows(load_alias_rows(conn), load_xref_rows(conn))
    match resolve_all(report.extracts, crosswalk):
        case Err(error):
            # The ambiguous batch aborts whole — never a silent wrong-pool write.
            print(f"scrape reconcile failed: {describe(error)}", file=sys.stderr)
            return _PhaseResult(code=1, fatal=True)
        case Ok(outcome):
            composition = compose(curated, outcome.resolved)
            write_schedules(
                conn,
                tuple((f.identity.facility_id, f) for f in composition.facilities),
            )
            msg = f"scraped {len(outcome.resolved)} indoor pools"
            msg += " (with prices)" if prices is not None else " (prices unavailable)"
            for note in composition.notes:
                msg += f"; {note}"
            print(msg)
            if outcome.unresolved:
                print(
                    f"unresolved (no pool matched): {', '.join(sorted(outcome.unresolved))}",
                    file=sys.stderr,
                )
                return _PhaseResult(code=1, fatal=False)
            return _PhaseResult(code=0, fatal=False)
        case _ as unreachable:  # pragma: no cover - exhaustiveness guard
            assert_never(unreachable)


# ── Phase: lane-plan discovery → fetch → attach ─────────────────────────────────────────────────


def _report_lane_audit(attachment: LanePlanAttachment) -> int:
    """Print the honest lane audit to stderr and return the count of attached lane plans.

    Two non-fatal audit streams (fail-fast removed the persisted-`unavailable` hole — a fetch/parse
    miss aborts before attach): (a) each `unbound` parsed section a URL/header no basin claims — a
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


def _attach_lanes(
    conn: sqlite3.Connection, *, client: HttpClient, fetched_at: datetime
) -> _PhaseResult:
    """Discover each pool page's Belegungsplan links, fetch those DISCOVERED PDFs, and attach the
    parsed plans onto the basin that owns each URL — a deterministic URL-keyed join. The fetch-set
    is a projection of the links `page_provider` discovers on the pool pages.

    Fail-fast (all aborts are ``fatal`` so the atomic swap discards, prior gold content-unchanged):
      * an empty store — nothing to attach to;
      * an authored `lane_plan_source.url` its pool page fails to advertise (`authored −
        discovered` non-empty) is a HARD abort carrying the typed cause, never a silent drop;
      * a discovered lane source that fails to fetch/parse is a HARD abort carrying its typed
        `ProviderError`, never a persisted `LanePlanUnavailable`.
    Prints an honest audit to stderr (un-fetchable pages, `unbound` sections, `unmatched section`).
    """
    facilities = GoldRepository(conn).load_all()
    if not facilities:
        print("gold store is empty; build it first", file=sys.stderr)
        return _PhaseResult(code=1, fatal=True)

    # The discovery hop: fetch each pool's official page and collect the Belegungsplan links it
    # advertises, stamped with the owning PoolId. The pool page URL is the roster's `url`.
    page_url = {entry.entry.pool_id: entry.entry.url for entry in load_roster(conn)}
    pages: list[tuple[PoolId, str]] = []
    for facility in facilities:
        url = page_url.get(str(facility.identity.facility_id))
        if url is not None:
            pages.append((facility.identity.facility_id, url))
    discovery = discover_pages(client, pages)
    # A page fetch failure is audited; it only ABORTS if it stranded an authored source (caught by
    # `authored − discovered` below). A page dropping no declared fact stays a non-fatal audit line.
    for page_miss in discovery.page_misses:
        print(
            f"page discovery failed ({page_miss.pool_id} <- {page_miss.page_url}): "
            f"{describe(page_miss.cause)}",
            file=sys.stderr,
        )

    # Fail-fast: an authored source its page no longer advertises is a declared fact gone missing.
    undiscovered = undiscovered_authored(facilities, discovery.links)
    if undiscovered:
        source = undiscovered[0]
        print(
            f"lane scrape aborted: authored lane source not discovered on its page "
            f"({source.pool_id} <- {source.url}): "
            f"{describe(_undiscovered_error(source, discovery))}",
            file=sys.stderr,
        )
        return _PhaseResult(code=1, fatal=True)

    report = scrape_lane_plans(client, discovery.links)
    # Fail-fast: a discovered lane source that failed to fetch/parse aborts carrying its typed
    # cause.
    if report.misses:
        miss = report.misses[0]
        print(
            f"lane scrape aborted: lane source {miss.source_url} failed: {describe(miss.cause)}",
            file=sys.stderr,
        )
        return _PhaseResult(code=1, fatal=True)

    match attach_lane_plans(facilities, report.plans, fetched_at):
        case Err(error):
            print(f"lane-plan reconcile failed: {describe(error)}", file=sys.stderr)
            return _PhaseResult(code=1, fatal=True)
        case Ok(attachment):
            attached = _report_lane_audit(attachment)
            if attached == 0:
                print("no lane plan reconciled to a curated basin", file=sys.stderr)
                return _PhaseResult(code=1, fatal=True)
            write_schedules(
                conn,
                tuple((f.identity.facility_id, f) for f in attachment.facilities),
            )
            print(f"attached {attached} lane plan(s)")
            return _PhaseResult(code=0, fatal=False)
        case _ as unreachable:  # pragma: no cover - exhaustiveness guard
            assert_never(unreachable)


# ── Commands ────────────────────────────────────────────────────────────────────────────────────


def build(*, db_path: Path, data_dir: Path, client: HttpClient) -> int:
    """Assemble a COMPLETE gold store in ONE atomic pipeline. Returns a process exit code.

    Order: WFS roster (`fetch_roster`) → assemble curated facilities + calendar + crosswalk
    (`build_store`) → schedule scrape + price + reconcile + compose (`_compose_schedules`) → lane
    discovery + fetch + attach (`_attach_lanes`). The whole chain runs inside ONE temp-DB +
    `os.replace` swap (`storage/atomic.py`): the store is committed ONLY if every phase completed,
    so a mid-chain provider failure aborts non-zero and leaves the prior gold DB
    **content-unchanged** (never a partial/half-written store). This makes `build`
    network-dependent (already true for the WFS roster since the parent refactor's S3).

    A benign non-fatal miss (e.g. an unresolved extra scrape name) keeps the store but exits 1.
    """
    match fetch_roster(client):
        case Err(error):
            print(f"build failed: WFS roster unavailable: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(roster):
            now = datetime.now(_ZURICH)
            with atomic_swap(db_path) as staging:
                match build_store(data_dir, staging.path, roster):
                    case Err(error):
                        # No commit: the temp is discarded, the prior gold DB is untouched.
                        print(f"build failed: {describe(error)}", file=sys.stderr)
                        return 1
                    case Ok(_repo):
                        conn = open_db(staging.path)
                        schedules = _compose_schedules(
                            conn, catalog=roster, client=client, fetched_at=now
                        )
                        if schedules.fatal:
                            return 1  # no commit -> prior gold content-unchanged
                        lanes = _attach_lanes(conn, client=client, fetched_at=now)
                        if lanes.fatal:
                            return 1  # no commit -> prior gold content-unchanged
                        # Read the count from the staging store BEFORE the swap: `commit()` only
                        # marks the temp good; the `os.replace` fires at context exit, so `db_path`
                        # is not yet the new store here.
                        count = GoldRepository(conn).count()
                        conn.close()  # release the staging handle before the atomic rename
                        staging.commit()
                        print(f"gold store built at {db_path} ({count} facilities)")
                        return max(schedules.code, lanes.code)


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
    """THIN RE-LAYER: re-run only the schedule phase against an already-built store. Exit code.

    Since S2 `build` folds this phase into the one atomic pipeline; this command survives so an
    operator can refresh schedules alone (a faster cadence than the WFS roster) without a full
    rebuild. It seeds a temp copy of the live store, runs the shared `_compose_schedules` phase
    against it, and swaps the temp in ONLY on a non-fatal outcome — any abort leaves the prior gold
    content-unchanged. The catalog is read from `catalog_path` (the roster double) rather than the
    WFS, so this command stays offline of the roster feed.
    """
    if not catalog_path.exists():
        print(f"catalog not found at {catalog_path}; run build-catalog first", file=sys.stderr)
        return 1
    if not db_path.exists():
        print(f"gold store not found at {db_path}; run `swimzh build` first", file=sys.stderr)
        return 1
    catalog = catalog_json.loads(catalog_path.read_text(encoding="utf-8"))

    with atomic_swap(db_path, seed_from=db_path) as staging:
        conn = open_db(staging.path)
        result = _compose_schedules(conn, catalog=catalog, client=client, fetched_at=fetched_at)
        if result.fatal:
            return 1  # no commit -> the live store is untouched
        conn.close()  # release the staging handle before the atomic rename
        staging.commit()
        return result.code


def scrape_lanes(*, db_path: Path, client: HttpClient, fetched_at: datetime) -> int:
    """THIN RE-LAYER: re-run only the lane-plan phase against an already-built store. Exit code.

    Since S2 `build` folds this phase into the one atomic pipeline; this command survives so an
    operator can refresh lane plans alone. It seeds a temp copy of the live store, runs the shared
    `_attach_lanes` phase, and swaps the temp in ONLY on a non-fatal outcome — any abort leaves the
    prior gold content-unchanged.
    """
    if not db_path.exists():
        print(f"gold store not found at {db_path}; build it first", file=sys.stderr)
        return 1

    with atomic_swap(db_path, seed_from=db_path) as staging:
        conn = open_db(staging.path)
        result = _attach_lanes(conn, client=client, fetched_at=fetched_at)
        if result.fatal:
            return 1  # no commit -> the live store is untouched
        conn.close()  # release the staging handle before the atomic rename
        staging.commit()
        return result.code


def main(argv: list[str] | None = None, *, client: HttpClient | None = None) -> int:
    """Parse argv and dispatch. `client` is injectable so the WFS-sourced atomic `build` (and the
    other network commands) can be driven from recorded HTTP in tests; when None a live client is
    created for the selected command."""
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)

    roster_build = subparsers.add_parser(
        "build", help="assemble a COMPLETE gold store (one atomic pipeline: roster+scrape+compose)"
    )
    roster_build.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    roster_build.add_argument(
        "--data", default="data", help="curated data directory (default: data)"
    )

    catalog = subparsers.add_parser("build-catalog", help="build the pool catalog from the WFS")
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    scrape = subparsers.add_parser(
        "scrape-gold", help="re-layer only the schedule phase onto a built store"
    )
    scrape.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    scrape.add_argument("--catalog", default="data/catalog.json", help="catalog JSON to read")

    lanes = subparsers.add_parser(
        "scrape-lanes", help="re-layer only the lane-plan phase onto a built store"
    )
    lanes.add_argument("--db", required=True, help="path to the existing gold SQLite file")

    args = parser.parse_args(argv)
    now = datetime.now(_ZURICH)

    # Every network command needs one HTTP client; tests inject a recorded-HTTP client, live runs
    # build one just-in-time. `follow_redirects`: some pool pages (e.g. bad-altstetten.ch) redirect
    # http→https, and the atomic `build` now scrapes those pages too.
    if client is None:  # pragma: no cover - live
        import httpx  # pragma: no cover - live

        with httpx.Client(timeout=30.0, follow_redirects=True) as inner:  # pragma: no cover - live
            live = HttpClient(inner, source="geo_sport", timeout_s=30.0)
            return _dispatch(args, client=live, now=now)
    return _dispatch(args, client=client, now=now)


def _dispatch(args: argparse.Namespace, *, client: HttpClient, now: datetime) -> int:
    """Route a parsed command to its handler with the resolved HTTP client."""
    if args.command == "build":
        return build(db_path=Path(args.db), data_dir=Path(args.data), client=client)
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
