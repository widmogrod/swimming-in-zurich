"""Build schedule-bearing facilities by scraping each indoor pool's official page.

Best-effort by design: scraping is brittle, so a pool whose page fails to parse is *skipped*
(and reported), not fatal — the rest still produce real schedules. Only indoor pools are
scraped here (they share the stadt-zuerich.ch table format); other categories link out.
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
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.schedule import HolidayPolicy
from swimzh.providers.schedule_scraper import ScrapedSchedule, scrape_schedule

_SOURCE = "schedule_scraper"


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    facilities: tuple[Facility, ...]
    skipped: tuple[str, ...]  # pool names whose page could not be parsed


def _facility(entry: PoolCatalogEntry, schedule: ScrapedSchedule, fetched_at: datetime) -> Facility:
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
        public_holiday_policy=HolidayPolicy.NORMAL,
    )


def scrape_indoor_facilities(
    client: HttpClient, catalog: tuple[PoolCatalogEntry, ...], fetched_at: datetime
) -> ScrapeReport:
    facilities: list[Facility] = []
    skipped: list[str] = []
    for entry in catalog:
        if entry.kind is not PoolKind.INDOOR or not entry.url:
            continue
        match scrape_schedule(client, entry.url):
            case Ok(schedule):
                facilities.append(_facility(entry, schedule, fetched_at))
            case Err(_):
                skipped.append(entry.name)
    return ScrapeReport(facilities=tuple(facilities), skipped=tuple(skipped))
