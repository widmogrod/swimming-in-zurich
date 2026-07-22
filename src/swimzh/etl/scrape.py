"""Scrape each indoor pool's official page into an identity-free ``(SourceRef, aspects)`` extract.

Per pool we scrape: the timetable (→ rules), notices/alerts (→ `Notice`s, and closure-type
notices → `ClosureRange`s), and attach the shared scraped admission `PriceTable` for city-run
pools. The result is a ``ScrapedAspects`` payload paired with a ``Name`` ``SourceRef`` (the WFS
display name) — **never a canonical id**. ``build.reconcile.resolve_all`` turns each ``Name``
into a ``PoolId`` by lookup, and ``build.compose`` folds the aspects onto the matching pool. A
pool whose page fails to parse is skipped and reported (best-effort).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from swimzh.build.compose import ScrapedAspects
from swimzh.build.reconcile import Name, SourceRef
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Basin, BasinId, Notice, PoolKind
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import ClosureRange
from swimzh.providers.schedule_scraper import (
    ScrapedSchedule,
    fetch_page,
    parse_notices,
    parse_schedule,
)

_CLOSURE_WORDS = ("geschlossen", "revision", "gesperrt", "betriebsferien")
_CITY_HOST = "stadt-zuerich.ch"

# One scrape extract: a reference the reconcile seam resolves to a PoolId, plus its payload.
Extract = tuple[SourceRef, ScrapedAspects]


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    extracts: tuple[Extract, ...]  # (SourceRef, ScrapedAspects) — no canonical id minted here
    skipped: tuple[str, ...]  # pool names whose page could not be parsed


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
    skipped: list[str] = []
    for entry in catalog:
        if entry.kind is not PoolKind.INDOOR or not entry.url:
            continue
        match fetch_page(client, entry.url):
            case Err(_):
                skipped.append(entry.name)
                continue
            case Ok(raw):
                page = raw.decode("utf-8", "replace")

        schedule = parse_schedule(page)
        if isinstance(schedule, Err):
            skipped.append(entry.name)
            continue
        notices = parse_notices(page)
        pool_prices = prices if (prices is not None and _CITY_HOST in entry.url) else None
        aspects = _aspects(
            entry,
            schedule.value,
            notices,
            _closures_from_notices(notices),
            pool_prices,
            fetched_at,
        )
        extracts.append((Name(entry.name), aspects))
    return ScrapeReport(extracts=tuple(extracts), skipped=tuple(skipped))
