"""The gold codec must be an exact inverse: loads(dumps(f)) == f for real facilities,
including nested tagged-union access, prices (Decimal), closures, and provenance."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from swimzh.core.result import Ok
from swimzh.domain.models import BasinKind, BasinSource, Dimensions, Facility
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.facilities


def test_roundtrip_all_curated_facilities(facilities: tuple[Facility, ...]) -> None:
    assert len(facilities) == 3
    for facility in facilities:
        assert codec.loads(codec.dumps(facility)) == facility


def test_roundtrip_preserves_stamped_fields(facilities: tuple[Facility, ...]) -> None:
    stamped = replace(
        facilities[0],
        identity=replace(facilities[0].identity, geo_sport_id="poi_hallenbad_view.99"),
        provenance=replace(
            facilities[0].provenance,
            fetched_at=datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Europe/Zurich")),
        ),
    )
    back = codec.loads(codec.dumps(stamped))
    assert back == stamped
    assert back.identity.geo_sport_id == "poi_hallenbad_view.99"
    assert back.provenance.fetched_at == stamped.provenance.fetched_at


def test_curated_basins_carry_kind_and_decimal_dimensions(
    facilities: tuple[Facility, ...],
) -> None:
    # The YAML migration replaced `length_m: 50` with `dimensions: {length_m: "50"}`.
    city = next(f for f in facilities if str(f.identity.facility_id) == "city")
    fifty = next(b for b in city.basins if str(b.basin_id) == "city-50m")
    assert fifty.kind is BasinKind.LAP
    assert fifty.dimensions == Dimensions(length_m=Decimal("50"))
    assert fifty.physical_source is BasinSource.CURATED


def test_roundtrip_covers_every_physical_basin_field(facilities: tuple[Facility, ...]) -> None:
    # Populate every new Basin field (incl. fractional Decimals and PARSED_PROSE) and
    # prove the codec is still an exact inverse.
    base = facilities[0]
    physical = replace(
        base.basins[0],
        kind=BasinKind.VARIO,
        dimensions=Dimensions(length_m=Decimal("16.66"), width_m=Decimal("10.5")),
        lanes=6,
        nominal_temp_c=Decimal("30.5"),
        physical_source=BasinSource.PARSED_PROSE,
    )
    facility = replace(base, basins=(physical, *base.basins[1:]))
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    first = back.basins[0]
    assert first.kind is BasinKind.VARIO
    assert first.dimensions == Dimensions(length_m=Decimal("16.66"), width_m=Decimal("10.5"))
    assert first.lanes == 6
    assert first.nominal_temp_c == Decimal("30.5")
    assert first.physical_source is BasinSource.PARSED_PROSE


def test_legacy_basin_level_length_m_is_rejected(facilities: tuple[Facility, ...]) -> None:
    # The old flat `length_m` field is gone; a stale gold payload using it must fail
    # loudly (extra="forbid") instead of being silently dropped.
    payload = json.loads(codec.dumps(facilities[0]))
    payload["basins"][0]["length_m"] = 50
    with pytest.raises(ValidationError):
        codec.loads(json.dumps(payload))
