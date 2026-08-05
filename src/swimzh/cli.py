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

**HTTP disk cache.** Every network command runs over ONE `DiskCacheTransport` (`.cache/swimzh/`,
git-ignored) shared by one `HttpClient` PER SOURCE (`ProviderClients`), so each provider's
responses expire on its own volatility clock (`core/cache_tiers`) instead of collapsing to one
tier. `--refresh` (or `SWIMZH_CACHE=refresh`) refetches everything once; `SWIMZH_CACHE=off`
restores the uncached behaviour for a live-correctness run.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, assert_never
from zoneinfo import ZoneInfo

import httpx

from swimzh.build.compose import compose
from swimzh.build.reconcile import crosswalk_from_rows, resolve_all
from swimzh.core.errors import ProviderError, SchemaMismatch, describe
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.httpcache import (
    DEFAULT_CACHE_ROOT,
    CacheMode,
    CacheStore,
    DiskCacheTransport,
)
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
from swimzh.etl.scrape import scrape_declared_sources
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

#: The env var that drives the disk cache from outside: `off` (today's uncached behaviour) or
#: `refresh` (refetch everything once, overwriting the entries). Unset means "use the cache".
CACHE_ENV_VAR: Final = "SWIMZH_CACHE"

_CACHE_MODE_BY_ENV: Final[dict[str, CacheMode]] = {
    "": CacheMode.USE,
    "use": CacheMode.USE,
    "on": CacheMode.USE,
    "off": CacheMode.OFF,
    "refresh": CacheMode.REFRESH,
}

_LIVE_TIMEOUT_S: Final = 30.0

_LIVE_CONNECT_TIMEOUT_S: Final = 5.0


class CacheModeError(ValueError):
    """An unusable `SWIMZH_CACHE` value — a config typo, reported as a one-line error.

    A dedicated type so `main` can catch *this* and nothing else: a bare `except ValueError`
    around the live wiring would also swallow a `ValueError` from `httpx.HTTPTransport()`
    construction (a bad SSL env, say) and report it as a cache-config problem. Still a
    `ValueError` by inheritance, so callers that only care that the value was rejected are
    unaffected.
    """


def _now() -> datetime:
    """The pipeline clock — tz-aware `Europe/Zurich`, and one seam a test can freeze."""
    return datetime.now(_ZURICH)


def cache_mode(*, refresh: bool = False, env: Mapping[str, str] | None = None) -> CacheMode:
    """Resolve the disk-cache mode from the `--refresh` flag and `SWIMZH_CACHE`.

    The flag wins over the env var (an explicit "refetch now" on this one run beats an
    ambient default). An unrecognised value is a **fail-fast `CacheModeError`**, not a silent
    fallback: `SWIMZH_CACHE=of` quietly meaning "use the cache" is exactly the class of
    typo that makes a live-correctness run serve stale bytes without saying so.
    """
    if refresh:
        return CacheMode.REFRESH
    raw = (env if env is not None else os.environ).get(CACHE_ENV_VAR, "").strip().lower()
    mode = _CACHE_MODE_BY_ENV.get(raw)
    if mode is None:
        valid = ", ".join(sorted(k for k in _CACHE_MODE_BY_ENV if k))
        raise CacheModeError(f"{CACHE_ENV_VAR}={raw!r} is not one of: {valid}")
    return mode


def cache_transport(
    inner: httpx.BaseTransport,
    *,
    mode: CacheMode,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
    now: Callable[[], datetime] = _now,
) -> DiskCacheTransport:
    """The ONE disk-cache transport a pipeline run shares across all five sources.

    One transport over one store: the per-source separation is the *tier stamp* each
    `HttpClient` puts on its requests (`cache_tiers`), not a separate cache per phase.

    **Accepted, S2-flagged:** the transport writes through *below* `HttpClient`, so a response
    larger than `max_bytes` is stored before `_classify` rejects it — an oversized payload caches
    and then replays as `TooLarge` for its whole TTL. Kept deliberately: it is the same verdict
    the live fetch gives, it is now merely reached without paying for the download again, and
    `--refresh` / `SWIMZH_CACHE=off` are the two ways out. Making the write conditional would
    mean teaching the transport a size policy that belongs to the client above it.
    """
    return DiskCacheTransport(inner, CacheStore(cache_dir), mode, now=now)


