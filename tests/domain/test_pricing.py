"""Age -> tariff resolution. Every bound here is one the city publishes; none is ours."""

from __future__ import annotations

from decimal import Decimal

import pytest

from swimzh.domain import pricing
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable, price_for

# Exactly what `preise_abos.html` prints: Erwachsene ab 20, Jugendliche ab 16, Kinder ab 6.
ZURICH = PriceTable(
    entries=(
        PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Erwachsene (ab 20 J.) Fr. 8.00", 20),
        PriceEntry(PriceCategory.YOUTH, Decimal("6.00"), "Jugendliche (ab 16 J.) Fr. 6.00", 16),
        PriceEntry(PriceCategory.CHILD, Decimal("4.00"), "Kinder (ab 6 J.) Fr. 4.00", 6),
    )
)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (6, Decimal("4.00")),
        (15, Decimal("4.00")),  # the old code charged 6.00 here — a real overcharge
        (16, Decimal("6.00")),
        (19, Decimal("6.00")),  # the old code charged 8.00 here
        (20, Decimal("8.00")),
        (70, Decimal("8.00")),  # the old code invented a senior discount at 65
        (None, Decimal("8.00")),  # unknown age -> the unreduced rate, never a reduction
    ],
)
def test_every_age_lands_on_the_band_the_city_publishes(age: int | None, expected: Decimal) -> None:
    entry = ZURICH.entry_for(age)
    assert entry is not None
    assert entry.amount_chf == expected


def test_below_every_published_bound_is_unknown_not_adult() -> None:
    """Zürich prints no under-6 price. The old fallback charged a 3-year-old the adult 8.00."""
    assert ZURICH.entry_for(5) is None
    assert ZURICH.entry_for(3) is None
    assert price_for(ZURICH, 0) is None


def test_an_entry_with_no_published_bound_is_not_age_resolvable() -> None:
    """`min_age=None` means the source stated nothing — not that the entry covers everyone."""
    unbounded = PriceTable(entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Adult"),))
    assert unbounded.entry_for(30) is None
    assert unbounded.entry_for(None) is None


def test_no_hardcoded_band_survives_in_the_domain() -> None:
    assert not hasattr(pricing, "category_for_age")
    assert not hasattr(pricing, "_YOUTH_MAX_AGE")
    assert not hasattr(pricing, "_SENIOR_MIN_AGE")
    assert not hasattr(PriceCategory, "SENIOR")
    assert set(PriceCategory) == {PriceCategory.CHILD, PriceCategory.YOUTH, PriceCategory.ADULT}
