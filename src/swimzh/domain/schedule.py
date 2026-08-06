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


class DatePrecision(Enum):
    """How precisely an `AnnualWindow`'s bounds were published."""

    #: Both bounds name a day ("30. Mai–16. August").
    DAY = "day"
    #: Both bounds name only a month ("Mai–September") — read as WHOLE months, inclusive.
    MONTH = "month"


#: Days per month, used only to reject an impossible `MonthDay`. February takes 29 because a
#: year-free date must stay constructible in a leap year.
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@dataclass(frozen=True, slots=True)
class MonthDay:
    """A year-free calendar position: month plus day-of-month."""

    month: int
    day: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"MonthDay month {self.month} out of range")
        if not 1 <= self.day <= _DAYS_IN_MONTH[self.month - 1]:
            raise ValueError(f"MonthDay day {self.day} out of range for month {self.month}")


@dataclass(frozen=True, slots=True)
class AnnualWindow:
    """A recurring part of the year, inclusive at both ends and free of any year.

    **Year-free by construction.** The city states the year once per page, in a heading whose
    DOM position varies — never in the cell that carries the range. A year-bound window would
    expire silently at the turn of the year; this one resolves correctly every season, with
    the scraped year kept as provenance rather than as a bound.

    `start > end` **wraps New Year** (`Oktober–April` is Oct, Nov, Dec, Jan, Feb, Mar, Apr).

    `precision` is not cosmetic. `MONTH` means *whole months inclusive* — `Mai–September` is
    1 May through 30 September — so the day components are ignored entirely and a caller can
    never accidentally read a published month range as a 1st-to-1st window.
    """

    start: MonthDay
    end: MonthDay
    precision: DatePrecision = DatePrecision.DAY

    @classmethod
    def whole_months(cls, start_month: int, end_month: int) -> AnnualWindow:
        """`Mai–September` — the published form that names months and no days.

        The bounds are filled with the natural first/last day so a consumer that ignored
        `precision` would still be right at the edges rather than a month short.
        """
        return cls(
            start=MonthDay(month=start_month, day=1),
            end=MonthDay(month=end_month, day=_DAYS_IN_MONTH[end_month - 1]),
            precision=DatePrecision.MONTH,
        )

    def contains(self, d: date) -> bool:
        match self.precision:
            case DatePrecision.MONTH:
                return _within(d.month, self.start.month, self.end.month)
            case DatePrecision.DAY:
                return _within(
                    (d.month, d.day),
                    (self.start.month, self.start.day),
                    (self.end.month, self.end.day),
                )


def _within[T: (int, tuple[int, int])](key: T, start: T, end: T) -> bool:
    """Inclusive membership on a cyclic (year-free) axis: `start > end` wraps New Year."""
    if start <= end:
        return start <= key <= end
    return key >= start or key <= end


class Weather(Enum):
    """Whether a session is published unconditionally or only for fair weather.

    Kept per-SESSION, never per-day: the fair-weather block is additive (an all-weather block
    ends exactly where the fair-weather one starts), so a day is *certainly* open for one span
    and *conditionally* open for the next. Folding that into a day-level "maybe" would launder
    a known fact into an unknown.
    """

    ANY = "any"
    FAIR_ONLY = "fair_only"


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
    #: The part of the year this rule applies to. `None` (the default) == all year round, which
    #: is what every rule published in a plain weekly table means.
    season: AnnualWindow | None = None
    #: Whether the block is published unconditionally or only for fair weather.
    weather: Weather = Weather.ANY


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """A concrete swimmable (or reserved) block on a specific day."""

    time: TimeRange
    access: SessionAccess
    #: Carried from the rule: a `FAIR_ONLY` session is real but conditional. The season is NOT
    #: carried — by the time a session is resolved the date is known and the season has already
    #: decided whether it exists at all.
    weather: Weather = Weather.ANY


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