def live_transport(
    *,
    refresh: bool = False,
    env: Mapping[str, str] | None = None,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
) -> DiskCacheTransport:
    """The live pipeline's transport: the real network behind the disk cache, in the mode the
    `--refresh` flag and `SWIMZH_CACHE` ask for.

    This is the ONLY place the escape hatch actually takes effect, so it is a factory rather
    than three lines inside `main`: `httpx.HTTPTransport()` opens no connection at construction
    time, which makes the whole flag/env → `CacheMode` → transport join assertable offline (see
    `apps.web.main.build_http_transport` for the same shape on the web side). Wired inline it
    would sit under a `# pragma: no cover - live`, where a `--refresh` quietly degraded to
    `USE` would keep the suite green.

    Raises `CacheModeError` on an unusable `SWIMZH_CACHE`; `main` turns that — and only that —
    into a one-line error.

    **Known behaviour change (recorded, not fixed):** passing an explicit `transport=` to
    `httpx.Client` disables httpx's environment proxy mounts, so the pipeline no longer honours
    `HTTP(S)_PROXY`. Restoring it means reading those vars here and handing them to
    `httpx.HTTPTransport(proxy=…)` — localized to this function if it is ever needed.
    """
    return cache_transport(
        httpx.HTTPTransport(), mode=cache_mode(refresh=refresh, env=env), cache_dir=cache_dir
    )


def live_timeout() -> httpx.Timeout:
    """The live pipeline's timeout budget: a SHORT connect budget, the long read budget unchanged.

    A flat `timeout=30.0` charges a host that accepts TCP and then says nothing the full 30s
    per attempt — and `ConnectionFailed`/`Timeout` are both `retriable()`, so a build pays that
    three times per URL. Splitting the budget bounds what any such blackholing listener can cost
    without shortening a *slow but working* fetch: read/write/pool stay at `_LIVE_TIMEOUT_S`, so
    nothing that passes today starts failing.

    **5.0s, not 3.0s, deliberately.** Every real host connects ~125x inside this budget
    (measured 2026-08-01: `www.ogd.stadt-zuerich.ch` 0.019s TCP / 0.038s TLS,
    `www.stadt-zuerich.ch` 0.013s / 0.032s — the Belegungsplan PDFs are on that same host —
    and `www.bad-altstetten.ch` 0.020s). But a schedule-page connect failure is **fatal** to
    the atomic build, so the budget must never be the thing that breaks it: the margin is sized
    for a bad network minute, not for the measured best case.

    A named factory rather than an inline `httpx.Timeout(...)` because the client itself is
    built under `# pragma: no cover - live`, where a budget that silently reverted to the flat
    30s would keep the suite green (the same lesson as `live_transport`).
    """
    return httpx.Timeout(_LIVE_TIMEOUT_S, connect=_LIVE_CONNECT_TIMEOUT_S)


