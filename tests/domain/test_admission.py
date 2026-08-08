"""The `Admission` union keeps free / tariff / unknown distinct on the `Facility` aggregate —
and the compressed `prices` field cannot quietly return."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from swimzh.domain.admission import Free, Tariff, Unknown
from swimzh.domain.models import Facility, PoolId, PoolIdentity, PoolKind, Provenance
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable


def _facility() -> Facility:
    return Facility(
        identity=PoolIdentity(PoolId("hallenbad-x"), "Hallenbad X", PoolKind.INDOOR),
        address="Somewhere 1",
        provenance=Provenance(source="curated", curated=True),
        basins=(),
    )


def test_the_compressed_prices_field_cannot_return() -> None:
    """`prices: PriceTable | None` compressed *free* and *unknown* into one null; the union
    replaced it. Asserted via `dataclasses.fields`, NOT `hasattr`: a re-added field without a
    default creates no class attribute, so `hasattr(Facility, "prices")` would stay False while
    the field silently returned."""
    assert "prices" not in {f.name for f in dataclasses.fields(Facility)}
    assert "admission" in {f.name for f in dataclasses.fields(Facility)}


def test_a_facility_defaults_to_the_honest_unknown() -> None:
    # `Unknown` is the zero object: a facility no source has priced is unknown, never free.
    assert _facility().admission == Unknown()
    assert _facility().admission != Free()


def test_the_three_arms_are_distinct_values() -> None:
    table = PriceTable(entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Adult"),))
    arms = (Free(), Tariff(table), Unknown())
    assert len({type(a) for a in arms}) == 3
    for i, a in enumerate(arms):
        for b in arms[i + 1 :]:
            assert a != b
