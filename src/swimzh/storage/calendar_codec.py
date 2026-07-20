"""Faithful `ZurichCalendar` <-> JSON codec for the gold store.

The calendar is seeded data (public holidays + school-holiday ranges + the years those
cover). Rather than hand-roll JSON we round-trip it through the same `CalendarDTO` the
curated YAML loader validates — one source of truth for the shape, in both directions, with
`date` values round-tripping as ISO strings via pydantic. `dumps` / `loads` are exact
inverses (verified by a round-trip test).
"""

from __future__ import annotations

from swimzh.boundary.curated_dto import CalendarDTO, PublicHolidayDTO, SchoolHolidayDTO
from swimzh.domain.calendar import HolidayRange, ZurichCalendar


def to_dto(calendar: ZurichCalendar) -> CalendarDTO:
    return CalendarDTO(
        known_years=sorted(calendar.known_years),
        public_holidays=[
            PublicHolidayDTO(date=day, name=name)
            for day, name in sorted(calendar.public_holidays.items())
        ],
        school_holidays=[
            SchoolHolidayDTO(name=r.name, start=r.start, end=r.end)
            for r in calendar.school_holidays
        ],
    )


def from_dto(dto: CalendarDTO) -> ZurichCalendar:
    return ZurichCalendar(
        public_holidays={h.date: h.name for h in dto.public_holidays},
        school_holidays=[
            HolidayRange(name=r.name, start=r.start, end=r.end) for r in dto.school_holidays
        ],
        known_years=dto.known_years,
    )


def dumps(calendar: ZurichCalendar) -> str:
    return to_dto(calendar).model_dump_json()


def loads(text: str) -> ZurichCalendar:
    return from_dto(CalendarDTO.model_validate_json(text))
