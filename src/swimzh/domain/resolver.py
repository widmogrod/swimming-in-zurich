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
from swimzh.domain.closure import ClosureCode
from swimzh.domain.holiday import classify_holiday
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


def _find_exception(exceptions: tuple[ScheduleException, ...], d: date) -> ScheduleException | None:
    return next((e for e in exceptions if e.date == d), None)


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


def resolve_hours(
    facility: Facility,
    rules: tuple[ScheduleRule, ...],
    exceptions: tuple[ScheduleException, ...],
    d: date,
    calendar: ZurichCalendar,
) -> DaySchedule:
    """Resolve any facility-scoped schedule (a basin's, or a `Feature`'s hours) for a
    concrete date. Facility closures and holiday policy apply either way — the sauna is
    shut during the Revision too."""
    # 1. Facility-wide closures win over everything.
    for closure in facility.closures:
        if closure.contains(d):
            return ClosedDay(code=closure.code, params=dict(closure.params))

    # 2. A one-off exception for this exact date overrides the recurring pattern.
    exception = _find_exception(exceptions, d)
    if exception is not None:
        if exception.closed:
            # The code was settled at build time (boundary/mapping); carry it through.
            return ClosedDay(code=exception.code, params=dict(exception.params))
        return OpenDay(sessions=exception.sessions)

    ctx = calendar.context(d)

    # 3. Public-holiday policy.
    effective_weekday = Weekday(d.weekday())
    # A holiday we cannot vouch for: the pool states no policy, so we fall through to its
    # ordinary weekday rules AND say so, rather than silently presenting them as confirmed.
    unverified_holiday = ctx.is_public_holiday and facility.public_holiday_policy is None
    if ctx.is_public_holiday:
        match facility.public_holiday_policy:
            case HolidayPolicy.CLOSED:
                # The holiday NAME is data, not copy: it travels as a param so a
                # translated sentence can place it (and an untranslatable one — see
                # Berchtoldstag — can be shown verbatim without breaking the sentence).
                name = ctx.holiday_name or ""
                # Both travel: the CODE so a known holiday can be translated, and the
                # NAME so an unrecognised (or untranslatable, e.g. Berchtoldstag) one is
                # still shown truthfully rather than as a blank.
                params = (
                    {"holiday": name, "holiday_code": classify_holiday(name).value} if name else {}
                )
                return ClosedDay(code=ClosureCode.PUBLIC_HOLIDAY, params=params)
            case HolidayPolicy.SUNDAY_SCHEDULE:
                effective_weekday = Weekday.SUNDAY
            case HolidayPolicy.NORMAL:
                pass
            case None:
                # Unknown policy: use the weekday rules, flagged (see `unverified_holiday`).
                pass

    # 4. Recurring rules for the effective weekday and calendar scope.
    sessions = _sessions_for_weekday(rules, effective_weekday, ctx)
    if not sessions:
        return ClosedDay(code=ClosureCode.NO_SESSIONS)
    return OpenDay(sessions=sessions, holiday_policy_unverified=unverified_holiday)


def resolve_basin(
    facility: Facility, basin: Basin, d: date, calendar: ZurichCalendar
) -> DaySchedule:
    return resolve_hours(facility, basin.rules, basin.exceptions, d, calendar)
