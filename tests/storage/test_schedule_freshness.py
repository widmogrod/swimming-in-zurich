"""The shared three-state curation model: `codec.schedule_freshness` derives a pool's
`ScheduleFreshness` from its schedule blob (kind + rules presence), never a stored column.

Replaced the `is_curated` boolean (delete-curated-schedule-tier S1):

* SCRAPED         — the blob is present AND ≥1 basin carries ≥1 rule.
* AWAITING_SCRAPE — no rule yet AND the pool is scrapeable (`kind == indoor`, or `thermal` — a
  Wärmebad is WFS-indoor, registry-overridden to thermal for display, and IS scraped).
* NO_SOURCE       — no rule AND not a scrapeable kind (e.g. a school pool), OR a NULL blob.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from swimzh.domain.access import PublicSwim
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday
from swimzh.storage import codec


@pytest.fixture(scope="module")
def scheduled_facility() -> Facility:
    """An indoor facility carrying ≥1 rule — the shape a scraped stadt-zuerich pool takes once its
    timetable is composed on. Built in-memory (curated YAML no longer carries any schedule after
    delete-curated-schedule-tier S3), so stripping the rule exercises `awaiting_scrape`."""
    rule = ScheduleRule(
        weekdays=frozenset({Weekday.MONDAY}),
        time=TimeRange(start=time(11, 0), end=time(22, 0)),
        access=PublicSwim(),
    )
    return Facility(
        identity=PoolIdentity(PoolId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="Sihlstrasse 71, 8001 Zürich",
        provenance=Provenance(source="schedule_scraper", curated=False),
        basins=(Basin(basin_id=BasinId("hallenbad-city-main"), name="Hauptbecken", rules=(rule,)),),
    )


def _ruleless(facility: Facility) -> Facility:
    return replace(facility, basins=tuple(replace(b, rules=()) for b in facility.basins))


def test_null_blob_is_no_source() -> None:
    assert codec.schedule_freshness(None) is ScheduleFreshness.NO_SOURCE


def test_blob_with_a_ruled_basin_is_scraped(scheduled_facility: Facility) -> None:
    assert codec.schedule_freshness(codec.dumps(scheduled_facility)) is ScheduleFreshness.SCRAPED


def test_indoor_schedule_less_pool_is_awaiting_scrape(scheduled_facility: Facility) -> None:
    # No rule yet, but the pool is an indoor stadt-zuerich pool → scrapeable → awaiting_scrape.
    assert scheduled_facility.identity.kind is PoolKind.INDOOR
    ruleless = _ruleless(scheduled_facility)
    assert codec.schedule_freshness(codec.dumps(ruleless)) is ScheduleFreshness.AWAITING_SCRAPE


def test_school_schedule_less_pool_is_no_source(scheduled_facility: Facility) -> None:
    # Only 4 of the 18 Schulschwimmanlagen are declared sources (the other 14 share one overview
    # URL, which `etl.scrape.declared_sources` excludes). Those 4 carry rules and so read
    # `scraped` from the blob; a schedule-less school (e.g. `schulschwimmanlage-hardau`) stays
    # permanently no_source — never awaiting_scrape, which would promise a scrape that will not
    # come. This is why `freshness_of`'s kind test deliberately omits SCHOOL.
    school = _ruleless(
        replace(
            scheduled_facility,
            identity=replace(scheduled_facility.identity, kind=PoolKind.SCHOOL),
        )
    )
    assert codec.schedule_freshness(codec.dumps(school)) is ScheduleFreshness.NO_SOURCE


def test_thermal_schedule_less_pool_is_awaiting_scrape(scheduled_facility: Facility) -> None:
    # A `thermal` Wärmebad (e.g. Käferberg) is WFS-indoor and IS scraped, so a schedule-less
    # thermal pool is awaiting_scrape, not no_source — despite its registry-override display kind.
    thermal = _ruleless(
        replace(
            scheduled_facility,
            identity=replace(scheduled_facility.identity, kind=PoolKind.THERMAL),
        )
    )
    assert codec.schedule_freshness(codec.dumps(thermal)) is ScheduleFreshness.AWAITING_SCRAPE


def test_blob_without_any_basin_is_no_source_when_not_indoor(scheduled_facility: Facility) -> None:
    outdoor = replace(
        scheduled_facility,
        identity=replace(scheduled_facility.identity, kind=PoolKind.OUTDOOR),
        basins=(),
    )
    assert codec.schedule_freshness(codec.dumps(outdoor)) is ScheduleFreshness.NO_SOURCE
