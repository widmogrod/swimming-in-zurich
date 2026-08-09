"""Rental offerings at a facility — the non-locker half of the pool pages' ``Mietobjekt`` table.

The same page rows that state the lockers (see `swimzh.domain.lockers`) also state rentals:
towels, swimwear, goggles, changing cabins, sun loungers, parasols, and one-off oddities
(a Lounge, a Pavillon, a sports hall). Kinds earn membership by corpus frequency across the
declared sources' committed pages (Kabine ×19, Liegestuhl ×9, Sonnenschirm ×8); everything
else routes to ``OTHER`` with the source row preserved in ``raw`` — the UNMAPPED idiom, so
no published row is ever dropped.

Cost is the same ORTHOGONAL-optionals model as `LockerOption` — ``fee_chf``, ``deposit_chf``,
``period`` — because the rows combine them freely ("Fr. 3.–, plus Depot Fr. 20.–" is a fee
plus a refundable deposit; "Saisonkabine" is a rental period on top of both).

Defined in mietobjekt-extraction S1 (so `providers.mietobjekt.parse_mietobjekte`'s return
shape never changes); wired onto `Facility` in S2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class RentalKind(Enum):
    TOWEL = "towel"  # Badetuch
    SWIMWEAR = "swimwear"  # Badebekleidung / Badehosen
    GOGGLES = "goggles"  # Schwimmbrille
    CABIN = "cabin"  # Saisonkabine / Tageskabine — the rental term rides `period`
    SUNLOUNGER = "sunlounger"  # Liegestuhl
    PARASOL = "parasol"  # Sonnenschirm
    OTHER = "other"  # anything else — kept, never dropped; the label rides `raw`


@dataclass(frozen=True, slots=True)
class RentalItem:
    """One rentable item — static, sourced from a pool page's ``Mietobjekt`` row.

    ``fee_chf`` is the usage cost (``None`` = the page states no fee, e.g. "auf Anfrage");
    ``deposit_chf`` a refundable monetary Pfand (``None`` also when the deposit is
    non-monetary — "plus Ausweis als Depot" — which survives in ``raw``); ``period`` free
    text ("Saison", "Tages") deliberately not parsed. ``raw`` keeps the exact source row
    for audit/reparse — for ``OTHER`` it is the only carrier of the label.
    """

    kind: RentalKind
    fee_chf: Decimal | None = None
    deposit_chf: Decimal | None = None
    period: str | None = None
    raw: str = ""
