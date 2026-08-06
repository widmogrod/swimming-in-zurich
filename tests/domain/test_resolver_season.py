"""Layer-4 season filtering: a seasoned rule runs only inside its window, and a facility
whose whole timetable is out of season closes as a SEASONAL BREAK — never as "no sessions
scheduled", which is a lie for a lido in October.
"""

from __future__ import annotations

from datetime import date, time

from swimzh.domain.access import PublicSwim
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.closure import ClosureCode
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.resolver import resolve_basin
from swimzh.domain.schedule import (
    AnnualWindow,
    ClosedDay,
    OpenDay,
    ScheduleRule,
    TimeRange,
    Weather,
    Weekday,
)

ALL_DAYS = frozenset(Weekday)
SUMMER = AnnualWindow.whole_months(5, 9)
WINTER = AnnualWindow.whole_months(10, 4)


def _calendar() -> ZurichCalendar:
    return ZurichCalendar(public_holidays={}, school_holidays=[], known_years=[2026, 2027])


def _facility(*rules: ScheduleRule) -> Facility:
    return Facility(
        identity=PoolIdentity(PoolId("f"), "Test", PoolKind.OUTDOOR),
        address="",
        provenance=Provenance(source="test", curated=False),
        basins=(Basin(basin_id=BasinId("b"), name="Becken", rules=rules),),
    )


def _resolve(facility: Facility, d: date) -> OpenDay | ClosedDay:
    return resolve_basin(facility, facility.basins[0], d, _calendar())


def test_only_the_in_season_rule_resolves() -> None:
    # The two windows Bläsi publishes for its weekend, on one basin.
    facility = _facility(
        ScheduleRule(ALL_DAYS, TimeRange(time(9), time(16)), PublicSwim(), season=SUMMER),
        ScheduleRule(ALL_DAYS, TimeRange(time(9), time(18)), PublicSwim(), season=WINTER),
    )

    july = _resolve(facility, date(2026, 7, 18))
    assert isinstance(july, OpenDay)
    assert [s.time for s in july.sessions] == [TimeRange(time(9), time(16))]

    january = _resolve(facility, date(2026, 1, 17))
    assert isinstance(january, OpenDay)
    assert [s.time for s in january.sessions] == [TimeRange(time(9), time(18))]


def test_an_unseasoned_rule_runs_all_year() -> None:
    facility = _facility(ScheduleRule(ALL_DAYS, TimeRange(time(9), time(16)), PublicSwim()))
    for d in (date(2026, 1, 17), date(2026, 7, 18), date(2026, 10, 1)):
        assert isinstance(_resolve(facility, d), OpenDay), d


def test_all_rules_out_of_season_is_a_seasonal_break_not_no_sessions() -> None:
    # A lido: it publishes summer hours only. On 1 October it is not "unscheduled", it is shut
    # for the season — and `NO_SESSIONS` renders as "No sessions scheduled", which is a lie.
    lido = _facility(
        ScheduleRule(ALL_DAYS, TimeRange(time(9), time(20)), PublicSwim(), season=SUMMER)
    )

    result = _resolve(lido, date(2026, 10, 1))
    assert isinstance(result, ClosedDay)
    assert result.code is ClosureCode.SEASONAL_BREAK


def test_a_closed_weekday_inside_the_season_is_still_no_sessions() -> None:
    # Open all summer, but never on Mondays: 2026-07-20 is a Monday INSIDE the season, so the
    # pool is not on a seasonal break — it is simply shut that day.
    facility = _facility(
        ScheduleRule(
            frozenset({Weekday.SATURDAY, Weekday.SUNDAY}),
            TimeRange(time(9), time(20)),
            PublicSwim(),
            season=SUMMER,
        )
    )

    result = _resolve(facility, date(2026, 7, 20))
    assert isinstance(result, ClosedDay)
    assert result.code is ClosureCode.NO_SESSIONS


def test_a_mixed_timetable_never_reports_a_seasonal_break() -> None:
    # One unseasoned rule (on another weekday) means the facility is NOT seasonal, so an empty
    # day is an ordinary empty day.
    facility = _facility(
        ScheduleRule(
            frozenset({Weekday.SATURDAY}), TimeRange(time(9), time(16)), PublicSwim(), season=SUMMER
        ),
        ScheduleRule(frozenset({Weekday.MONDAY}), TimeRange(time(9), time(16)), PublicSwim()),
    )

    result = _resolve(facility, date(2026, 10, 6))  # a Tuesday
    assert isinstance(result, ClosedDay)
    assert result.code is ClosureCode.NO_SESSIONS


def test_a_rule_less_basin_is_still_no_sessions() -> None:
    assert _resolve(_facility(), date(2026, 7, 18)) == ClosedDay(code=ClosureCode.NO_SESSIONS)


def test_weather_rides_from_the_rule_onto_the_resolved_session() -> None:
    facility = _facility(
        ScheduleRule(ALL_DAYS, TimeRange(time(9), time(14)), PublicSwim()),
        ScheduleRule(
            ALL_DAYS, TimeRange(time(14), time(21)), PublicSwim(), weather=Weather.FAIR_ONLY
        ),
    )

    result = _resolve(facility, date(2026, 7, 18))
    assert isinstance(result, OpenDay)
    # Per-SESSION, never per-day: the morning is certain, the afternoon conditional.
    assert [s.weather for s in result.sessions] == [Weather.ANY, Weather.FAIR_ONLY]
