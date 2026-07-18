"""Build schedule-bearing facilities by scraping each indoor pool's official page.

Per pool we scrape: the timetable (→ rules), notices/alerts (→ `Notice`s, and closure-type
notices → `ClosureRange`s), and attach the shared scraped admission `PriceTable` for
city-run pools. Best-effort: a pool whose page fails to parse is skipped and reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    FacilityId,
    Notice,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import ClosureRange, HolidayPolicy
from swimzh.providers.schedule_scraper import (
    ScrapedSchedule,
    fetch_page,
    parse_notices,
    parse_schedule,
)

_SOURCE = "schedule_scraper"
_CLOSURE_WORDS = ("geschlossen", "revision", "gesperrt", "betriebsferien")
_CITY_HOST = "stadt-zuerich.ch"


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    facilities: tuple[Facility, ...]
    skipped: tuple[str, ...]  # pool names whose page could not be parsed


def _closures_from_notices(notices: tuple[Notice, ...]) -> tuple[ClosureRange, ...]:
    return tuple(
        ClosureRange(start=n.active_from, end=n.active_to, reason=n.text)
        for n in notices
        if n.active_from is not None
        and n.active_to is not None
        and any(word in n.text.lower() for word in _CLOSURE_WORDS)
    )


def _facility(
    entry: PoolCatalogEntry,
    schedule: ScrapedSchedule,
    notices: tuple[Notice, ...],
    closures: tuple[ClosureRange, ...],
    prices: PriceTable | None,
    fetched_at: datetime,
) -> Facility:
    return Facility(
        identity=PoolIdentity(
            facility_id=FacilityId(entry.pool_id), name=entry.name, kind=entry.kind
        ),
        address=entry.address,
        provenance=Provenance(
            source=_SOURCE, curated=False, valid_as_of=fetched_at.date(), fetched_at=fetched_at
        ),
        basins=(
            Basin(
                basin_id=BasinId(f"{entry.pool_id}-main"), name="Hauptbecken", rules=schedule.rules
            ),
        ),
        geo=entry.geo,
        closures=closures,
        public_holiday_policy=HolidayPolicy.NORMAL,
        prices=prices,
        notices=notices,
    )


def scrape_indoor_facilities(
    client: HttpClient,
    catalog: tuple[PoolCatalogEntry, ...],
    fetched_at: datetime,
    *,
    prices: PriceTable | None = None,
) -> ScrapeReport:
    facilities: list[Facility] = []
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
        facilities.append(
            _facility(
                entry,
                schedule.value,
                notices,
                _closures_from_notices(notices),
                pool_prices,
                fetched_at,
            )
        )
    return ScrapeReport(facilities=tuple(facilities), skipped=tuple(skipped))
