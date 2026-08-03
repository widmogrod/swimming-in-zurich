"""Scrape each indoor pool's official page into an identity-free ``(SourceRef, aspects)`` extract.

Per pool we scrape: the timetable (→ rules), notices/alerts (→ `Notice`s, and closure-type
notices → `ClosureRange`s), and attach the shared scraped admission `PriceTable` for city-run
pools. The result is a ``ScrapedAspects`` payload paired with a ``Name`` ``SourceRef`` (the WFS
display name) — **never a canonical id**. ``build.reconcile.resolve_all`` turns each ``Name``
into a ``PoolId`` by lookup, and ``build.compose`` folds the aspects onto the matching pool.

**Fail-fast (S4):** a declared source (an INDOOR catalog pool with a page URL) whose page fails
to fetch or parse is **NOT skipped**. Its typed ``ProviderError`` is preserved in
``ScrapeReport.failures`` so the ``scrape-gold`` command aborts the whole run non-zero carrying
that cause (owner decision 2026-07-28: no green-exit-with-a-hole). The best-effort skip-and-report
posture is gone; the typed error *value* stays.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from swimzh.build.compose import ScrapedAspects
from swimzh.build.reconcile import Name, SourceRef
from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Basin, BasinId, Notice, PoolKind
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import ClosureRange
from swimzh.providers.operator_pages import parse_maintenance_closures
from swimzh.providers.schedule_scraper import (
    ScrapedSchedule,
    fetch_page,
    parse_notices,
    parse_schedule,
)

_CLOSURE_WORDS = ("geschlossen", "revision", "gesperrt", "betriebsferien")
_CITY_HOST = "stadt-zuerich.ch"

#: Per-pool extra closure extractors for pools whose page is a **private operator's**, not the
#: city's. Keyed by `pool_id` — deliberately NOT by host: `freibad-dolder`'s operator changed
#: domain (doldersports.com → doldereisundbad.ch) without notice, and a host-keyed table would
#: have fallen through silently. `pool_id` is the identity spine and is the only stable key.
#:
#: This is a dispatch, not another entry in `schedule_scraper._PARSERS`: that chain is
#: format-sniffing and pool-blind (first `Ok` wins, tried against all 57 pages), which on these
#: sites is a wrong-answer generator rather than a fallback.
_OPERATOR_CLOSURES: Mapping[str, Callable[[str], tuple[ClosureRange, ...]]] = {
    "hallenbad-altstetten": parse_maintenance_closures,
}

# One scrape extract: a reference the reconcile seam resolves to a PoolId, plus its payload.
Extract = tuple[SourceRef, ScrapedAspects]


@dataclass(frozen=True, slots=True)
class ScrapeFailure:
    """A declared source (INDOOR catalog pool) whose page failed to fetch or parse, keyed to its
    **typed** ``ProviderError`` cause. Not a swallowed skip: ``scrape-gold`` aborts the whole run
    on any of these, surfacing the cause (S4 fail-fast)."""

    name: str
    url: str
    cause: ProviderError


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    extracts: tuple[Extract, ...]  # (SourceRef, ScrapedAspects) — no canonical id minted here
    failures: tuple[ScrapeFailure, ...]  # declared sources that failed (typed cause preserved)


def _closures_from_notices(notices: tuple[Notice, ...]) -> tuple[ClosureRange, ...]:
    return tuple(
        ClosureRange(start=n.active_from, end=n.active_to, reason=n.text)
        for n in notices
        if n.active_from is not None
        and n.active_to is not None
        and any(word in n.text.lower() for word in _CLOSURE_WORDS)
    )


def _aspects(
    entry: PoolCatalogEntry,
    schedule: ScrapedSchedule,
    notices: tuple[Notice, ...],
    closures: tuple[ClosureRange, ...],
    prices: PriceTable | None,
    fetched_at: datetime,
) -> ScrapedAspects:
    return ScrapedAspects(
        name=entry.name,
        kind=entry.kind,
        address=entry.address,
        geo=entry.geo,
        basins=(
            Basin(
                basin_id=BasinId(f"{entry.pool_id}-main"), name="Hauptbecken", rules=schedule.rules
            ),
        ),
        closures=closures,
        notices=notices,
        prices=prices,
        fetched_at=fetched_at,
    )


def scrape_indoor_facilities(
    client: HttpClient,
    catalog: tuple[PoolCatalogEntry, ...],
    fetched_at: datetime,
    *,
    prices: PriceTable | None = None,
) -> ScrapeReport:
    extracts: list[Extract] = []
    failures: list[ScrapeFailure] = []
    for entry in catalog:
        if entry.kind is not PoolKind.INDOOR or not entry.url:
            continue
        match fetch_page(client, entry.url):
            case Err(cause):
                failures.append(ScrapeFailure(name=entry.name, url=entry.url, cause=cause))
                continue
            case Ok(raw):
                page = raw.decode("utf-8", "replace")

        schedule = parse_schedule(page)
        if isinstance(schedule, Err):
            failures.append(ScrapeFailure(name=entry.name, url=entry.url, cause=schedule.error))
            continue
        notices = parse_notices(page)
        pool_prices = prices if (prices is not None and _CITY_HOST in entry.url) else None
        # City notices carry their own dates; an operator page states its shutdown in prose,
        # so the two closure sources are additive, not alternatives.
        operator = _OPERATOR_CLOSURES.get(entry.pool_id)
        closures = _closures_from_notices(notices)
        if operator is not None:
            closures = closures + operator(page)
        aspects = _aspects(
            entry,
            schedule.value,
            notices,
            closures,
            pool_prices,
            fetched_at,
        )
        extracts.append((Name(entry.name), aspects))
    return ScrapeReport(extracts=tuple(extracts), failures=tuple(failures))
