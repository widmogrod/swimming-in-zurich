"""Admission pricing — the tariff states its own age bounds; this module invents none.

Prices come from HTML, go stale, and carry liability if computed wrong. So this is not a
tariff engine: each entry stores a dated display value, an amount, and the **published**
lower age bound it was printed under (`Erwachsene (ab 20 J.)` -> `min_age=20`).
`price_for` picks the entry whose bound the person clears; it never guesses.

`min_age=None` means the source stated no bound, so the entry is not age-resolvable at all —
`entry_for` skips it rather than treating it as universal. An age below every published bound
(Zürich prints nothing for under-6) yields `None`: unknown is not the adult rate.
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


@dataclass(frozen=True, slots=True)
class PriceEntry:
    category: PriceCategory
    amount_chf: Decimal
    display: str
    min_age: int | None = None
    """The lower bound the tariff itself prints for this entry; `None` if it prints none."""


@dataclass(frozen=True, slots=True)
class PriceTable:
    entries: tuple[PriceEntry, ...]
    valid_as_of: date | None = None
    source_url: str | None = None

    def entry_for(self, age: int | None) -> PriceEntry | None:
        """The entry with the greatest published `min_age` this age clears.

        An unknown age takes the entry with the greatest bound — the unreduced rate, the one
        answer that can never undercharge. No age clears a bound it is below, so a table whose
        lowest band starts at 6 returns `None` for a 3-year-old.
        """
        bounded = [(e.min_age, e) for e in self.entries if e.min_age is not None]
        if age is not None:
            bounded = [(bound, e) for bound, e in bounded if bound <= age]
        if not bounded:
            return None
        return max(bounded, key=lambda pair: pair[0])[1]


def price_for(table: PriceTable, age: int | None) -> PriceEntry | None:
    return table.entry_for(age)
