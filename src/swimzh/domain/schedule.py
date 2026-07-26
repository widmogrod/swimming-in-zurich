"""Schedule primitives: recurring rules, one-off exceptions, closures, and the resolved
result for a single day.

A pool's timetable is a *recurring* pattern (weekday → sessions) modulated by calendar
context (school term vs holiday), overlaid with one-off exceptions and multi-day closures.
These types describe that; `resolver.resolve` composes them for a concrete date.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum, IntEnum

from swimzh.domain.access import SessionAccess
from swimzh.domain.closure import ClosureCode


class Weekday(IntEnum):
    """Matches `datetime.date.weekday()` (Monday == 0)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True, slots=True)
class TimeRange:
    """A local-time interval within a single day (`Europe/Zurich`).

    `start` must be strictly before `end`. Sessions crossing midnight are not represented
    (Zürich pools close well before midnight); such a case would be split into two ranges.
    """

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"TimeRange start {self.start} must be before end {self.end}")

    def contains(self, t: time) -> bool:
        return self.start <= t < self.end


class DayScope(Enum):
    """When a recurring rule applies, relative to the school calendar."""

    ALWAYS = "always"
    SCHOOL_TERM = "school_term"  # only when school is in session (not a school holiday)
    SCHOOL_HOLIDAY = "school_holiday"  # only during school holidays (Ferien)


class HolidayPolicy(Enum):
    """How a facility behaves on a public holiday."""

    NORMAL = "normal"  # treat as its actual weekday
    SUNDAY_SCHEDULE = "sunday_schedule"  # run the Sunday timetable
    CLOSED = "closed"  # shut for the day


@dataclass(frozen=True, slots=True)
class ScheduleRule:
    """A recurring block: on these weekdays, during this time, with this access rule,
    subject to the given calendar `scope`."""

    weekdays: frozenset[Weekday]
    time: TimeRange
    access: SessionAccess
    scope: DayScope = DayScope.ALWAYS


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """A concrete swimmable (or reserved) block on a specific day."""

    time: TimeRange
    access: SessionAccess


@dataclass(frozen=True, slots=True)
class ScheduleException:
    """A one-off override for a specific date (event, gala, altered hours, or a closure).

    If `closed` is True the facility is shut that day and `sessions` is ignored. Otherwise
    `sessions` *replaces* the normally-resolved sessions for that date.
    """

    date: date
    closed: bool = False
    reason: str = ""
    #: The classified reason (S4). `reason` is the curated German it was derived from;
    #: it stays until S5 so nothing breaks mid-migration.
    code: ClosureCode = ClosureCode.SPECIAL
    params: Mapping[str, str] = field(default_factory=dict)
    sessions: tuple[ResolvedSession, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ClosureRange:
    """A multi-day closure (annual maintenance "Revision", seasonal shutdown)."""

    start: date
    end: date  # inclusive
    reason: str = ""
    #: The classified reason (S4) — see ScheduleException.code.
    code: ClosureCode = ClosureCode.SPECIAL
    params: Mapping[str, str] = field(default_factory=dict)

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass(frozen=True, slots=True)
class OpenDay:
    """The facility/basin is open with these sessions (sorted by start time)."""

    sessions: tuple[ResolvedSession, ...]


@dataclass(frozen=True, slots=True)
class ClosedDay:
    """The facility/basin is closed on this day, with a human-readable reason."""

    reason: str
    #: The machine identity of that reason + its interpolation values. `reason` is the
    #: English/German rendering of exactly this; it is retired in S5.
    code: ClosureCode = ClosureCode.SPECIAL
    params: Mapping[str, str] = field(default_factory=dict)


type DaySchedule = OpenDay | ClosedDay
