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
from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.domain.models import Facility, PoolKind
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def scheduled_facility() -> Facility:
    """A real curated facility that is indoor AND carries ≥1 rule (Hallenbad City) — so stripping
    its rules exercises the `awaiting_scrape` branch, not a school's `no_source`."""
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    facility = next(
        f
        for f in result.value.facilities
        if f.identity.kind is PoolKind.INDOOR and any(b.rules for b in f.basins)
    )
    return facility


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
    # A `school` pool is not scraped by `scrape_indoor_facilities`, so a schedule-less school
    # (e.g. `aemtler`) stays permanently no_source — never awaiting_scrape.
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
