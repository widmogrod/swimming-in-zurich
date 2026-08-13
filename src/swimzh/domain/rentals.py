"""Rental offerings at a facility — the non-locker half of the pool pages' ``Mietobjekt`` table.

The same page rows that state the lockers (see `swimzh.domain.lockers`) also state rentals:
towels, swimwear, goggles, changing cabins, sun loungers, parasols, and one-off oddities
(a Lounge, a Pavillon, a sports hall). Kinds earn membership by corpus frequency across the
declared sources' committed pages (Kabine ×19, Liegestuhl ×9, Sonnenschirm ×8); everything
else routes to ``OTHER`` with the source row preserved in ``raw`` — the UNMAPPED idiom, so
no published row is ever dropped.

The fee is a closed three-state union (`RentalFee`), NOT a nullable amount, because the
corpus states free-ness and states nothing in different cells: a Liegestuhl row prints
"gratis, plus Depot Fr. 2.–" (a stated fact) while a Mehrzweckraum row prints "auf Anfrage"
(no stated fee at all). One ``fee_chf: None`` covering both would compress a stated fact
and an absent fact into one value — the admission-union `Free`/`Unknown` lesson at rental
scale. Deposit and ``period`` stay ORTHOGONAL optionals as on `LockerOption`, because the
rows combine them freely ("Fr. 3.–, plus Depot Fr. 20.–" is a fee plus a refundable
deposit; "Saisonkabine" is a rental period on top of both).

Types defined in mietobjekt-extraction S1 (so `providers.mietobjekt.parse_mietobjekte`'s
return shape never changes); wired onto `Facility` — and the fee widened to the union, per
the S1 review directive — in S2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
class Priced:
    """The page prints an amount: "Fr. 3.–"."""

    amount_chf: Decimal


@dataclass(frozen=True, slots=True)
class Gratis:
    """The page STATES the rental is free ("gratis, plus Depot Fr. 2.–") — a positive fact
    off the page, never to be conflated with the page saying nothing."""


@dataclass(frozen=True, slots=True)
class Unstated:
    """The page states no fee at all ("auf Anfrage", "Vermietung via Kiosk") — the honest
    unknown. The prose survives in the item's ``raw``."""


#: The closed fee union. `Priced` and `Gratis` are page-stated facts; `Unstated` is the
#: absence of one. Consumers `match` all three arms and end with `assert_never`.
RentalFee = Priced | Gratis | Unstated


@dataclass(frozen=True, slots=True)
class RentalItem:
    """One rentable item — static, sourced from a pool page's ``Mietobjekt`` row.

    ``fee`` is the closed `RentalFee` union (see module docstring — stated-free vs unstated
    are different facts); ``deposit_chf`` a refundable monetary Pfand (``None`` also when
    the deposit is non-monetary — "plus Ausweis als Depot" — which survives in ``raw``);
    ``period`` free text ("Saison", "Tages") deliberately not parsed. ``raw`` keeps the
    exact source row for audit/reparse — for ``OTHER`` it is the only carrier of the label.
    """

    kind: RentalKind
    fee: RentalFee = field(default_factory=Unstated)
    deposit_chf: Decimal | None = None
    period: str | None = None
    raw: str = ""
