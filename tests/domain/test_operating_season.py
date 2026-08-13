"""The facility-level SEASON GATE (sharedsource-fanout S1): a rule-less facility whose page
states an operating season resolves to the honest third state — `OpenUnscheduledDay` inside
the window, `ClosedDay(OUT_OF_SEASON)` outside it — and `/swim` reports it exactly once,
never also as a `no_source` ghost. A facility WITHOUT an `operating_season` resolves exactly
as before the gate existed (regression-pinned on the illustrative fixtures).
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from swimzh.domain.access import PublicSwim
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry, RosterEntry, ScheduleFreshness
from swimzh.domain.closure import ClosureCode
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    OperatingSeason,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.person import Person
from swimzh.domain.query import FacilityStatus, StatusCode, SwimQuery, find_swim_options
from swimzh.domain.resolver import resolve_basin, resolve_hours
from swimzh.domain.schedule import (
    AnnualWindow,
    ClosedDay,
    ClosureRange,
    MonthDay,
    OpenDay,
    OpenUnscheduledDay,
    ScheduleException,
    ScheduleRule,
    TimeRange,
    Weather,
    Weekday,
)
from swimzh.providers.curated import Dataset

ZURICH = ZoneInfo("Europe/Zurich")
MAI_SEP = AnnualWindow.whole_months(5, 9)
SEASON = OperatingSeason(window=MAI_SEP, weather=Weather.FAIR_ONLY)
# The S1 acceptance dates: mid-July (inside Mai–September) and mid-January (outside).
JULY_15 = date(2026, 7, 15)
JANUARY_15 = date(2026, 1, 15)
JULY_AFTERNOON = datetime(2026, 7, 15, 14, 0, tzinfo=ZURICH)
JANUARY_AFTERNOON = datetime(2026, 1, 15, 14, 0, tzinfo=ZURICH)


def _calendar() -> ZurichCalendar:
    return ZurichCalendar(public_holidays={}, school_holidays=[], known_years=[2026])


def _paddling_pool(
    *,
    season: OperatingSeason | None,
    rules: tuple[ScheduleRule, ...] = (),
    closures: tuple[ClosureRange, ...] = (),
) -> Facility:
    return Facility(
        identity=PoolIdentity(
            PoolId("planschbecken-josefwiese"), "Planschbecken Josefwiese", PoolKind.PADDLING
        ),
        address="",
        provenance=Provenance(source="test", curated=False),
        basins=(Basin(basin_id=BasinId("pj-b"), name="Becken", rules=rules),),
        closures=closures,
        operating_season=season,
    )


# --- the resolver's season gate ---------------------------------------------------------


def test_a_zero_rule_facility_is_open_unscheduled_inside_its_season() -> None:
    facility = _paddling_pool(season=SEASON)
    result = resolve_hours(facility, (), (), JULY_15, _calendar())
    assert result == OpenUnscheduledDay(weather=Weather.FAIR_ONLY)


def test_a_zero_rule_facility_is_out_of_season_outside_its_window() -> None:
    facility = _paddling_pool(season=SEASON)
    result = resolve_hours(facility, (), (), JANUARY_15, _calendar())
    assert result == ClosedDay(code=ClosureCode.OUT_OF_SEASON)


def test_the_season_weather_rides_through_never_defaulted() -> None:
    # `OpenUnscheduledDay.weather` is REQUIRED: the only legitimate producer is the gate
    # passing `operating_season.weather`, so an all-weather season states ANY explicitly.
    all_weather = OperatingSeason(window=MAI_SEP, weather=Weather.ANY)
    result = resolve_hours(_paddling_pool(season=all_weather), (), (), JULY_15, _calendar())
    assert result == OpenUnscheduledDay(weather=Weather.ANY)


def test_a_facility_closure_beats_the_season_gate() -> None:
    # Priority order: closures win over everything, including an in-season gate.
    closure = ClosureRange(start=date(2026, 7, 1), end=date(2026, 7, 31), reason="Revision")
    facility = _paddling_pool(season=SEASON, closures=(closure,))
    result = resolve_hours(facility, (), (), JULY_15, _calendar())
    assert isinstance(result, ClosedDay)
    assert result.code is ClosureCode.MAINTENANCE


def test_an_exception_beats_the_season_gate() -> None:
    # Order is closures -> exceptions -> gate: a one-off dated statement outranks the
    # season sentence even outside the window.
    exception = ScheduleException(date=JANUARY_15, closed=True, reason="Event")
    result = resolve_hours(_paddling_pool(season=SEASON), (), (exception,), JANUARY_15, _calendar())
    assert isinstance(result, ClosedDay)
    assert result.code is not ClosureCode.OUT_OF_SEASON


def test_a_rule_carrying_schedule_inside_the_window_resolves_unchanged() -> None:
    # Inside the window with rules, the gate is a pass-through: the resolution is identical
    # to the same facility without any `operating_season`.
    rule = ScheduleRule(frozenset(Weekday), TimeRange(time(9), time(18)), PublicSwim())
    with_season = _paddling_pool(season=SEASON, rules=(rule,))
    without_season = _paddling_pool(season=None, rules=(rule,))
    seasoned = resolve_basin(with_season, with_season.basins[0], JULY_15, _calendar())
    plain = resolve_basin(without_season, without_season.basins[0], JULY_15, _calendar())
    assert seasoned == plain
    assert isinstance(seasoned, OpenDay)


def test_a_facility_without_a_season_and_without_rules_resolves_as_today() -> None:
    facility = _paddling_pool(season=None)
    for d in (JULY_15, JANUARY_15):
        assert resolve_hours(facility, (), (), d, _calendar()) == ClosedDay(
            code=ClosureCode.NO_SESSIONS
        )


def test_the_illustrative_fixtures_resolve_exactly_as_today(dataset: Dataset) -> None:
    """Regression pin: no illustrative facility carries an `operating_season`, and none —
    across the year's dates — ever resolves to the new variant. The gate is inert for
    every pool that predates it."""
    days = [date(2026, 1, 1), date(2026, 4, 15), JULY_15, date(2026, 10, 1), date(2026, 12, 24)]
    assert dataset.facilities, "the illustrative dataset must not be empty"
    for facility in dataset.facilities:
        assert facility.operating_season is None
        for basin in facility.basins:
            for d in days:
                result = resolve_basin(facility, basin, d, _calendar())
                assert not isinstance(result, OpenUnscheduledDay), (
                    facility.identity.facility_id,
                    basin.basin_id,
                    d,
                )


# --- the /swim query surface ------------------------------------------------------------


def _roster_row(facility: Facility) -> RosterEntry:
    return RosterEntry(
        entry=PoolCatalogEntry(
            pool_id=str(facility.identity.facility_id),
            name=facility.identity.name,
            kind=facility.identity.kind,
            address="",
            geo=None,
            url=None,
            description=None,
            phone=None,
        ),
        # A Planschbecken has no timetable source at all: its SCHEDULE freshness stays the
        # honest `no_source` even while the season rides as a separate fact.
        freshness=ScheduleFreshness.NO_SOURCE,
    )


def _statuses_for(facility: Facility, at: datetime) -> tuple[FacilityStatus, ...]:
    result = find_swim_options(
        SwimQuery(person=Person(gender=None, age=None), at=at),
        (facility,),
        _calendar(),
        roster=(_roster_row(facility),),
    )
    assert result.options == ()
    return result.statuses


def test_in_season_the_facility_is_open_unscheduled_exactly_once() -> None:
    facility = _paddling_pool(season=SEASON)
    statuses = _statuses_for(facility, JULY_AFTERNOON)
    assert len(statuses) == 1, "exactly once — never also a no_source ghost"
    status = statuses[0]
    assert status.status == "open_unscheduled"
    assert status.code is StatusCode.OPEN_UNSCHEDULED
    assert status.closure is None
    assert status.params == {
        "weather": "fair_only",
        "season_start_month": "5",
        "season_end_month": "9",
        "season_precision": "month",
    }


def test_out_of_season_the_facility_is_closed_exactly_once() -> None:
    facility = _paddling_pool(season=SEASON)
    statuses = _statuses_for(facility, JANUARY_AFTERNOON)
    assert len(statuses) == 1
    status = statuses[0]
    # The SAME pair a seasonal scraped pool already serves — no new closed shape.
    assert status.status == "closed"
    assert status.code is StatusCode.CLOSED_REASON
    assert status.closure is ClosureCode.OUT_OF_SEASON


def test_without_a_season_the_same_facility_stays_a_no_source_ghost() -> None:
    # The exclusivity control: remove the season and the pre-slice answer returns.
    facility = _paddling_pool(season=None)
    statuses = _statuses_for(facility, JULY_AFTERNOON)
    assert len(statuses) == 1
    assert statuses[0].status == "no_source"
    assert statuses[0].code is StatusCode.NO_SOURCE


def test_a_day_precise_season_carries_its_days_in_the_params() -> None:
    season = OperatingSeason(
        window=AnnualWindow(start=MonthDay(5, 30), end=MonthDay(8, 16)),
        weather=Weather.ANY,
    )
    statuses = _statuses_for(_paddling_pool(season=season), JULY_AFTERNOON)
    params = statuses[0].params
    assert params["season_precision"] == "day"
    assert params["season_start_day"] == "30"
    assert params["season_end_day"] == "16"


def test_month_precision_params_never_claim_a_day() -> None:
    # [[annual-window]] rendering rule: a MONTH-precision window is whole months, never
    # rendered day-precise — so the params must not smuggle a fabricated day out.
    statuses = _statuses_for(_paddling_pool(season=SEASON), JULY_AFTERNOON)
    params = statuses[0].params
    assert "season_start_day" not in params
    assert "season_end_day" not in params


def test_a_facility_closure_reports_closed_not_open_unscheduled() -> None:
    closure = ClosureRange(start=date(2026, 7, 1), end=date(2026, 7, 31), reason="Revision")
    facility = _paddling_pool(season=SEASON, closures=(closure,))
    statuses = _statuses_for(facility, JULY_AFTERNOON)
    assert len(statuses) == 1
    assert statuses[0].status == "closed"
    assert statuses[0].closure is ClosureCode.MAINTENANCE
