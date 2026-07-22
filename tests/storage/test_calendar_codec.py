"""The calendar codec round-trips a ZurichCalendar exactly (dates as ISO strings)."""

from __future__ import annotations

from datetime import date

from swimzh.domain.calendar import HolidayRange, ZurichCalendar
from swimzh.storage import calendar_codec


def _sample() -> ZurichCalendar:
    return ZurichCalendar(
        public_holidays={
            date(2026, 1, 1): "Neujahr",
            date(2026, 8, 1): "Bundesfeier",
        },
        school_holidays=(
            HolidayRange(name="Sportferien", start=date(2026, 2, 9), end=date(2026, 2, 20)),
            HolidayRange(name="Sommerferien", start=date(2026, 7, 13), end=date(2026, 8, 14)),
        ),
        known_years=(2026,),
    )


def test_roundtrip_preserves_all_state() -> None:
    original = _sample()
    restored = calendar_codec.loads(calendar_codec.dumps(original))

    assert restored == original
    assert restored.public_holidays == original.public_holidays
    assert restored.school_holidays == original.school_holidays
    assert restored.known_years == original.known_years


def test_equality_is_value_based_and_typed() -> None:
    assert _sample() == _sample()
    assert _sample() != "not a calendar"


def test_roundtrip_preserves_holiday_context() -> None:
    restored = calendar_codec.loads(calendar_codec.dumps(_sample()))

    ctx = restored.context(date(2026, 1, 1))
    assert ctx.is_public_holiday and ctx.holiday_name == "Neujahr"

    ferien = restored.context(date(2026, 2, 10))
    assert ferien.is_school_holiday and ferien.school_holiday_name == "Sportferien"

    assert restored.covers(date(2026, 6, 1))
    assert not restored.covers(date(2027, 1, 1))
