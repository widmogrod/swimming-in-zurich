"""Command-line entry point.

  swimzh build         --db gold.sqlite     # ONE atomic pipeline, through the lake (`--lake .lake`)
  swimzh lake pull     <dir-or-url>         # step 0: seed the lake's silver from the last publish
  swimzh lake export   --out dist/ios/lake  # ship the silver beside the store for the next run
  swimzh build-catalog --out data/catalog.json  # full pool catalog from the WFS (committed)
  swimzh scrape-gold   --db gold.sqlite     # == build, with prices + schedules FORCED to refetch
  swimzh scrape-lanes  --db gold.sqlite     # == build, with lane_plans FORCED to refetch
  swimzh export-ios    --db gold.sqlite --out ios.sqlite  # OFFLINE: the pre-resolved iOS store

Run via: `uv run python -m swimzh.cli <command> ...`

Since S2 (`delete-curated-schedule-tier`) `build` is a SINGLE ATOMIC PIPELINE: it fetches the WFS
roster, assembles the curated facilities, then scrapes schedules + lane plans and composes them —
all inside ONE temp-DB + `os.replace` swap. A mid-chain provider failure aborts the whole build
non-zero and leaves the prior gold DB content-unchanged. Since the lake (`storage/lake.py`) every
source goes through the refresh policy (`etl/refresh.py`): a silver younger than its TTL is reused
without the network, a due one is refetched, and a transiently unreachable one is kept stale.

**There is ONE pipeline.** `scrape-gold` and `scrape-lanes` are thin wrappers over `build` that
pass a `force_sources` set: `scrape-gold` forces `prices` + `schedules`, `scrape-lanes` forces
`lane_plans`; every other source follows the normal policy (reused inside its TTL, fetched when
due — the roster comes from the lake's `roster.json`, fetched live only if the lake has none). The
store is then rebuilt atomically from silver exactly as `build` does. This retires the old
re-layer path — a second pipeline that seeded a temp copy of the live store, read the hand-made
`data/catalog.json` as its roster, and composed onto the previous gold without ever touching silver
(the defect it kept re-fixing is `docs/2026-08-10-scrape-gold-recompose-defect.md`; under one
pipeline `compose` is never fed its own output by construction).

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final, assert_never
from zoneinfo import ZoneInfo

import httpx

from swimzh.build.compose import compose_facilities, scraped_facility
from swimzh.build.reconcile import Crosswalk, crosswalk_from_rows, resolve_all
from swimzh.core.errors import ProviderError, SchemaMismatch, describe
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.httpcache import (
    DEFAULT_CACHE_ROOT,
    CacheMode,
    CacheStore,
    DiskCacheTransport,
)
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import Facility, PoolId
from swimzh.etl.build import assemble_curated, write_curated_store
from swimzh.etl.catalog import build_catalog
from swimzh.etl.ios_export import DEFAULT_DAYS, ExportReport, export_ios, write_manifest
from swimzh.etl.lane_plans import (
    UndiscoveredSource,
    scrape_lane_plans,
    undiscovered_authored,
)
from swimzh.etl.refresh import Refreshed, refresh_source
from swimzh.etl.roster import fetch_roster
from swimzh.etl.scrape import ScrapeReport, scrape_declared_sources, scrape_shared_sources
from swimzh.etl.silver import LanePlanAttachment, attach_lane_plans
from swimzh.etl.silver_codec import (
    ScrapedLanePlans,
    ScrapedSchedules,
    decode_lane_plans,
    decode_prices,
    decode_roster,
    decode_schedules,
    encode_lane_plans,
    encode_prices,
    encode_roster,
    encode_schedules,
)
from swimzh.providers import geo_sport
from swimzh.providers.page_provider import DiscoveryReport, discover_pages
from swimzh.providers.price_scraper import CityTariffs, scrape_prices
from swimzh.storage import catalog_json
from swimzh.storage.atomic import atomic_swap
from swimzh.storage.lake import DEFAULT_LAKE_ROOT, SILVER_SOURCES, Lake
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_alias_rows,
    load_roster,
    load_xref_rows,
    open_db,
    write_schedules,
    write_source_freshness,
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


# ── Fetch: schedules (+ the shared city price) ──────────────────────────────────────────────────
#
# Each phase is split in two since the lake exists: a FETCH half that reaches the network and
# returns the phase's typed silver value (or the typed cause), and a WRITE half that composes
# that value onto an open staging store. `build` runs the fetch half through the refresh policy
# (`etl/refresh`) so a reused or stale silver can stand in for it; the write half always runs.
# These halves are the ONLY phase functions — `scrape-gold`/`scrape-lanes` are `build`.


def _fetch_prices(client: HttpClient, on: date) -> Result[CityTariffs, ProviderError]:
    """The shared city tariff page. Its failure is a provider failure, not "26 pools unknown"."""
    return scrape_prices(client, on)


def _fetch_schedules(
    client: HttpClient,
    *,
    catalog: tuple[PoolCatalogEntry, ...],
    tariffs: CityTariffs,
    crosswalk: Crosswalk,
    fetched_at: datetime,
) -> Result[ScrapedSchedules, ProviderError]:
    """Scrape every declared + shared pool page and reconcile each extract to its `PoolId`.

    Returns the scraped-side facilities (`compose.scraped_facility`) — the silver form — plus the
    honest audit: `unresolved` names (a benign miss, reported at write time) and provider notes.
    Fail-fast stays: a declared source that fails to fetch/parse is the typed `Err` (the refresh
    policy decides whether a kept silver may stand in for a *transient* one), an empty scrape is
    a `SchemaMismatch`, and an ambiguous reconcile aborts whole — never a silent wrong-pool write.
    """
    declared = scrape_declared_sources(client, catalog, fetched_at, tariffs=tariffs)
    # The shared-source fan-out (sharedsource-fanout S3) rides the SAME phase, report shape,
    # and temp-DB swap: one fetch per registered shared page (the Planschbecken overview), one
    # extract per member on Ok, ONE failure for the whole set on Err — so the fail-fast abort,
    # reconcile, and compose below need no second path. Same client: the overview is a
    # stadt-zuerich pool page, on the schedule scraper's volatility clock.
    shared = scrape_shared_sources(client, catalog, fetched_at)
    report = ScrapeReport(
        extracts=declared.extracts + shared.extracts,
        failures=declared.failures + shared.failures,
        notes=declared.notes + shared.notes,
    )
    if report.failures:
        failure = report.failures[0]
        print(
            f"schedule scrape aborted: declared source {failure.name} ({failure.url}) failed: "
            f"{describe(failure.cause)}",
            file=sys.stderr,
        )
        return Err(failure.cause)
    if not report.extracts:
        return Err(
            SchemaMismatch(source="schedule_scraper", detail="no schedules could be scraped")
        )
    match resolve_all(report.extracts, crosswalk):
        case Err(error):
            # The ambiguous batch aborts whole — never a silent wrong-pool write.
            print(f"scrape reconcile failed: {describe(error)}", file=sys.stderr)
            return Err(error)
        case Ok(outcome):
            return Ok(
                ScrapedSchedules(
                    facilities=tuple(
                        scraped_facility(pool_id, aspects) for pool_id, aspects in outcome.resolved
                    ),
                    unresolved=tuple(sorted(outcome.unresolved)),
                    notes=report.notes,
                )
            )
        case _ as unreachable:  # pragma: no cover - exhaustiveness guard
            assert_never(unreachable)


def _write_scraped_schedules(
    conn: sqlite3.Connection,
    *,
    curated: tuple[Facility, ...],
    scraped: ScrapedSchedules,
) -> _PhaseResult:
    """Compose the scraped-side facilities onto the curated tier and write them. OFFLINE.

    **`curated` is an ARGUMENT, not a read of `conn`** — invariant S-1: `compose` is never called
    with its own output as an input. The caller supplies the curated tier assembled from `data/` +
    the roster (`etl.build.assemble_curated`); reading the store here instead made the previous
    fold's own output the curated side, so every aspect won against itself and a re-layer refreshed
    nothing (`docs/2026-08-10-scrape-gold-recompose-defect.md`).

    Writes the composed facilities through the single ``write_schedules`` door — **only for the
    pools this scrape resolved an extract for**. A pool the curated tier names but the scrape did
    not reach keeps its curated blob; a phase writes only the facts it owns. An `unresolved` name
    (a scraped `Name` in no alias) is a benign partial success — the resolved pools are written and
    the phase exits 1 with the miss named (``fatal=False``), not a data hole. Under one pipeline
    every scraped name IS a roster name and every roster name IS an alias, so the branch is reached
    only through the `resolve_all` seam — it stays because the outcome type carries it.
    """
    for note in scraped.notes:
        # Non-fatal audit: a declared source whose page states no city tariff (free or privately
        # run) ships unpriced ON PURPOSE. Printed, never counted as a failure — but printed, so a
        # WFS url drift that silently unprices a pool leaves a trace in the build output.
        print(note, file=sys.stderr)
    composition = compose_facilities(curated, scraped.facilities)
    scraped_ids = {str(f.identity.facility_id) for f in scraped.facilities}
    write_schedules(
        conn,
        tuple(
            (f.identity.facility_id, f)
            for f in composition.facilities
            if str(f.identity.facility_id) in scraped_ids
        ),
    )
    msg = f"scraped {len(scraped.facilities)} source extracts"
    for note in composition.notes:
        msg += f"; {note}"
    print(msg)
    if scraped.unresolved:
        print(
            f"unresolved (no pool matched): {', '.join(scraped.unresolved)}",
            file=sys.stderr,
        )
        return _PhaseResult(code=1, fatal=False)
    return _PhaseResult(code=0, fatal=False)


# ── Fetch: lane-plan discovery → sheets ─────────────────────────────────────────────────────────


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


def _page_urls(
    conn: sqlite3.Connection, facilities: tuple[Facility, ...]
) -> list[tuple[PoolId, str]]:
    """Each stored pool's official page URL (the roster's `url`), for the discovery hop."""
    page_url = {entry.entry.pool_id: entry.entry.url for entry in load_roster(conn)}
    pages: list[tuple[PoolId, str]] = []
    for facility in facilities:
        url = page_url.get(str(facility.identity.facility_id))
        if url is not None:
            pages.append((facility.identity.facility_id, url))
    return pages


def _fetch_lane_plans(
    *,
    page_client: HttpClient,
    lane_client: HttpClient,
    facilities: tuple[Facility, ...],
    pages: list[tuple[PoolId, str]],
) -> Result[ScrapedLanePlans, ProviderError]:
    """Discover each pool page's Belegungsplan links, then fetch those DISCOVERED PDFs.

    **Two clients, not one**: the discovery hop reads the pool pages (`page_provider`, 7d — the
    link set changes far more slowly than the timetable on the same page) while the sheets
    themselves are `belegungsplan` (3d). Each provider call gets its own source's client.

    Fail-fast, as typed `Err`s: an authored `lane_plan_source.url` its pool page fails to advertise
    (`authored − discovered` non-empty) is a HARD abort carrying the typed cause, never a silent
    drop; a discovered lane source that fails to fetch/parse aborts carrying its `ProviderError`.
    """
    discovery = discover_pages(page_client, pages)
    # A page fetch failure is audited; it only ABORTS if it stranded an authored source (caught by
    # `authored − discovered` below). A page dropping no declared fact stays a non-fatal audit line.
    for page_miss in discovery.page_misses:
        print(
            f"page discovery failed ({page_miss.pool_id} <- {page_miss.page_url}): "
            f"{describe(page_miss.cause)}",
            file=sys.stderr,
        )
    undiscovered = undiscovered_authored(facilities, discovery.links)
    if undiscovered:
        source = undiscovered[0]
        cause = _undiscovered_error(source, discovery)
        print(
            f"lane scrape aborted: authored lane source not discovered on its page "
            f"({source.pool_id} <- {source.url}): {describe(cause)}",
            file=sys.stderr,
        )
        return Err(cause)
    report = scrape_lane_plans(lane_client, discovery.links)
    if report.misses:
        miss = report.misses[0]
        print(
            f"lane scrape aborted: lane source {miss.source_url} failed: {describe(miss.cause)}",
            file=sys.stderr,
        )
        return Err(miss.cause)
    return Ok(ScrapedLanePlans(links=discovery.links, plans=report.plans))


def _write_lane_plans(
    conn: sqlite3.Connection,
    *,
    facilities: tuple[Facility, ...],
    scraped: ScrapedLanePlans,
    fetched_at: datetime,
) -> _PhaseResult:
    """Attach the parsed plans onto the basin that owns each URL — a deterministic URL-keyed join —
    and write. OFFLINE. Prints the honest audit (`unbound` sections, `unmatched section`)."""
    match attach_lane_plans(facilities, scraped.plans, fetched_at):
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


#: `build`'s exit code when the store was written but at least one source is a KEPT STALE silver.
EXIT_BUILT_STALE: Final = 2

#: The silver sources each thin wrapper FORCES through the refresh policy (`force_sources`).
#: `scrape-gold` is the schedule cadence — the tariff page rides with it because a scraped
#: schedule is priced from it; `scrape-lanes` is the Belegungsplan cadence.
SCHEDULE_SOURCES: Final = frozenset({"prices", "schedules"})
LANE_SOURCES: Final = frozenset({"lane_plans"})


def _freshness_line(refreshed: Sequence[Refreshed[Any]]) -> str:
    """One stdout line naming, per source, where this build's facts came from and how old."""
    parts: list[str] = []
    for item in refreshed:
        how = "fetched" if item.fetched else "reused"
        parts.append(
            f"{item.header.source} {item.header.status.value} "
            f"({how}, fetched_at {item.header.fetched_at.isoformat(timespec='minutes')})"
        )
    return "sources: " + "; ".join(parts)


