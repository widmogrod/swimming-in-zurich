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
from swimzh.domain.closure import ClosureCode, classify_closure


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
    #: The verbatim source cell this rule was classified from (the timetable's *Angebot*
    #: column), kept so classifying never destroys what the page said — it carries the
    #: per-session depth ("Tiefe 135 cm") and any footnote the domain cannot express.
    #: Defaulted, so every pre-existing construction stays equal; persisted but not yet read
    #: by any query, API field or UI surface.
    source_text: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """A concrete swimmable (or reserved) block on a specific day."""

    time: TimeRange
    access: SessionAccess


def _derive_closure(obj: ScheduleException | ClosureRange) -> None:
    """Fill `code`/`params` from `reason` unless the caller set them.

    Frozen dataclasses need `object.__setattr__`; the alternative — classifying only at
    the DTO boundary — let a directly-constructed domain object carry `SPECIAL` for a
    reason that was perfectly classifiable.
    """
    if obj.code is not ClosureCode.SPECIAL or obj.params:
        return
    code, params = classify_closure(obj.reason)
    object.__setattr__(obj, "code", code)
    object.__setattr__(obj, "params", params)


@dataclass(frozen=True, slots=True)
class ScheduleException:
    """A one-off override for a specific date (event, gala, altered hours, or a closure).

    If `closed` is True the facility is shut that day and `sessions` is ignored. Otherwise
    `sessions` *replaces* the normally-resolved sessions for that date.
    """

    date: date
    closed: bool = False
    #: The curated German this was authored as. Kept as the SOURCE of `code` (and for the
    #: build audit); it is never rendered — the UI reads the code.
    reason: str = ""
    #: The classified reason. Derived from `reason` on construction unless given
    #: explicitly, so NO construction path can skip classification — an earlier version
    #: classified only at the DTO boundary, and a domain object built directly in a test
    #: silently carried `SPECIAL`.
    code: ClosureCode = field(default=ClosureCode.SPECIAL)
    params: Mapping[str, str] = field(default_factory=dict)
    sessions: tuple[ResolvedSession, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _derive_closure(self)


@dataclass(frozen=True, slots=True)
class ClosureRange:
    """A multi-day closure (annual maintenance "Revision", seasonal shutdown)."""

    start: date
    end: date  # inclusive
    #: See ScheduleException.reason.
    reason: str = ""
    code: ClosureCode = field(default=ClosureCode.SPECIAL)
    params: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _derive_closure(self)

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass(frozen=True, slots=True)
class OpenDay:
    """The facility/basin is open with these sessions (sorted by start time)."""

    sessions: tuple[ResolvedSession, ...]
    #: True when this is a public holiday AND no source states the facility's holiday policy,
    #: so the sessions are the ordinary weekday ones and we cannot confirm they hold today.
    #:
    #: Deliberately a flag on the OPEN day rather than a fourth `DaySchedule` member: the
    #: sessions are real and the pool may well be open, so reporting the day as closed (or as
    #: a new terminal "unknown" state) would trade one wrong answer for another. The caller
    #: surfaces it as a warning alongside the hours — see `query.find_swim_options`.
    holiday_policy_unverified: bool = False


@dataclass(frozen=True, slots=True)
class ClosedDay:
    """The facility/basin is closed on this day, as a CODE plus its parameters.

    The human-readable `reason` was retired in S5: the domain states WHY in a form every
    locale can render, and only the client turns that into words.
    """

    code: ClosureCode = ClosureCode.SPECIAL
    params: Mapping[str, str] = field(default_factory=dict)


type DaySchedule = OpenDay | ClosedDay
