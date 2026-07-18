"""Admission pricing — deliberately modest.

Prices come from HTML/PDF, go stale, and carry liability if computed wrong. So this is not
a tariff engine: each entry stores a dated display value plus an amount, and `price_for`
picks the entry for a person by simple age bands. Everything is stamped with `valid_as_of`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class PriceCategory(Enum):
    CHILD = "child"  # young children (often free / reduced)
    YOUTH = "youth"  # school-age / students
    ADULT = "adult"
    SENIOR = "senior"


# Approximate Zürich age bands; refine per facility if their tariff differs.
_YOUTH_MAX_AGE = 15
_SENIOR_MIN_AGE = 65


def category_for_age(age: int) -> PriceCategory:
    if age <= 5:
        return PriceCategory.CHILD
    if age <= _YOUTH_MAX_AGE:
        return PriceCategory.YOUTH
    if age >= _SENIOR_MIN_AGE:
        return PriceCategory.SENIOR
    return PriceCategory.ADULT


@dataclass(frozen=True, slots=True)
class PriceEntry:
    category: PriceCategory
    amount_chf: Decimal
    display: str


@dataclass(frozen=True, slots=True)
class PriceTable:
    entries: tuple[PriceEntry, ...]
    valid_as_of: date | None = None
    source_url: str | None = None

    def by_category(self, category: PriceCategory) -> PriceEntry | None:
        return next((e for e in self.entries if e.category == category), None)


def price_for(table: PriceTable, age: int | None) -> PriceEntry | None:
    """Pick the price entry for a person's age; adult when age is unknown."""
    category = category_for_age(age) if age is not None else PriceCategory.ADULT
    entry = table.by_category(category)
    # Fall back to the adult tariff if the specific band is not published.
    return entry if entry is not None else table.by_category(PriceCategory.ADULT)