@dataclass(frozen=True, slots=True)
class ProviderClients:
    """One `HttpClient` per provider **source**, all sharing one underlying transport.

    The tier TTL keys off `HttpClient.source`, so a single client threaded through the
    whole pipeline would stamp every request with the roster's 14-day tier and make the
    volatility table inert. Hence one client per source — and note a *phase* is not
    source-atomic: the schedule phase fans out to `price_scraper` **and**
    `schedule_scraper`, the lane phase to `page_provider` **and** `belegungsplan`. The
    granularity is the provider call, which is why both phases take two clients.

    Providers stay byte-unchanged: they still just receive an `HttpClient`.
    """

    roster: HttpClient  # geo_sport — the WFS layers
    schedules: HttpClient  # schedule_scraper — the pool-page timetables
    prices: HttpClient  # price_scraper — the shared city tariff page
    pages: HttpClient  # page_provider — the Belegungsplan discovery hop
    lanes: HttpClient  # belegungsplan — the discovered lane sheets

    @staticmethod
    def over(
        client: httpx.Client,
        *,
        timeout_s: float = _LIVE_TIMEOUT_S,
        retry: RetryPolicy | None = None,
    ) -> ProviderClients:
        """Wrap ONE `httpx.Client` (hence one transport, one cache) in the five clients."""

        def wrap(source: str) -> HttpClient:
            return HttpClient(client, source=source, timeout_s=timeout_s, retry=retry)

        return ProviderClients(
            roster=wrap("geo_sport"),
            schedules=wrap("schedule_scraper"),
            prices=wrap("price_scraper"),
            pages=wrap("page_provider"),
            lanes=wrap("belegungsplan"),
        )


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
    schedule_client: HttpClient,
    price_client: HttpClient,
    fetched_at: datetime,
) -> _PhaseResult:
    """Scrape indoor-pool schedules (+ the shared city price) and compose them onto the store.

    **Two clients, not one**: the tariff page moves a few times a year (`price_scraper`, 7d) while
    a pool timetable is re-cut per season (`schedule_scraper`, 12h). They are different sources at
    different cadences, so each provider call gets the client whose cache tier matches it.

    Runs the ONE builder path: scrape emits identity-free ``(SourceRef, aspects)`` extracts;
    ``resolve_all`` resolves each ``SourceRef`` to a canonical id against the store's spine (an
    unreconcilable name is a loud typed ``Err``, never a silent wrong-pool write); ``compose``
    folds the scraped aspects onto the curated pool (curated-wins per aspect). Writes the composed
    facilities through the single ``write_schedules`` door.

    Fail-fast: a declared source (`etl.scrape.declared_sources`) whose page fails to fetch or
    parse aborts the phase (``fatal``) carrying the typed cause. An unresolved WFS name (a scraped
    pool in no alias) is a benign partial success — the resolved pools are written and the phase
    exits 1 with the miss named (``fatal=False``), not a data hole.
    """
    prices_result = scrape_prices(price_client, fetched_at.date())
    prices = prices_result.value if isinstance(prices_result, Ok) else None
    report = scrape_declared_sources(schedule_client, catalog, fetched_at, prices=prices)
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
            msg = f"scraped {len(outcome.resolved)} declared sources"
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
    conn: sqlite3.Connection,
    *,
    page_client: HttpClient,
    lane_client: HttpClient,
    fetched_at: datetime,
) -> _PhaseResult:
    """Discover each pool page's Belegungsplan links, fetch those DISCOVERED PDFs, and attach the
    parsed plans onto the basin that owns each URL — a deterministic URL-keyed join. The fetch-set
    is a projection of the links `page_provider` discovers on the pool pages.

    **Two clients, not one**: the discovery hop reads the pool pages (`page_provider`, 7d — the
    link set changes far more slowly than the timetable on the same page) while the sheets
    themselves are `belegungsplan` (3d). Each provider call gets its own source's client.

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
    discovery = discover_pages(page_client, pages)
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

    report = scrape_lane_plans(lane_client, discovery.links)
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


def build(*, db_path: Path, data_dir: Path, clients: ProviderClients) -> int:
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
    match fetch_roster(clients.roster):
        case Err(error):
            print(f"build failed: WFS roster unavailable: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(roster):
            now = _now()
            with atomic_swap(db_path) as staging:
                match build_store(data_dir, staging.path, roster):
                    case Err(error):
                        # No commit: the temp is discarded, the prior gold DB is untouched.
                        print(f"build failed: {describe(error)}", file=sys.stderr)
                        return 1
                    case Ok(_repo):
                        conn = open_db(staging.path)
                        schedules = _compose_schedules(
                            conn,
                            catalog=roster,
                            schedule_client=clients.schedules,
                            price_client=clients.prices,
                            fetched_at=now,
                        )
                        if schedules.fatal:
                            return 1  # no commit -> prior gold content-unchanged
                        lanes = _attach_lanes(
                            conn,
                            page_client=clients.pages,
                            lane_client=clients.lanes,
                            fetched_at=now,
                        )
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
    *, db_path: Path, catalog_path: Path, clients: ProviderClients, fetched_at: datetime
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
        result = _compose_schedules(
            conn,
            catalog=catalog,
            schedule_client=clients.schedules,
            price_client=clients.prices,
            fetched_at=fetched_at,
        )
        if result.fatal:
            return 1  # no commit -> the live store is untouched
        conn.close()  # release the staging handle before the atomic rename
        staging.commit()
        return result.code


def scrape_lanes(*, db_path: Path, clients: ProviderClients, fetched_at: datetime) -> int:
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
        result = _attach_lanes(
            conn,
            page_client=clients.pages,
            lane_client=clients.lanes,
            fetched_at=fetched_at,
        )
        if result.fatal:
            return 1  # no commit -> the live store is untouched
        conn.close()  # release the staging handle before the atomic rename
        staging.commit()
        return result.code


def main(argv: list[str] | None = None, *, clients: ProviderClients | None = None) -> int:
    """Parse argv and dispatch. `clients` is injectable so the WFS-sourced atomic `build` (and the
    other network commands) can be driven from recorded HTTP in tests; when None the live
    per-source clients are created over one shared disk-cache transport for the selected command.
    """
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared across every network command: the one-run escape hatch from the disk cache.
    cache_flags = argparse.ArgumentParser(add_help=False)
    cache_flags.add_argument(
        "--refresh",
        action="store_true",
        help=(
            f"ignore cached responses and refetch every source (also {CACHE_ENV_VAR}=refresh; "
            f"{CACHE_ENV_VAR}=off disables the cache entirely)"
        ),
    )

    roster_build = subparsers.add_parser(
        "build",
        parents=[cache_flags],
        help="assemble a COMPLETE gold store (one atomic pipeline: roster+scrape+compose)",
    )
    roster_build.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    roster_build.add_argument(
        "--data", default="data", help="curated data directory (default: data)"
    )

    catalog = subparsers.add_parser(
        "build-catalog", parents=[cache_flags], help="build the pool catalog from the WFS"
    )
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    scrape = subparsers.add_parser(
        "scrape-gold",
        parents=[cache_flags],
        help="re-layer only the schedule phase onto a built store",
    )
    scrape.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    scrape.add_argument("--catalog", default="data/catalog.json", help="catalog JSON to read")

    lanes = subparsers.add_parser(
        "scrape-lanes",
        parents=[cache_flags],
        help="re-layer only the lane-plan phase onto a built store",
    )
    lanes.add_argument("--db", required=True, help="path to the existing gold SQLite file")

    args = parser.parse_args(argv)
    now = _now()
    if clients is None:
        return _dispatch_live(args, now=now)
    return _dispatch(args, clients=clients, now=now)


def _dispatch_live(args: argparse.Namespace, *, now: datetime) -> int:
    """Build the LIVE per-source clients over one disk-cache transport, then dispatch.

    Only the `with` block below is un-runnable under test (it is the real network); the join
    that decides *how the cache behaves* — flag + env → `CacheMode` → transport — is
    `live_transport`, deliberately a separate, fully testable factory. That split is the point:
    a `--refresh` that silently stopped refreshing would otherwise be invisible to the suite.
    """
    try:
        transport = live_transport(refresh=args.refresh)
    except CacheModeError as exc:
        # A typo'd SWIMZH_CACHE stops the run with the repo's one-line style, not a traceback.
        # Narrow on purpose: a bare `except ValueError` here would also catch one raised by
        # `httpx.HTTPTransport()` construction and mislabel it as a cache-config problem.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # `follow_redirects`: some pool pages (e.g. bad-altstetten.ch) redirect http→https, and the
    # atomic `build` scrapes those pages too.
    with httpx.Client(  # pragma: no cover - live (the real network)
        timeout=live_timeout(), follow_redirects=True, transport=transport
    ) as inner:
        live = ProviderClients.over(inner, timeout_s=_LIVE_TIMEOUT_S)
        return _dispatch(args, clients=live, now=now)


def _dispatch(args: argparse.Namespace, *, clients: ProviderClients, now: datetime) -> int:
    """Route a parsed command to its handler with the resolved per-source HTTP clients."""
    if args.command == "build":
        return build(db_path=Path(args.db), data_dir=Path(args.data), clients=clients)
    if args.command == "scrape-gold":
        return scrape_gold(
            db_path=Path(args.db),
            catalog_path=Path(args.catalog),
            clients=clients,
            fetched_at=now,
        )
    if args.command == "scrape-lanes":
        return scrape_lanes(db_path=Path(args.db), clients=clients, fetched_at=now)
    return build_catalog_file(out=Path(args.out), client=clients.roster, generated_at=now)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
