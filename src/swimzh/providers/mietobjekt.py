"""Parse a pool page's ``Mietobjekt | Preis`` table into lockers and rentals — one table,
two typed outputs.

The table sits on 20 of the 26 declared sources' pages (measured over the committed
fixtures; 6 carry none: altstetten, maennerbad, and the 4 Schulschwimmanlagen). It is
anchored by its own ``Mietobjekt`` column header inside a ``<stzh-datatable>`` element —
element-scoped and read off the RAW page, decoded with the escaped-JSON attribute machinery
`price_scraper` already owns, per the plan's recorded reuse decision (the attributes are
HTML-escaped, so unescaping the document first would destroy the attribute boundaries).

Row labels route by German noun:

* **lockers** (`LockerOption`): any ``…kasten`` label → ``WARDROBE`` (``Monatskasten`` /
  ``Saisonkasten`` carry their prefix as ``period`` — a Kasten is a locker whatever its
  rental term); ``Wertsachenfach`` → ``VALUABLES``; ``Wäschefach`` → ``LAUNDRY``, its
  ``(1/2 Jahr)``-style suffix as ``period`` verbatim, deliberately unparsed (the
  `LockerOption` docstring's standing decision).
* **rentals** (`RentalItem`): ``Badetuch`` → ``TOWEL``; ``Badebekleidung``/``Badehosen`` →
  ``SWIMWEAR``; ``Schwimmbrille`` → ``GOGGLES``; ``…kabine`` → ``CABIN`` (prefix as
  ``period``); ``Liegestuhl`` → ``SUNLOUNGER``; ``Sonnenschirm`` → ``PARASOL``; anything
  else → ``OTHER`` with the full row in ``raw`` — nothing is dropped.

**The cost grammar, specified against the real corpus, not three examples.** The tables
carry prose cells a naive parser would crash on ("gratis, eigenes Vorhängeschloss
mitbringen" on the Garderobenkasten row at the outdoor pools, "auf Anfrage",
"Vermietung via Restaurant/Kiosk", the non-monetary "Fr. 2.–, plus Ausweis als Depot"):

* a cell with **no** ``Fr.`` token → ``fee=None, deposit=None``, the prose preserved in
  ``raw`` — absence of a stated price is data, not an error;
* a cell **with** ``Fr.`` tokens → the first non-Depot amount is the fee (a
  ``"gratis, …"`` cell has none ⇒ ``fee=None``), a ``Depot Fr. N`` clause is the deposit;
  extra clauses ride in ``raw``; "Ausweis als Depot" carries no ``Fr.`` token ⇒
  ``deposit=None`` (non-monetary, kept in ``raw``);
* a ``Fr.`` token that yields **no parseable amount** → ``Err(ParseError)``, fatal — that
  is garble, not prose.

A page without the table is **not** a failure — it yields ``Ok`` with empty tuples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from swimzh.core.errors import ParseError, ProviderError
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.lockers import LockerCategory, LockerOption
from swimzh.domain.rentals import RentalItem, RentalKind

# The shared escaped-JSON <stzh-datatable> machinery — deliberately imported from
# price_scraper (the plan's recorded reuse decision) rather than re-implemented: it already
# handles the escaped attributes, endash cents, nbsp, and <p>-wrapped values.
from swimzh.providers.price_scraper import (
    _COLUMNS_ATTR,
    _ROWS_ATTR,
    _TABLE_SPLIT,
    _cells,
    _headers,
    _money,
)

_SOURCE = "mietobjekt"

#: The anchoring column header — the table is recognised by ITS OWN first header, never by
#: position on the page.
_MIETOBJEKT_HEADER = "Mietobjekt"

#: A price amount announces itself with a `Fr.` token; a `Depot` immediately before it makes
#: the amount a refundable deposit rather than the usage fee.
_FR_TOKEN = re.compile(r"(Depot\s+)?Fr\.")

#: A trailing parenthesized label suffix — "Wäschefach (1/2 Jahr)" — split off before routing.
_LABEL_SUFFIX = re.compile(r"^(?P<base>.*\S)\s*\((?P<suffix>[^)]+)\)$")


@dataclass(frozen=True, slots=True)
class MietobjektTable:
    """The one page table, routed onto its two typed outputs. Empty tuples == no table."""

    lockers: tuple[LockerOption, ...] = ()
    rentals: tuple[RentalItem, ...] = ()


@dataclass(frozen=True, slots=True)
class _Cost:
    """The two orthogonal monetary axes one price cell decomposes onto."""

    fee: Decimal | None
    deposit: Decimal | None


def _cost(cell: str) -> Result[_Cost, ProviderError]:
    """Decompose one price cell per the corpus grammar (module docstring)."""
    fee: Decimal | None = None
    deposit: Decimal | None = None
    for token in _FR_TOKEN.finditer(cell):
        amount = _money(cell[token.end() :])
        if amount is None:
            return Err(
                ParseError(
                    source=_SOURCE,
                    detail=f"Fr. token with no parseable amount: {cell!r}",
                    raw_snippet=cell,
                )
            )
        if token.group(1) is not None:
            deposit = amount if deposit is None else deposit
        elif fee is None:
            fee = amount
    return Ok(_Cost(fee=fee, deposit=deposit))


def _split_label(label: str) -> tuple[str, str | None]:
    """``"Wäschefach (1/2 Jahr)"`` → ``("Wäschefach", "1/2 Jahr")``; no suffix → ``None``."""
    match = _LABEL_SUFFIX.match(label)
    if match is None:
        return label, None
    return match.group("base"), match.group("suffix")


def _locker(base: str, suffix: str | None, cost: _Cost, raw: str) -> LockerOption | None:
    """The locker routes — ``None`` when the label is not a locker noun (→ rentals)."""
    lowered = base.lower()
    if lowered.endswith("kasten"):
        # A Kasten is a locker whatever its rental term: Monatskasten/Saisonkasten carry
        # their term prefix as `period` (verbatim, deliberately unparsed); the plain
        # Garderobenkasten has none — "Garderoben" is the noun, not a term.
        prefix = base[: -len("kasten")]
        period = suffix if suffix is not None else prefix if lowered != "garderobenkasten" else None
        return LockerOption(
            category=LockerCategory.WARDROBE,
            fee_chf=cost.fee,
            deposit_chf=cost.deposit,
            period=period,
            raw=raw,
        )
    if base in ("Wertsachenfach", "Wäschefach"):
        category = LockerCategory.VALUABLES if base == "Wertsachenfach" else LockerCategory.LAUNDRY
        return LockerOption(
            category=category, fee_chf=cost.fee, deposit_chf=cost.deposit, period=suffix, raw=raw
        )
    return None


def _rental(base: str, suffix: str | None, cost: _Cost, raw: str) -> RentalItem:
    """The rental routes — every non-locker label lands here; unknown nouns are ``OTHER``."""
    lowered = base.lower()
    period = suffix
    if base == "Badetuch":
        kind = RentalKind.TOWEL
    elif base in ("Badebekleidung", "Badehosen"):
        kind = RentalKind.SWIMWEAR
    elif base == "Schwimmbrille":
        kind = RentalKind.GOGGLES
    elif lowered.endswith("kabine"):
        kind = RentalKind.CABIN
        period = suffix if suffix is not None else base[: -len("kabine")]
    elif base == "Liegestuhl":
        kind = RentalKind.SUNLOUNGER
    elif base == "Sonnenschirm":
        kind = RentalKind.PARASOL
    else:
        # The no-drop guarantee: an unmapped label ("Mööslihalle (35 x 16 Meter)", "Lounge")
        # is kept as OTHER with the full row in `raw`. Its parenthesized suffix is NOT a
        # rental period (Mööslihalle's is its dimensions), so `period` stays None.
        return RentalItem(
            kind=RentalKind.OTHER, fee_chf=cost.fee, deposit_chf=cost.deposit, raw=raw
        )
    return RentalItem(kind=kind, fee_chf=cost.fee, deposit_chf=cost.deposit, period=period, raw=raw)


def parse_mietobjekte(page_html: str) -> Result[MietobjektTable, ProviderError]:
    """Every row of every ``Mietobjekt``-anchored table, routed to lockers or rentals.

    Absence of the table is data, not an error — ``Ok`` with empty tuples (6 of the 26
    declared sources carry none). Malformedness in a table that IS present is
    ``Err(ParseError)`` — a garbled price cell, or a ``Mietobjekt``-anchored element whose
    ``columns=``/``rows=`` attribute no longer decodes (the table EXISTS but cannot be read;
    silently serving ``lockers: []`` for it would be indistinguishable from absence).
    Fail-fast on garble, tolerant of absence and of prose.
    """
    lockers: list[LockerOption] = []
    rentals: list[RentalItem] = []
    for chunk in page_html.split(_TABLE_SPLIT)[1:]:
        columns, rows = _COLUMNS_ATTR.search(chunk), _ROWS_ATTR.search(chunk)
        if columns is None or rows is None:
            continue
        # The anchor test runs on the RAW attribute text, so a Mietobjekt table whose
        # attribute fails to decode is still recognised as PRESENT — and therefore fatal —
        # rather than skipped as if the page carried no table at all.
        if _MIETOBJEKT_HEADER not in columns.group(1):
            continue
        headers, decoded = _headers(columns.group(1)), _cells(rows.group(1))
        if headers is None or decoded is None:
            return Err(
                ParseError(
                    source=_SOURCE,
                    detail=(
                        "Mietobjekt-anchored <stzh-datatable> whose columns=/rows= "
                        "attribute failed to decode"
                    ),
                    raw_snippet=chunk[:200],
                )
            )
        if not headers or headers[0] != _MIETOBJEKT_HEADER:
            continue
        for row in decoded:
            if not row or not row[0]:
                continue
            label = row[0]
            cell = row[1] if len(row) > 1 else ""
            cost = _cost(cell)
            if isinstance(cost, Err):
                return Err(cost.error)
            raw = f"{label} | {cell}"
            base, suffix = _split_label(label)
            locker = _locker(base, suffix, cost.value, raw)
            if locker is not None:
                lockers.append(locker)
            else:
                rentals.append(_rental(base, suffix, cost.value, raw))
    return Ok(MietobjektTable(lockers=tuple(lockers), rentals=tuple(rentals)))
