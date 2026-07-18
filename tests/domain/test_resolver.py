"""The resolver date-matrix: the same weekday must resolve differently across term,
school holiday, public holiday, and maintenance closure. This is the correctness core.
"""

from __future__ import annotations

from datetime import date, time

from swimzh.domain.access import LaneSwim, PublicSwim, SeniorsOnly
from swimzh.domain.calendar import HolidayRange, ZurichCalendar
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.resolver import resolve_basin
from swimzh.domain.schedule import (
    ClosedDay,
    ClosureRange,
    DayScope,
    HolidayPolicy,
    OpenDay,
    ScheduleException,
    ScheduleRule,
    TimeRange,
    Weekday,
)

WEEKDAYS = frozenset(
    {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
)
WEEKEND = frozenset({Weekday.SATURDAY, Weekday.SUNDAY})


def _calendar(policy_year: int = 2026) -> ZurichCalendar:
    return ZurichCalendar(
        public_holidays={date(2026, 4, 3): "Karfreitag"},
        school_holidays=[HolidayRange("Sportferien", date(2026, 2, 9), date(2026, 2, 20))],
        known_years=[policy_year],
    )


def _basin() -> Basin:
    return Basin(
        basin_id=BasinId("b"),
        name="Becken",
        rules=(
            ScheduleRule(WEEKDAYS, TimeRange(time(6, 30), time(9, 0)), LaneSwim()),
            ScheduleRule(
                WEEKDAYS,
                TimeRange(time(9, 0), time(11, 0)),
                SeniorsOnly(min_age=60),
                scope=DayScope.SCHOOL_TERM,
            ),
            ScheduleRule(
                WEEKDAYS,
                TimeRange(time(9, 0), time(11, 0)),
                PublicSwim(),
                scope=DayScope.SCHOOL_HOLIDAY,
            ),
            ScheduleRule(WEEKDAYS, TimeRange(time(11, 0), time(22, 0)), PublicSwim()),
            ScheduleRule(WEEKEND, TimeRange(time(8, 0), time(20, 0)), PublicSwim()),
        ),
        exceptions=(ScheduleException(date=date(2026, 12, 24), closed=True, reason="Heiligabend"),),
    )


def _facility(policy: HolidayPolicy = HolidayPolicy.SUNDAY_SCHEDULE) -> Facility:
    return Facility(
        identity=PoolIdentity(FacilityId("f"), "Test", PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="test", curated=True),
        basins=(_basin(),),
        closures=(ClosureRange(date(2026, 7, 4), date(2026, 8, 7), "Sommerpause / Revision"),),
        public_holiday_policy=policy,
    )


def _accesses(day: OpenDay) -> list[str]:
    return [type(s.access).__name__ for s in day.sessions]


def test_normal_tuesday_in_term() -> None:
    # 2026-03-10 is a Tuesday, in school term, not a holiday.
    result = resolve_basin(_facility(), _facility().basins[0], date(2026, 3, 10), _calendar())
    assert isinstance(result, OpenDay)
    assert _accesses(result) == ["LaneSwim", "SeniorsOnly", "PublicSwim"]


def test_school_holiday_tuesday_swaps_seniors_for_public() -> None:
    # 2026-02-10 is a Tuesday inside Sportferien.
    result = resolve_basin(_facility(), _facility().basins[0], date(2026, 2, 10), _calendar())
    assert isinstance(result, OpenDay)
    # Seniors slot is gone; the 09:00–11:00 block is public instead.
    assert _accesses(result) == ["LaneSwim", "PublicSwim", "PublicSwim"]
    assert all(type(s.access).__name__ != "SeniorsOnly" for s in result.sessions)


def test_public_holiday_uses_sunday_schedule() -> None:
    # Karfreitag 2026-04-03 (a Friday) -> Sunday timetable via policy.
    result = resolve_basin(_facility(), _facility().basins[0], date(2026, 4, 3), _calendar())
    assert isinstance(result, OpenDay)
    assert len(result.sessions) == 1
    assert result.sessions[0].time == TimeRange(time(8, 0), time(20, 0))


def test_public_holiday_closed_policy() -> None:
    facility = _facility(policy=HolidayPolicy.CLOSED)
    result = resolve_basin(facility, facility.basins[0], date(2026, 4, 3), _calendar())
    assert isinstance(result, ClosedDay)
    assert "Karfreitag" in result.reason


def test_maintenance_closure_wins() -> None:
    # 2026-07-20 is inside the Revision closure.
    result = resolve_basin(_facility(), _facility().basins[0], date(2026, 7, 20), _calendar())
    assert isinstance(result, ClosedDay)
    assert "Revision" in result.reason


def test_one_off_exception_closes_day() -> None:
    result = resolve_basin(_facility(), _facility().basins[0], date(2026, 12, 24), _calendar())
    assert isinstance(result, ClosedDay)
    assert result.reason == "Heiligabend"


def test_calendar_coverage_boundary() -> None:
    cal = _calendar()
    assert cal.covers(date(2026, 3, 10)) is True
    assert cal.covers(date(2030, 3, 10)) is False
