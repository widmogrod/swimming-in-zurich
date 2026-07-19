"""End-to-end: load the real curated dataset and answer 'where can I swim?' for a date
matrix. This is the proof the data model answers the actual question before any provider
or UI exists.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.errors import ProviderError, Timeout, describe
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import PublicSwim
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import (
    LiveOccupancy,
    Occupancy,
    OccupancyUnavailable,
    QueryResult,
    SwimQuery,
    find_swim_options,
)
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday
from swimzh.providers.curated import Dataset, load_dataset

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ZURICH = ZoneInfo("Europe/Zurich")
ADULT = Person(gender=Gender.MALE, age=40)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def test_dataset_loads_four_curated_pools(dataset: Dataset) -> None:
    names = {f.identity.name for f in dataset.facilities}
    assert names == {
        "Hallenbad City",
        "Hallenbad Oerlikon",
        "Hallenbad Bungertwies",
        "Schulschwimmanlage Aemtler",
    }
    # Registry knows more than we have curated.
    assert len(dataset.registry.identities) == 8


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


def test_options_carry_basin_physicals(dataset: Dataset) -> None:
    # Tuesday 18:00: the City 50m option surfaces the basin's kind and its stated lane
    # count (6 Bahnen); a fact the curated data does NOT state (nominal temp) stays None —
    # never invented.
    result = _query(dataset, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH))
    city_50m = [o for o in result.options if str(o.basin_id) == "city-50m"]
    assert city_50m, "expected the City 50m basin among Tuesday-evening options"
    option = city_50m[0]
    assert option.basin_kind is BasinKind.LAP
    assert option.lanes == 6
    assert option.water_temp_c is None


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


def test_school_pool_adults_only_window_rejects_child(dataset: Dataset) -> None:
    # Monday 2026-03-09 19:00 in term: Aemtler runs an adults-only window 18:00-21:00.
    # The correctness bug AdultsOnly exists to prevent: a child must NOT be told
    # "you can swim" just because the window is public.
    when = datetime(2026, 3, 9, 19, 0, tzinfo=ZURICH)
    child = _query(dataset, when, person=Person(gender=Gender.FEMALE, age=10))
    open_aemtler = [
        o for o in child.options if str(o.facility_id) == "aemtler" and o.open_at_query_time
    ]
    assert open_aemtler, "expected the Aemtler adults-only window among Monday-evening options"
    option = open_aemtler[0]
    assert option.eligibility.allowed is False
    assert option.eligibility.rule == "adults-only"
    assert "requires age 18+" in option.eligibility.reason
    # The same window admits an adult.
    adult = _query(dataset, when)
    open_adult = [
        o for o in adult.options if str(o.facility_id) == "aemtler" and o.open_at_query_time
    ]
    assert open_adult and open_adult[0].eligibility.allowed is True


def test_school_pool_daytime_is_school_reserved_in_term(dataset: Dataset) -> None:
    # Wednesday 2026-03-11 14:00 in term: school time — reserved, not public.
    result = _query(dataset, datetime(2026, 3, 11, 14, 0, tzinfo=ZURICH))
    open_aemtler = [
        o for o in result.options if str(o.facility_id) == "aemtler" and o.open_at_query_time
    ]
    assert open_aemtler
    assert all(o.eligibility.allowed is False for o in open_aemtler)
    assert open_aemtler[0].eligibility.rule == "school-reserved"


def test_school_pool_opens_to_public_in_school_holidays(dataset: Dataset) -> None:
    # Monday 2026-07-20 10:00 (Sommerferien): the daytime block is public; the term-scoped
    # school-reserved and adults-only rules must not fire.
    result = _query(dataset, datetime(2026, 7, 20, 10, 0, tzinfo=ZURICH))
    aemtler = [o for o in result.options if str(o.facility_id) == "aemtler"]
    assert aemtler
    assert {o.eligibility.rule for o in aemtler} == {"public"}
    assert all(o.eligibility.allowed for o in aemtler)


def test_no_live_occupancy_without_provider(dataset: Dataset) -> None:
    result = _query(dataset, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH))
    assert all(o.live_occupancy is None for o in result.options)


# --- Live occupancy attach (fake provider — the real CrowdMonitor adapter is deferred
# --- pending the ToS check recorded in data/sources.md) ---------------------------------


class _FakeOccupancyProvider:
    """In-memory `OccupancyProvider`: returns a canned Result and records calls."""

    def __init__(self, result: Result[Occupancy, ProviderError]) -> None:
        self._result = result
        self.calls: list[tuple[str, ...]] = []

    def read(self, keys: tuple[str, ...]) -> Result[Occupancy, ProviderError]:
        self.calls.append(keys)
        return self._result


def _keyed_facility(keys: tuple[str, ...]) -> Facility:
    """A synthetic facility whose one basin is open the entire day, every day, so a
    wall-clock 'now' query always yields an option regardless of when tests run.
    `time.max` (23:59:59.999999) because `TimeRange.contains` is end-exclusive — a
    23:59 end would leave the last minute of the day uncovered."""
    all_day = ScheduleRule(
        weekdays=frozenset(Weekday),
        time=TimeRange(time(0, 0), time.max),
        access=PublicSwim(),
    )
    return Facility(
        identity=PoolIdentity(
            facility_id=FacilityId("occ-test"),
            name="Hallenbad Occupancy-Test",
            kind=PoolKind.INDOOR,
            crowdmonitor_keys=keys,
        ),
        address="Teststrasse 1, Zürich",
        provenance=Provenance(source="test", curated=True),
        basins=(Basin(basin_id=BasinId("occ-main"), name="Hauptbecken", rules=(all_day,)),),
    )


def _reading(measured_at: datetime) -> Occupancy:
    return Occupancy(
        facility_id=FacilityId("occ-test"),
        measured_at=measured_at,
        percent_full=62.0,
        people=93,
        capacity=150,
        source="fake",
    )


def test_now_query_attaches_live_occupancy(dataset: Dataset) -> None:
    now = datetime.now(ZURICH)
    provider = _FakeOccupancyProvider(Ok(_reading(now - timedelta(minutes=5))))
    result = find_swim_options(
        SwimQuery(person=ADULT, at=now),
        (_keyed_facility(("Occupancy-Test", "Hallenbad Occupancy-Test")),),
        dataset.calendar,
        occupancy=provider,
    )
    assert result.options, "the 24/7 test basin must yield an option"
    live = result.options[0].live_occupancy
    assert isinstance(live, LiveOccupancy)
    assert live.reading.people == 93
    assert live.reading.percent_full == 62.0
    # age is derived at attach time from measured_at (~5 min ago), not stored upstream.
    assert timedelta(minutes=4) < live.age < timedelta(minutes=6)
    assert live.is_stale() is False
    # The provider is keyed by the facility's crowdmonitor keys, once per facility.
    assert provider.calls == [("Occupancy-Test", "Hallenbad Occupancy-Test")]


def test_future_query_does_not_request_occupancy(dataset: Dataset) -> None:
    provider = _FakeOccupancyProvider(Ok(_reading(datetime.now(ZURICH))))
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime.now(ZURICH) + timedelta(days=2)),
        (_keyed_facility(("Occupancy-Test",)),),
        dataset.calendar,
        occupancy=provider,
    )
    assert result.options
    assert all(o.live_occupancy is None for o in result.options)  # None = not requested
    assert provider.calls == []


def test_provider_error_becomes_occupancy_unavailable(dataset: Dataset) -> None:
    error = Timeout(url="wss://occupancy.example.test/api", after_s=3.0)
    provider = _FakeOccupancyProvider(Err(error))
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime.now(ZURICH)),
        (_keyed_facility(("Occupancy-Test",)),),
        dataset.calendar,
        occupancy=provider,
    )
    assert result.options
    assert result.options[0].live_occupancy == OccupancyUnavailable(reason=describe(error))


def test_facility_without_crowdmonitor_keys_is_unavailable(dataset: Dataset) -> None:
    provider = _FakeOccupancyProvider(Ok(_reading(datetime.now(ZURICH))))
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime.now(ZURICH)),
        (_keyed_facility(()),),
        dataset.calendar,
        occupancy=provider,
    )
    assert result.options
    assert result.options[0].live_occupancy == OccupancyUnavailable(reason="no crowdmonitor key")
    assert provider.calls == []  # never asked without a key


def test_naive_measured_at_is_rejected_at_construction() -> None:
    # A future real adapter returning a naive datetime must fail loudly at the boundary,
    # not as a TypeError escaping from the age subtraction inside find_swim_options.
    with pytest.raises(ValueError, match="tz-aware"):
        _reading(datetime(2026, 3, 10, 18, 0))


def test_staleness_is_derived_not_stored() -> None:
    reading = _reading(datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH))
    assert LiveOccupancy(reading=reading, age=timedelta(minutes=9)).is_stale() is False
    stale = LiveOccupancy(reading=reading, age=timedelta(minutes=11))
    assert stale.is_stale() is True
    assert stale.is_stale(limit=timedelta(minutes=20)) is False
    # No stored freshness enum / age_s shadow field — freshness derives from the reading.
    assert {f.name for f in dataclasses.fields(LiveOccupancy)} == {"reading", "age"}


def test_future_year_warns_about_calendar_coverage(dataset: Dataset) -> None:
    result = _query(dataset, datetime(2030, 3, 12, 18, 0, tzinfo=ZURICH))
    assert any("calendar data not available" in w for w in result.warnings)
