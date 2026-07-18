"""End-to-end: load the real curated dataset and answer 'where can I swim?' for a date
matrix. This is the proof the data model answers the actual question before any provider
or UI exists.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.result import Ok
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import QueryResult, SwimQuery, find_swim_options
from swimzh.providers.curated import Dataset, load_dataset

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ZURICH = ZoneInfo("Europe/Zurich")
ADULT = Person(gender=Gender.MALE, age=40)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def test_dataset_loads_three_curated_pools(dataset: Dataset) -> None:
    names = {f.identity.name for f in dataset.facilities}
    assert names == {"Hallenbad City", "Hallenbad Oerlikon", "Hallenbad Bungertwies"}
    # Registry knows more than we have curated.
    assert len(dataset.registry.identities) == 7


def _query(dataset: Dataset, when: datetime, person: Person = ADULT) -> QueryResult:
    return find_swim_options(
        SwimQuery(person=person, at=when),
        dataset.facilities,
        dataset.calendar,
        registry=dataset.registry,
    )


def test_uncurated_facilities_are_distinguished_from_closed(dataset: Dataset) -> None:
    # A normal Wednesday afternoon in term.
    result = _query(dataset, datetime(2026, 3, 11, 14, 0, tzinfo=ZURICH))
    uncurated = [s for s in result.statuses if s.status == "uncurated"]
    assert {s.facility_name for s in uncurated} == {
        "Hallenbad Altstetten",
        "Hallenbad Bläsi",
        "Hallenbad Leimbach",
        "Wärmebad Käferberg",
    }


def test_evening_public_swim_is_open_and_eligible(dataset: Dataset) -> None:
    # Tuesday 18:00 in term: City 50m public (11:00–22:00) is open and open-to-all.
    result = _query(dataset, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH))
    open_eligible = [o for o in result.eligible_options() if o.open_at_query_time]
    assert open_eligible, "expected at least one open, eligible option on a Tuesday evening"
    city = [o for o in open_eligible if o.facility_name == "Hallenbad City"]
    assert city, "City should be open Tuesday 18:00"
    assert city[0].price is not None
    assert city[0].price.display == "Erwachsene CHF 8.00"
    assert city[0].provenance.curated is True
    assert city[0].provenance.valid_as_of is not None


def test_good_friday_oerlikon_closed_city_open(dataset: Dataset) -> None:
    # Karfreitag 2026-04-03: Oerlikon closes on public holidays; City runs Sunday schedule.
    result = _query(dataset, datetime(2026, 4, 3, 12, 0, tzinfo=ZURICH))
    closed = {s.facility_name for s in result.statuses if s.status == "closed"}
    assert "Hallenbad Oerlikon" in closed
    open_facilities = {o.facility_name for o in result.options}
    assert "Hallenbad City" in open_facilities


def test_maintenance_week_city_closed(dataset: Dataset) -> None:
    # 2026-07-20 falls in City's Sommerpause / Revision closure.
    result = _query(dataset, datetime(2026, 7, 20, 12, 0, tzinfo=ZURICH))
    closed = {s.facility_name for s in result.statuses if s.status == "closed"}
    assert "Hallenbad City" in closed


def test_no_live_occupancy_without_provider(dataset: Dataset) -> None:
    result = _query(dataset, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH))
    assert all(o.live_occupancy is None for o in result.options)


def test_future_year_warns_about_calendar_coverage(dataset: Dataset) -> None:
    result = _query(dataset, datetime(2030, 3, 12, 18, 0, tzinfo=ZURICH))
    assert any("calendar data not available" in w for w in result.warnings)
