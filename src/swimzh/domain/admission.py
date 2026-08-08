"""The admission union: free is a fact the city publishes, not a missing price.

Four pools state *"Der Eintritt … ist gratis"* (or *"ein Gratisbad"*) on their own page. Before
this union, that fact was compressed into ``prices=None`` — the same value carried by the 32
pools nobody has priced. ``Admission`` keeps the three states distinct:

* ``Free`` — the pool's own page states admission is free. Asserted only from that page
  sentence (``price_scraper.states_free_admission``), never inferred from a missing tariff
  link, a hostname, or a kind.
* ``Tariff`` — the pool's page links the city tariff page; ``table`` is the published rate it
  is served (general or Schulschwimmanlage, by kind).
* ``Unknown`` — the page states neither. The honest default for a pool whose admission no
  source has established (and the reading given to any pre-union stored blob).

The union is closed: consumers ``match`` it and end with ``assert_never``.
"""

from __future__ import annotations

from dataclasses import dataclass

from swimzh.domain.pricing import PriceTable


@dataclass(frozen=True, slots=True)
class Free:
    """The pool's own page states admission is free."""


@dataclass(frozen=True, slots=True)
class Tariff:
    """The pool is served a published admission tariff."""

    table: PriceTable


@dataclass(frozen=True, slots=True)
class Unknown:
    """No source states this pool's admission — distinct from free."""


type Admission = Free | Tariff | Unknown