def build(
    *,
    db_path: Path,
    data_dir: Path,
    clients: ProviderClients,
    lake: Lake | None = None,
    now: datetime | None = None,
    force: bool = False,
    force_sources: frozenset[str] = frozenset(),
) -> int:
    """Assemble a COMPLETE gold store from the LAKE in ONE atomic pipeline. Returns an exit code:
    `0` every source fetched or reused fresh, `EXIT_BUILT_STALE` (2) the store was written but a
    source was kept stale, `1` aborted (or a benign non-fatal miss, as before).

    Order, each source through the refresh policy (`etl/refresh.refresh_source`): roster (WFS) →
    assemble curated facilities + calendar + crosswalk (`assemble_curated` → `write_curated_store`)
    → prices → schedules (scrape + reconcile, silver = scraped-side facilities) → compose onto the
    curated tier → lane plans (discover + fetch, silver = links + parsed sheets) → attach → the
    `source_freshness` rows. The store-writing chain runs inside ONE temp-DB + `os.replace` swap
    (`storage/atomic.py`): the store is committed ONLY if every phase completed, so an abort leaves
    the prior gold DB **content-unchanged** (never a partial/half-written store). A stale keep is
    NOT a partial store: every phase completed, one of them on last time's silver, and the store
    says which.

    `lake=None` builds against a throwaway lake (every source must fetch — the pre-lake
    behaviour), so the lake is opt-in per call site and the default for the CLI (`--lake`).
    `force` refetches every source regardless of TTL (`--refresh`); `force_sources` names the
    `SILVER_SOURCES` to refetch regardless of TTL while every other source follows the policy —
    this is what makes `scrape-gold`/`scrape-lanes` a cadence rather than a second pipeline. An
    unknown name is a caller bug and raises rather than silently forcing nothing.
    """
    unknown = force_sources - set(SILVER_SOURCES)
    if unknown:
        raise ValueError(f"force_sources not in SILVER_SOURCES: {sorted(unknown)}")
    now = now if now is not None else _now()
    if lake is None:
        # A throwaway lake, removed with the call: nothing of a lake-less build outlives it.
        with TemporaryDirectory(prefix="swimzh-lake-") as tmp:
            return build(
                db_path=db_path,
                data_dir=data_dir,
                clients=clients,
                lake=Lake(Path(tmp)),
                now=now,
                force=force,
                force_sources=force_sources,
            )
    refreshed: list[Refreshed[Any]] = []

    def forced(source: str) -> bool:
        return force or source in force_sources

    roster = refresh_source(
        lake,
        "roster",
        now=now,
        force=forced("roster"),
        fetch=lambda: fetch_roster(clients.roster),
        encode=lambda entries: encode_roster(entries, now),
        decode=decode_roster,
    )
    if isinstance(roster, Err):
        print(f"build aborted: WFS roster unavailable: {roster.error.describe()}", file=sys.stderr)
        return 1
    refreshed.append(roster.value)
    assembly_result = assemble_curated(data_dir, roster.value.value)
    if isinstance(assembly_result, Err):
        print(f"build failed: {describe(assembly_result.error)}", file=sys.stderr)
        return 1
    assembly = assembly_result.value

    prices = refresh_source(
        lake,
        "prices",
        now=now,
        force=forced("prices"),
        fetch=lambda: _fetch_prices(clients.prices, now.date()),
        encode=encode_prices,
        decode=decode_prices,
    )
    if isinstance(prices, Err):
        print(f"build aborted: city tariff page: {prices.error.describe()}", file=sys.stderr)
        return 1
    refreshed.append(prices.value)

    with atomic_swap(db_path) as staging:
        write_curated_store(assembly, staging.path)
        conn = open_db(staging.path)
        crosswalk = crosswalk_from_rows(load_alias_rows(conn), load_xref_rows(conn))
        schedules = refresh_source(
            lake,
            "schedules",
            now=now,
            force=forced("schedules"),
            fetch=lambda: _fetch_schedules(
                clients.schedules,
                catalog=roster.value.value,
                tariffs=prices.value.value,
                crosswalk=crosswalk,
                fetched_at=now,
            ),
            encode=encode_schedules,
            decode=decode_schedules,
        )
        if isinstance(schedules, Err):
            print(f"build aborted: schedules: {schedules.error.describe()}", file=sys.stderr)
            return 1  # no commit -> prior gold content-unchanged
        refreshed.append(schedules.value)
        # Never fatal: an unresolved extra name is the benign exit-1 miss, the store still lands.
        written = _write_scraped_schedules(
            conn, curated=assembly.facilities, scraped=schedules.value.value
        )

        facilities = GoldRepository(conn).load_all()
        pages = _page_urls(conn, facilities)
        lanes = refresh_source(
            lake,
            "lane_plans",
            now=now,
            force=forced("lane_plans"),
            fetch=lambda: _fetch_lane_plans(
                page_client=clients.pages,
                lane_client=clients.lanes,
                facilities=facilities,
                pages=pages,
            ),
            encode=encode_lane_plans,
            decode=decode_lane_plans,
        )
        if isinstance(lanes, Err):
            print(f"build aborted: lane plans: {lanes.error.describe()}", file=sys.stderr)
            return 1  # no commit -> prior gold content-unchanged
        refreshed.append(lanes.value)
        attached = _write_lane_plans(
            conn,
            facilities=facilities,
            scraped=lanes.value.value,
            fetched_at=lanes.value.header.fetched_at,
        )
        if attached.fatal:
            return 1  # no commit -> prior gold content-unchanged

        write_source_freshness(conn, tuple(r.header for r in refreshed), built_at=now)
        # Read the count from the staging store BEFORE the swap: `commit()` only marks the temp
        # good; the `os.replace` fires at context exit, so `db_path` is not yet the new store here.
        count = GoldRepository(conn).count()
        conn.close()  # release the staging handle before the atomic rename
        staging.commit()
        print(f"gold store built at {db_path} ({count} facilities)")
        print(_freshness_line(refreshed))
        code = max(written.code, attached.code)
        if code == 0 and any(r.stale for r in refreshed):
            return EXIT_BUILT_STALE
        return code


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
    *,
    db_path: Path,
    data_dir: Path,
    clients: ProviderClients,
    lake: Lake | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """`build` on the SCHEDULE cadence: prices + schedules are forced through the refresh policy,
    every other source follows it. Exit code as `build`.

    The roster is the lake's `roster.json` — reused inside its TTL, fetched live from the WFS if
    the lake has none (a first run) or it is due. The lane plans are the lake's `lane_plans.json`
    likewise, so the plans a previous run attached come back attached without a refetch. The store
    is rebuilt atomically from silver, never from the previous gold: nothing here composes onto
    its own output (`docs/2026-08-10-scrape-gold-recompose-defect.md` cannot recur), and a pool
    this run did not scrape comes out of the same curated tier it came out of last time.
    """
    return build(
        db_path=db_path,
        data_dir=data_dir,
        clients=clients,
        lake=lake,
        now=now,
        force=force,
        force_sources=SCHEDULE_SOURCES,
    )


