"""The gold codec must be an exact inverse: loads(dumps(f)) == f for real facilities,
including nested tagged-union access, prices (Decimal), closures, and provenance."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from swimzh.core.result import Ok
from swimzh.domain.access import ClubReserved, PublicSwim
from swimzh.domain.lane_plan import LanePlan, LaneReservation, PlanConfidence, PlanCoverage
from swimzh.domain.lockers import LockerCategory, LockerMechanism, LockerOption
from swimzh.domain.models import (
    BasinKind,
    BasinSource,
    Dimensions,
    Facility,
    Feature,
    FeatureKind,
)
from swimzh.domain.schedule import TimeRange, Weekday
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.facilities


def test_roundtrip_all_curated_facilities(facilities: tuple[Facility, ...]) -> None:
    assert len(facilities) == 4
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


def test_curated_city_carries_facility_level_statics(facilities: tuple[Facility, ...]) -> None:
    # The curated YAML schema expresses website/features/lockers, and the all-facilities
    # round-trip above already proves they survive the codec on real data.
    city = next(f for f in facilities if str(f.identity.facility_id) == "city")
    assert city.website is not None
    assert {f.kind for f in city.features} == {FeatureKind.SAUNA}
    assert city.features[0].hours, "sauna hours should be curated as ScheduleRules"
    assert {lo.category for lo in city.lockers} == set(LockerCategory)


def test_roundtrip_covers_every_facility_level_static_field(
    facilities: tuple[Facility, ...],
) -> None:
    # Populate every new Facility field — feature hours, surcharge/temp/note, and all
    # locker axes at once (incl. mechanism) — and prove the codec stays an exact inverse.
    base = facilities[0]
    facility = replace(
        base,
        website="https://example.org/hallenbad",
        features=(
            Feature(
                kind=FeatureKind.STEAM_BATH,
                name="Dampfbad",
                hours=base.basins[0].rules[:1],
                surcharge_chf=Decimal("10.00"),
                temp_c=Decimal("45.5"),
                note="gemischt",
            ),
        ),
        lockers=(
            LockerOption(
                category=LockerCategory.VALUABLES,
                fee_chf=Decimal("3.00"),
                deposit_chf=Decimal("20.00"),
                period="Saison",
                mechanism=LockerMechanism.COIN,
                raw="Badetuch Fr. 3.–, plus Depot Fr. 20.–",
            ),
        ),
    )
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    assert back.features[0].hours == base.basins[0].rules[:1]
    assert back.lockers[0].mechanism is LockerMechanism.COIN


def test_roundtrip_basin_carrying_a_lane_plan(facilities: tuple[Facility, ...]) -> None:
    # Correctness trap #3 (STORED side): a basin carrying a LanePlan must round-trip exactly,
    # including sorted frozensets and PARTIAL coverage with unresolved lanes.
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY, Weekday.MONDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({2, 1}),
                access=ClubReserved(club="ASVZ"),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({3, 4, 5, 6}),
                access=PublicSwim(),
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.PARTIAL,
            cells_total=1344,
            cells_resolved=1300,
            unresolved_lanes=frozenset({5, 1}),
        ),
    )
    base = facilities[0]
    facility = replace(base, basins=(replace(base.basins[0], lane_plan=plan), *base.basins[1:]))
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    assert back.basins[0].lane_plan == plan


def test_occupancy_and_lane_availability_never_leak_into_gold(
    facilities: tuple[Facility, ...],
) -> None:
    # Correctness trap #2/#3 (DERIVED side): occupancy AND lane *availability* are live-only /
    # query-time derivations — their absence from gold must be a guarded regression, not just
    # structural. The STORED `lane_plan` IS serialised; the DERIVED `LaneAvailability` /
    # `lane_availability` must never be. Dump a plan-carrying basin so the guard is meaningful.
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
                access=ClubReserved(club="ASVZ"),
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )
    with_plan = replace(
        facilities[0],
        basins=(replace(facilities[0].basins[0], lane_plan=plan), *facilities[0].basins[1:]),
    )
    for facility in (*facilities, with_plan):
        dumped = codec.dumps(facility).lower()
        assert "occupancy" not in dumped
        assert "lane_availability" not in dumped
        assert "laneavailability" not in dumped
    # The stored plan itself must still be present (proves the guard rejects the derived type,
    # not lane data wholesale).
    assert "lane_plan" in codec.dumps(with_plan).lower()


def test_legacy_basin_level_length_m_is_rejected(facilities: tuple[Facility, ...]) -> None:
    # The old flat `length_m` field is gone; a stale gold payload using it must fail
    # loudly (extra="forbid") instead of being silently dropped.
    payload = json.loads(codec.dumps(facilities[0]))
    payload["basins"][0]["length_m"] = 50
    with pytest.raises(ValidationError):
        codec.loads(json.dumps(payload))
