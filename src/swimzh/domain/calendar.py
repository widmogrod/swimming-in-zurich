"""Zürich calendar overlays: school-holiday and public-holiday context for a date.

This is what lets the resolver answer *future* dates correctly: the same weekday resolves
to different sessions depending on whether school is in session, and public holidays alter
or close the timetable. The underlying dates are seeded data (`data/calendar/zurich.yaml`)
and change roughly yearly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class DayContext:
    date: date
    is_public_holiday: bool
    holiday_name: str | None
    is_school_holiday: bool
    school_holiday_name: str | None


@dataclass(frozen=True, slots=True)
class HolidayRange:
    name: str
    start: date
    end: date  # inclusive

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


class ZurichCalendar:
    """Answers school/public-holiday questions for a date.

    Constructed from explicit data so it is deterministic and testable; coverage is bounded
    by the seeded years and `covers()` reports that boundary honestly rather than silently
    returning "not a holiday" for dates outside the known range.
    """

    def __init__(
        self,
        *,
        public_holidays: Mapping[date, str],
        school_holidays: Iterable[HolidayRange],
        known_years: Iterable[int],
    ) -> None:
        self._public = dict(public_holidays)
        self._school = tuple(school_holidays)
        self._known_years = frozenset(known_years)

    @property
    def public_holidays(self) -> Mapping[date, str]:
        """Public holidays keyed by date, as a read-only view (frozen contract preserved)."""
        return MappingProxyType(self._public)

    @property
    def school_holidays(self) -> tuple[HolidayRange, ...]:
        """The seeded school-holiday ranges (already immutable)."""
        return self._school

    @property
    def known_years(self) -> frozenset[int]:
        """The years this calendar has data for (already immutable)."""
        return self._known_years

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ZurichCalendar):
            return NotImplemented
        return (
            self._public == other._public
            and self._school == other._school
            and self._known_years == other._known_years
        )

    # Defining __eq__ on this plain class makes Python set __hash__ = None (unhashable). That
    # is intentional and safe: nothing uses a ZurichCalendar as a dict key or set member, and
    # one field is a mutable-origin Mapping, so value-based hashing would be unsound anyway.

    def covers(self, d: date) -> bool:
        """Whether calendar data is present for this date's year."""
        return d.year in self._known_years

    def context(self, d: date) -> DayContext:
        holiday_name = self._public.get(d)
        school = next((r for r in self._school if r.contains(d)), None)
        return DayContext(
            date=d,
            is_public_holiday=holiday_name is not None,
            holiday_name=holiday_name,
            is_school_holiday=school is not None,
            school_holiday_name=school.name if school is not None else None,
        )
