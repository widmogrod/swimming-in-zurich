"""Locker offerings at a facility (Garderobenkasten / Wertsachenfach / Wäschefach).

Cost is modelled as ORTHOGONAL optionals — `fee_chf`, `deposit_chf`, `period` — not a
tagged union, because real pool-page rows combine them freely: "gratis, plus Depot
Fr. 5.–" is free usage plus a refundable deposit; "Wäschefach (1 Jahr) Fr. 400.–" is a
fee plus a rental period; a towel row carries both a fee and a deposit. A single-tag
union cannot hold these independent axes (see docs/entities/locker-option.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class LockerCategory(Enum):
    WARDROBE = "wardrobe"  # Garderobenkasten
    VALUABLES = "valuables"  # Wertsachenfach
    LAUNDRY = "laundry"  # Wäschefach


class LockerMechanism(Enum):
    COIN = "coin"
    KEY = "key"
    CHIP = "chip"  # Wertmarke / token chip (named CHIP: ruff S105 false-positives on TOKEN)
    WRISTBAND = "wristband"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LockerOption:
    """One locker offering — static, sourced from pool-page rows.

    `fee_chf` is the usage cost (`None` = free to use); `deposit_chf` a refundable
    Pfand; `period` free text ("1 Jahr", "Saison") deliberately not parsed. `mechanism`
    is usually unstated → `None`. `raw` keeps the exact source row for audit/reparse.
    """

    category: LockerCategory
    fee_chf: Decimal | None = None
    deposit_chf: Decimal | None = None
    period: str | None = None
    mechanism: LockerMechanism | None = None
    raw: str = ""
