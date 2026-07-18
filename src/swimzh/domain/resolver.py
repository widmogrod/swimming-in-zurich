"""The schedule resolver — the correctness core of the app.

`resolve_basin(facility, basin, d, calendar)` answers: *on this concrete date, what are this
basin's sessions?* It composes, in priority order:

  1. facility closures (maintenance "Revision" / seasonal)  -> ClosedDay
  2. a one-off ScheduleException for the date                -> its override (closed or sessions)
  3. public-holiday policy (closed / Sunday schedule / normal)
  4. recurring rules filtered by weekday and school-calendar scope

This is what makes future-date answers correct: the same weekday yields different sessions
in term vs holiday, and holidays alter or close the day.
"""

from __future__ import annotations

from datetime import date

from swimzh.domain.calendar import DayContext, ZurichCalendar
from swimzh.domain.models import Basin, Facility
from swimzh.domain.schedule import (
    ClosedDay,
    DaySchedule,
    DayScope,
    HolidayPolicy,
    OpenDay,
    ResolvedSession,
    ScheduleException,
    ScheduleRule,
    Weekday,
)


def _find_exception(basin: Basin, d: date) -> ScheduleException | None:
    return next((e for e in basin.exceptions if e.date == d), None)


def _scope_applies(scope: DayScope, ctx: DayContext) -> bool:
    match scope:
        case DayScope.ALWAYS:
            return True
        case DayScope.SCHOOL_TERM:
            return not ctx.is_school_holiday
        case DayScope.SCHOOL_HOLIDAY:
            return ctx.is_school_holiday


def _sessions_for_weekday(
    rules: tuple[ScheduleRule, ...], weekday: Weekday, ctx: DayContext
) -> tuple[ResolvedSession, ...]:
    matched = [
        ResolvedSession(time=rule.time, access=rule.access)
        for rule in rules
        if weekday in rule.weekdays and _scope_applies(rule.scope, ctx)
    ]
    matched.sort(key=lambda s: s.time.start)
    return tuple(matched)


def resolve_basin(
    facility: Facility, basin: Basin, d: date, calendar: ZurichCalendar
) -> DaySchedule:
    # 1. Facility-wide closures win over everything.
    for closure in facility.closures:
        if closure.contains(d):
            reason = closure.reason or "closed (maintenance)"
            return ClosedDay(reason=reason)

    # 2. A one-off exception for this exact date overrides the recurring pattern.
    exception = _find_exception(basin, d)
    if exception is not None:
        if exception.closed:
            return ClosedDay(reason=exception.reason or "closed (special)")
        return OpenDay(sessions=exception.sessions)

    ctx = calendar.context(d)

    # 3. Public-holiday policy.
    effective_weekday = Weekday(d.weekday())
    if ctx.is_public_holiday:
        match facility.public_holiday_policy:
            case HolidayPolicy.CLOSED:
                name = ctx.holiday_name or "public holiday"
                return ClosedDay(reason=f"closed ({name})")
            case HolidayPolicy.SUNDAY_SCHEDULE:
                effective_weekday = Weekday.SUNDAY
            case HolidayPolicy.NORMAL:
                pass

    # 4. Recurring rules for the effective weekday and calendar scope.
    sessions = _sessions_for_weekday(basin.rules, effective_weekday, ctx)
    if not sessions:
        return ClosedDay(reason="no sessions scheduled")
    return OpenDay(sessions=sessions)
