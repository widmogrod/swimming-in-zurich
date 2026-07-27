"""End-to-end: load the real curated dataset and answer 'where can I swim?' for a date
matrix. This is the proof the data model answers the actual question before any provider
or UI exists.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.errors import ProviderError, Timeout, describe
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import ClubReserved, PublicSwim, ReasonCode
from swimzh.domain.catalog import PoolCatalogEntry, RosterEntry
from swimzh.domain.lane_plan import (
    LaneAvailability,
    LanePlan,
    LaneReservation,
    PlanConfidence,
    PlanCoverage,
)
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import (
    LiveOccupancy,
    LiveTemp,
    Occupancy,
    OccupancyUnavailable,
    QueryResult,
    SwimQuery,
    TempReading,
    TempUnavailable,
    TempUnavailableCode,
    find_swim_options,
    read_temperature,
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


def test_dataset_loads_curated_and_lane_plan_only_pools(dataset: Dataset) -> None:
    names = {f.identity.name for f in dataset.facilities}
    assert names == {
        # Fully curated (schedules).
        "Hallenbad City",
        "Hallenbad Oerlikon",
        "Hallenbad Bungertwies",
        "Schulschwimmanlage Aemtler",
        # Lane-plan-only (schedule-less basin carrying a lane_plan_source).
        "Hallenbad Leimbach",
        "Hallenbad Bläsi",
        "Wärmebad Käferberg",
    }
    # Registry knows more than we have curated (25 since S4 added identity-only entries for every
    # reconcilable Baditicker pool so their live water-temp `baditicker_poiid` survives onto the
    # location-only facility the build mints — 9 through S1/S2 + 16 new outdoor/river/lake pins).
    assert len(dataset.registry.identities) == 25


def _roster(dataset: Dataset) -> tuple[RosterEntry, ...]:
    """The roster the app feeds `find_swim_options`, here derived from the curated dataset's
    registry (25 known pools after S4) so the three-state `uncurated = roster − scheduled` answer
    is exercised without a gold DB."""
    return tuple(
        RosterEntry(
            entry=PoolCatalogEntry(
                pool_id=str(identity.facility_id),
                name=identity.name,
                kind=identity.kind,
                address="",
                geo=None,
                url=None,
                description=None,
                phone=None,
            ),
            curated=False,
        )
        for identity in dataset.registry.identities.values()
    )


def _query(dataset: Dataset, when: datetime, person: Person = ADULT) -> QueryResult:
    return find_swim_options(
        SwimQuery(person=person, at=when),
        dataset.facilities,
        dataset.calendar,
        _roster(dataset),
    )


def test_uncurated_facilities_are_distinguished_from_closed(dataset: Dataset) -> None:
    # A normal Wednesday afternoon in term.
    result = _query(dataset, datetime(2026, 3, 11, 14, 0, tzinfo=ZURICH))
    uncurated = [s for s in result.statuses if s.status == "uncurated"]
    assert {s.facility_name for s in uncurated} == {
        # Registry-known but not scheduled (identity-only or lane-plan-only) → "uncurated", never
        # "closed". S4 grew this set: every reconcilable Baditicker pool now carries a registry
        # identity so its live water-temp key survives onto the location-only facility.
        "Hallenbad Altstetten",
        "Hallenbad Bläsi",
        "Hallenbad Leimbach",
        "Wärmebad Käferberg",
        "Freibad Heuried",  # S1: registry-known outdoor pin, no schedule → uncurated (not closed)
        # S4: the outdoor/river/lake pins that gained a Baditicker `baditicker_poiid`.
        "Freibad Allenmoos",
        "Freibad Auhof",
        "Freibad Dolder",
        "Freibad Letzigraben",
        "Freibad Seebach",
        "Freibad Zwischen den Hölzern",
        "Flussbad Au-Höngg",
        "Flussbad Oberer Letten",
        "Frauenbad Stadthausquai",
        "Männerbad Schanzengraben",
        "Seebad Enge",
        "Seebad Katzensee",
        "Seebad Utoquai",
        "Strandbad Mythenquai",
        "Strandbad Tiefenbrunnen",
        "Strandbad Wollishofen",
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
        o
        for o in child.options
        if str(o.facility_id) == "schulschwimmanlage-aemtler" and o.open_at_query_time
    ]
    assert open_aemtler, "expected the Aemtler adults-only window among Monday-evening options"
    option = open_aemtler[0]
    assert option.eligibility.allowed is False
    assert option.eligibility.rule == "adults-only"
    assert option.eligibility.code is ReasonCode.ADULTS_ONLY_TOO_YOUNG
    assert option.eligibility.params == {"min_age": 18}
    # The same window admits an adult.
    adult = _query(dataset, when)
    open_adult = [
        o
        for o in adult.options
        if str(o.facility_id) == "schulschwimmanlage-aemtler" and o.open_at_query_time
    ]
    assert open_adult and open_adult[0].eligibility.allowed is True


def test_school_pool_daytime_is_school_reserved_in_term(dataset: Dataset) -> None:
    # Wednesday 2026-03-11 14:00 in term: school time — reserved, not public.
    result = _query(dataset, datetime(2026, 3, 11, 14, 0, tzinfo=ZURICH))
    open_aemtler = [
        o
        for o in result.options
        if str(o.facility_id) == "schulschwimmanlage-aemtler" and o.open_at_query_time
    ]
    assert open_aemtler
    assert all(o.eligibility.allowed is False for o in open_aemtler)
    assert open_aemtler[0].eligibility.rule == "school-reserved"


def test_school_pool_opens_to_public_in_school_holidays(dataset: Dataset) -> None:
    # Monday 2026-07-20 10:00 (Sommerferien): the daytime block is public; the term-scoped
    # school-reserved and adults-only rules must not fire.
    result = _query(dataset, datetime(2026, 7, 20, 10, 0, tzinfo=ZURICH))
    aemtler = [o for o in result.options if str(o.facility_id) == "schulschwimmanlage-aemtler"]
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
            facility_id=PoolId("occ-test"),
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
        facility_id=PoolId("occ-test"),
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


# --- Live water temperature attach (fake provider — the real Baditicker adapter is deferred
# --- to a later slice) -------------------------------------------------------------------


class _FakeTemperatureProvider:
    """In-memory `TemperatureProvider`: returns a canned Result and records the poiids asked."""

    def __init__(self, result: Result[TempReading, ProviderError]) -> None:
        self._result = result
        self.calls: list[str] = []

    def read(self, poiid: str) -> Result[TempReading, ProviderError]:
        self.calls.append(poiid)
        return self._result


def _temp_reading(measured_at: datetime, celsius: Decimal | None = Decimal("23.0")) -> TempReading:
    return TempReading(measured_at=measured_at, celsius=celsius, is_open=True, source="baditicker")


def _keyed_identity(poiid: str | None) -> PoolIdentity:
    return PoolIdentity(
        facility_id=PoolId("temp-test"),
        name="Freibad Temp-Test",
        kind=PoolKind.OUTDOOR,
        baditicker_poiid=poiid,
    )


def test_read_temperature_attaches_live_temp_with_derived_age() -> None:
    now = datetime.now(ZURICH)
    provider = _FakeTemperatureProvider(Ok(_temp_reading(now - timedelta(minutes=42))))
    result = read_temperature(provider, _keyed_identity("fb012"), now)
    assert isinstance(result, LiveTemp)
    assert result.reading.celsius == Decimal("23.0")
    # age is derived at attach time from measured_at (~42 min ago), not stored upstream.
    assert timedelta(minutes=41) < result.age < timedelta(minutes=43)
    assert result.is_stale() is False  # well within the 6h default limit
    assert provider.calls == ["fb012"]  # keyed by the identity's baditicker poiid, once


def test_read_temperature_empty_cell_is_live_temp_with_none_celsius() -> None:
    # Pinned: an empty feed cell (measured nothing yet) is still a LiveTemp — we know
    # open/closed + freshness — NEVER a TempUnavailable.
    now = datetime.now(ZURICH)
    provider = _FakeTemperatureProvider(Ok(_temp_reading(now - timedelta(minutes=5), celsius=None)))
    result = read_temperature(provider, _keyed_identity("fb012"), now)
    assert isinstance(result, LiveTemp)
    assert result.reading.celsius is None


def test_read_temperature_without_key_is_unavailable() -> None:
    provider = _FakeTemperatureProvider(Ok(_temp_reading(datetime.now(ZURICH))))
    result = read_temperature(provider, _keyed_identity(None), datetime.now(ZURICH))
    assert result == TempUnavailable(reason="no baditicker key", code=TempUnavailableCode.NO_KEY)
    # The CODE is what the UI renders — "no baditicker key" is operator jargon, and the
    # pseudolocale pass caught it being shown to users verbatim.
    assert result.code is TempUnavailableCode.NO_KEY
    assert provider.calls == []  # never asked without a key


def test_read_temperature_provider_error_becomes_unavailable() -> None:
    error = Timeout(url="https://www.stadt-zuerich.ch/stzh/bathdatadownload", after_s=3.0)
    provider = _FakeTemperatureProvider(Err(error))
    result = read_temperature(provider, _keyed_identity("fb012"), datetime.now(ZURICH))
    # No exception escapes the errors-as-values surface; the cause is described.
    assert result == TempUnavailable(reason=describe(error))


def test_temp_reading_naive_measured_at_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        _temp_reading(datetime(2026, 7, 25, 20, 39))


def test_live_temp_staleness_is_derived_not_stored() -> None:
    reading = _temp_reading(datetime(2026, 7, 25, 20, 39, tzinfo=ZURICH))
    assert LiveTemp(reading=reading, age=timedelta(hours=5)).is_stale() is False
    stale = LiveTemp(reading=reading, age=timedelta(hours=7))
    assert stale.is_stale() is True
    assert stale.is_stale(limit=timedelta(hours=8)) is False
    # No stored freshness enum — freshness derives from the reading via `age`.
    assert {f.name for f in dataclasses.fields(LiveTemp)} == {"reading", "age"}


# --- Lane availability (query-time derivation of the STORED lane plan) -------------------
#
# Unlike occupancy, lane availability is a pure derivation of the recurring plan, so it is
# attached for ANY query time (incl. future dates), computed at each session's start.

# Tuesday 2026-09-15 (2026-09-14 is a Monday per the fixtures above).
_TUESDAY = datetime(2026, 9, 15, 12, 0, tzinfo=ZURICH)


def _planned_facility() -> Facility:
    """A synthetic facility open Tue 06:00–08:00, whose basin carries a lane plan for that
    slot: lanes 1–2 held by a club, 3–6 public."""
    rule = ScheduleRule(
        weekdays=frozenset({Weekday.TUESDAY}),
        time=TimeRange(time(6, 0), time(8, 0)),
        access=PublicSwim(),
    )
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
                access=ClubReserved(club="ASVZ"),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({3, 4, 5, 6}),
                access=PublicSwim(),
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )
    return Facility(
        identity=PoolIdentity(
            facility_id=PoolId("lane-test"),
            name="Hallenbad Lane-Test",
            kind=PoolKind.INDOOR,
        ),
        address="Bahnstrasse 1, Zürich",
        provenance=Provenance(source="test", curated=True),
        basins=(
            Basin(
                basin_id=BasinId("lane-main"),
                name="Schwimmerbecken",
                rules=(rule,),
                lane_plan=plan,
            ),
        ),
    )


def test_lane_availability_clamps_to_session_start_when_query_is_outside(
    dataset: Dataset,
) -> None:
    # _TUESDAY is 12:00 but the session is 06:00–08:00, so the queried moment is OUTSIDE it and
    # the point eval clamps to the session start (06:00) — lanes 1–2 club, 3–6 public.
    result = find_swim_options(
        SwimQuery(person=ADULT, at=_TUESDAY), (_planned_facility(),), dataset.calendar
    )
    assert result.options
    avail = result.options[0].lane_availability
    assert avail == LaneAvailability(
        lane_count=6,
        public_lanes=4,
        reserved_lanes=2,
        owners=(ClubReserved(club="ASVZ"),),
        public_until=time(8, 0),
        partial=False,
    )


def _timeline_facility() -> Facility:
    """A basin open Tue 06:00–22:00: all six lanes public until 18:00, when a club takes 2 —
    so 12:00 (6 public) and 18:00 (4 public) must report DIFFERENT counts."""
    rule = ScheduleRule(
        weekdays=frozenset({Weekday.TUESDAY}),
        time=TimeRange(time(6, 0), time(22, 0)),
        access=PublicSwim(),
    )
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(18, 0)),
                lanes=frozenset({1, 2, 3, 4, 5, 6}),
                access=PublicSwim(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(18, 0), time(22, 0)),
                lanes=frozenset({1, 2, 3, 4}),
                access=PublicSwim(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(18, 0), time(22, 0)),
                lanes=frozenset({5, 6}),
                access=ClubReserved(club="ASVZ"),
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )
    return Facility(
        identity=PoolIdentity(
            facility_id=PoolId("timeline-test"),
            name="Hallenbad Timeline-Test",
            kind=PoolKind.INDOOR,
        ),
        address="Bahnstrasse 2, Zürich",
        provenance=Provenance(source="test", curated=True),
        basins=(
            Basin(
                basin_id=BasinId("timeline-main"),
                name="Schwimmerbecken",
                rules=(rule,),
                lane_plan=plan,
            ),
        ),
    )


def test_lane_availability_clamped_to_queried_moment_not_wall_clock(dataset: Dataset) -> None:
    # THE 12:00 == 18:00 FIX. Both queries share the SAME 06:00–22:00 session; only the queried
    # time-of-day differs. The point eval must clamp to `now_time` (the queried moment), so
    # 18:00 reports fewer public lanes than 12:00 — and this holds regardless of the wall-clock
    # time the test runs, because the clamp reads `at`, never `datetime.now()`.
    facility = (_timeline_facility(),)
    at_noon = datetime(2026, 9, 15, 12, 0, tzinfo=ZURICH)  # a Tuesday
    at_evening = datetime(2026, 9, 15, 18, 0, tzinfo=ZURICH)

    noon = find_swim_options(SwimQuery(person=ADULT, at=at_noon), facility, dataset.calendar)
    evening = find_swim_options(SwimQuery(person=ADULT, at=at_evening), facility, dataset.calendar)

    noon_avail = noon.options[0].lane_availability
    evening_avail = evening.options[0].lane_availability
    assert noon_avail is not None and evening_avail is not None
    assert noon_avail.public_lanes == 6
    assert evening_avail.public_lanes == 4
    assert evening_avail.public_lanes < noon_avail.public_lanes


def test_lane_timeline_attached_across_the_whole_session(dataset: Dataset) -> None:
    # The derived timeline spans the whole session independent of the queried moment: one
    # segment per reservation boundary (06:00–18:00 = 6 public, 18:00–22:00 = 4 public).
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime(2026, 9, 15, 12, 0, tzinfo=ZURICH)),
        (_timeline_facility(),),
        dataset.calendar,
    )
    timeline = result.options[0].lane_timeline
    assert timeline is not None
    assert [(s.time.start, s.time.end) for s in timeline.segments] == [
        (time(6, 0), time(18, 0)),
        (time(18, 0), time(22, 0)),
    ]
    assert [s.availability.public_lanes for s in timeline.segments] == [6, 4]


def test_no_lane_timeline_without_a_plan(dataset: Dataset) -> None:
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime(2026, 9, 14, 12, 0, tzinfo=ZURICH)),
        dataset.facilities,
        dataset.calendar,
    )
    assert result.options
    assert all(o.lane_timeline is None for o in result.options)


def test_lane_availability_not_gated_to_now(dataset: Dataset) -> None:
    # The query moment (2026-09-15) is far from wall-clock now, yet the badge is still
    # attached — availability is a static derivation, not a "~now" signal like occupancy.
    far_future = _TUESDAY + timedelta(weeks=104)  # ~2 years ahead, still a Tuesday
    result = find_swim_options(
        SwimQuery(person=ADULT, at=far_future), (_planned_facility(),), dataset.calendar
    )
    assert result.options
    assert result.options[0].lane_availability is not None
    assert result.options[0].live_occupancy is None  # occupancy stays unrequested


def test_no_lane_availability_without_a_plan(dataset: Dataset) -> None:
    # The curated dataset carries no lane plans yet (S2 needs live URLs) → None, never invented.
    result = find_swim_options(
        SwimQuery(person=ADULT, at=datetime(2026, 9, 14, 12, 0, tzinfo=ZURICH)),
        dataset.facilities,
        dataset.calendar,
    )
    assert result.options
    assert all(o.lane_availability is None for o in result.options)


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