def scrape_lanes(
    *,
    db_path: Path,
    data_dir: Path,
    clients: ProviderClients,
    lake: Lake | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """`build` on the LANE-PLAN cadence: `lane_plans` (discovery + the Belegungsplan sheets) is
    forced through the refresh policy, every other source follows it. Exit code as `build`."""
    return build(
        db_path=db_path,
        data_dir=data_dir,
        clients=clients,
        lake=lake,
        now=now,
        force=force,
        force_sources=LANE_SOURCES,
    )


def _export_report_line(out: Path, report: ExportReport) -> str:
    """One line an operator (and CI) can read the whole export off.

    `uncovered_days` is E2's reseed signal, printed at EVERY build on purpose: the calendar is
    seeded a year at a time, so a horizon that runs past `known_years` is the normal state and
    the only thing that makes it visible is this number.
    """
    return (
        f"ios export written to {out} ({report.bytes} bytes, {report.pools} pools, "
        f"{report.sessions} sessions, {report.day_rows} day rows, {report.notices} notices, "
        f"{report.warnings} warnings, horizon {report.horizon_start}..{report.horizon_end}, "
        f"{report.uncovered_days} day(s) outside calendar coverage, "
        f"content {report.content_hash[:12]})"
    )


def _write_ios_manifest(*, store: Path, manifest: Path, url: str) -> int:
    """Write the release manifest beside a finished store. Exit code.

    The URL is REQUIRED rather than defaulted: where the store is hosted is the operator's
    call (hosting is out of scope), and a manifest carrying a placeholder URL is one a client
    would dutifully fetch and fail on.
    """
    if not url:
        print("--manifest requires --url (where the store will be hosted)", file=sys.stderr)
        return 2
    match write_manifest(store, manifest, url=url):
        case Ok(described):
            print(
                f"ios manifest written to {manifest} (schema {described.schema_version}, "
                f"built {described.built_at}, horizon end {described.horizon_end}, "
                f"{described.bytes} bytes, sha256 {described.sha256[:12]})"
            )
            return 0
        case Err(error):
            print(f"ios manifest failed: {describe(error)}", file=sys.stderr)
            return 1
        case _ as unreachable:
            assert_never(unreachable)


def export_ios_store(
    *,
    db_path: Path,
    out: Path,
    today: date,
    days: int,
    manifest: Path | None = None,
    url: str | None = None,
) -> int:
    """Project the gold store into the pre-resolved iOS store. Exit code.

    NETWORK-FREE by construction: it takes no `ProviderClients` at all — gold is the only input,
    which is why `main` dispatches it before the live clients are ever built.
    """
    if not db_path.exists():
        print(f"gold store not found at {db_path}; run `swimzh build` first", file=sys.stderr)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        match export_ios(conn, out, today=today, days=days):
            case Ok(report):
                print(_export_report_line(out, report))
                # The manifest describes the file that was just committed, so it is written
                # AFTER the export and only if the export succeeded: a manifest naming a store
                # that does not exist is a download every phone retries forever.
                if manifest is None:
                    return 0
                return _write_ios_manifest(store=out, manifest=manifest, url=url or "")
            case Err(error):
                print(f"ios export failed: {describe(error)}", file=sys.stderr)
                return 1
            case _ as unreachable:
                assert_never(unreachable)
    finally:
        conn.close()


def lake_command(args: argparse.Namespace) -> int:
    """`swimzh lake pull|export`: the two runtime seams of the lake. Exit code.

    `pull` is best-effort and loud (see `Lake.pull`): a missing origin makes the next build a
    first run, which the build itself then reports. `export` copies what is present.
    """
    lake = Lake(Path(args.lake))
    if args.lake_command == "pull":
        report = lake.pull(args.origin)
        for source, error in report.failed:
            print(f"lake pull: skipping {source}: {describe(error)}", file=sys.stderr)
        summary = ", ".join(report.pulled) or "nothing"
        if report.absent:
            summary += f" (absent: {', '.join(report.absent)})"
        if report.failed:
            summary += f" (failed: {', '.join(source for source, _ in report.failed)})"
        print(f"lake pulled from {args.origin} into {lake.root}: {summary}")
        return 0
    copied = lake.export(Path(args.out))
    print(f"lake exported to {args.out}: {', '.join(copied) or 'nothing'}")
    return 0


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

    # `build` and its two cadence wrappers share the store/data/lake flags: they ARE one command.
    store_flags = argparse.ArgumentParser(add_help=False)
    store_flags.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    store_flags.add_argument(
        "--data", default="data", help="curated data directory (default: data)"
    )
    store_flags.add_argument(
        "--lake",
        default=str(DEFAULT_LAKE_ROOT),
        help=(
            "the lake directory (silver per source; the previous run's facts stand in for an "
            f"unreachable source within its max_stale) (default: {DEFAULT_LAKE_ROOT})"
        ),
    )

    subparsers.add_parser(
        "build",
        parents=[cache_flags, store_flags],
        help="assemble a COMPLETE gold store (one atomic pipeline: roster+scrape+compose)",
    )

    # The lake's two runtime seams — where the previous silver comes from, where this one goes.
    # OFFLINE except `pull` reading an http(s) origin; neither touches a provider.
    lake_cmd = subparsers.add_parser(
        "lake", help="pull a previous publish into the lake, or export the lake for publishing"
    )
    lake_sub = lake_cmd.add_subparsers(dest="lake_command", required=True)
    lake_pull = lake_sub.add_parser(
        "pull", help="seed the lake's silver from a directory or an http(s) base (best effort)"
    )
    lake_pull.add_argument("origin", help="a directory or URL serving silver/<source>.json")
    lake_pull.add_argument("--lake", default=str(DEFAULT_LAKE_ROOT), help="the lake directory")
    lake_export = lake_sub.add_parser(
        "export", help="copy the lake's silver documents to <out>/silver/ for publishing"
    )
    lake_export.add_argument("--out", required=True, help="directory to export into")
    lake_export.add_argument("--lake", default=str(DEFAULT_LAKE_ROOT), help="the lake directory")

    catalog = subparsers.add_parser(
        "build-catalog", parents=[cache_flags], help="build the pool catalog from the WFS"
    )
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    subparsers.add_parser(
        "scrape-gold",
        parents=[cache_flags, store_flags],
        help=(
            "build with the schedule + price pages forced to refetch; the roster and lane plans "
            "are reused from the lake (the roster is fetched live only if the lake has none)"
        ),
    )
    subparsers.add_parser(
        "scrape-lanes",
        parents=[cache_flags, store_flags],
        help=(
            "build with the Belegungsplan lane plans forced to refetch; every other source is "
            "reused from the lake (the roster is fetched live only if the lake has none)"
        ),
    )

    # No `cache_flags`: the export touches no provider, so a cache switch would be a lie.
    ios = subparsers.add_parser(
        "export-ios", help="project the gold store into the pre-resolved iOS SQLite (offline)"
    )
    ios.add_argument("--db", required=True, help="path to the existing gold SQLite file")
    ios.add_argument("--out", required=True, help="path to the iOS SQLite file to write")
    ios.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"forward horizon in days (default: {DEFAULT_DAYS})",
    )
    ios.add_argument(
        "--manifest",
        help="also write the release manifest.json describing the exported store (needs --url)",
    )
    ios.add_argument(
        "--url",
        help="the URL the exported store will be served from; recorded in the manifest",
    )

    args = parser.parse_args(argv)
    now = _now()
    if args.command == "lake":
        return lake_command(args)
    if args.command == "export-ios":
        # Dispatched BEFORE any client is built: the export is offline, and building live
        # clients for it would open a connection pool nothing uses.
        return export_ios_store(
            db_path=Path(args.db),
            out=Path(args.out),
            today=now.date(),
            days=args.days,
            manifest=Path(args.manifest) if args.manifest else None,
            url=args.url,
        )
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
    if args.command == "build-catalog":
        return build_catalog_file(out=Path(args.out), client=clients.roster, generated_at=now)
    pipeline: dict[str, Callable[..., int]] = {
        "build": build,
        "scrape-gold": scrape_gold,
        "scrape-lanes": scrape_lanes,
    }
    return pipeline[args.command](
        db_path=Path(args.db),
        data_dir=Path(args.data),
        clients=clients,
        lake=Lake(Path(args.lake)),
        now=now,
        force=bool(args.refresh),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
