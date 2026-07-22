"""The gold codec must be an exact inverse: loads(dumps(f)) == f for real facilities,
including nested tagged-union access, prices (Decimal), closures, and provenance."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from swimzh.core.errors import (
    ConnectionFailed,
    DecodeError,
    HttpStatus,
    ParseError,
    ProviderError,
    ProviderSpecific,
    RateLimited,
    Redirect,
    SchemaMismatch,
    Timeout,
    TooLarge,
)
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
    LanePlanSource,
    LanePlanUnavailable,
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
    # 4 fully-curated pools + 3 lane-plan-only pools (leimbach/blaesi/käferberg carry a minimal
    # schedule-less basin with a `lane_plan_source`).
    assert len(facilities) == 7
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
    city = next(f for f in facilities if str(f.identity.facility_id) == "hallenbad-city")
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


def test_roundtrip_covers_slice_f_basin_and_facility_fields(
    facilities: tuple[Facility, ...],
) -> None:
    # Slice F additive fields (measured temp, diving heights, accessibility, last admission)
    # round-trip EXACTLY through the gold codec.
    base = facilities[0]
    basin = replace(
        base.basins[0],
        nominal_temp_c=Decimal("28"),
        measured_temp_c=Decimal("26.5"),
        diving_platforms_m=(Decimal("1"), Decimal("3"), Decimal("5")),
    )
    facility = replace(
        base,
        basins=(basin, *base.basins[1:]),
        accessibility="barrierefrei, Lift zum Becken",
        last_admission_before=timedelta(minutes=30),
    )
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    assert back.basins[0].measured_temp_c == Decimal("26.5")
    assert back.basins[0].diving_platforms_m == (Decimal("1"), Decimal("3"), Decimal("5"))
    assert back.accessibility == "barrierefrei, Lift zum Becken"
    assert back.last_admission_before == timedelta(minutes=30)


def test_basin_without_slice_f_fields_serializes_without_the_new_keys(
    facilities: tuple[Facility, ...],
) -> None:
    # Additive-and-invisible guard (mirrors the Slice-D lane-plan guard): a basin with neither
    # Slice-F basin field set must add NOTHING to the payload, so pre-Slice-F gold is byte-stable.
    dumped = codec.dumps(facilities[0])
    assert '"measured_temp_c"' not in dumped
    assert '"diving_platforms_m"' not in dumped


def test_curated_city_carries_facility_level_statics(facilities: tuple[Facility, ...]) -> None:
    # The curated YAML schema expresses website/features/lockers, and the all-facilities
    # round-trip above already proves they survive the codec on real data.
    city = next(f for f in facilities if str(f.identity.facility_id) == "hallenbad-city")
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


def test_roundtrip_plan_with_lanes_by_weekday_and_sectioned_reservation(
    facilities: tuple[Facility, ...],
) -> None:
    # Slice D fidelity: a movable-floor plan (ragged `lanes_by_weekday`) carrying a reservation
    # tagged with a named `section` must survive dumps -> loads EXACTLY (deep equality).
    plan = LanePlan(
        lane_count=4,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.MONDAY, Weekday.WEDNESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
                access=ClubReserved(club="ASVZ"),
                section="Teil 1",
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.SATURDAY}),
                time=TimeRange(time(9, 0), time(12, 0)),
                lanes=frozenset({1, 2, 3}),
                access=PublicSwim(),
                section="Teil 2",
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=100, cells_resolved=100
        ),
        lanes_by_weekday={
            Weekday.MONDAY: 4,
            Weekday.WEDNESDAY: 4,
            Weekday.SATURDAY: 3,
        },
    )
    base = facilities[0]
    facility = replace(base, basins=(replace(base.basins[0], lane_plan=plan), *base.basins[1:]))
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    round_tripped = back.basins[0].lane_plan
    assert isinstance(round_tripped, LanePlan)
    assert round_tripped == plan
    assert round_tripped.lanes_by_weekday == {
        Weekday.MONDAY: 4,
        Weekday.WEDNESDAY: 4,
        Weekday.SATURDAY: 3,
    }
    assert {r.section for r in round_tripped.reservations} == {"Teil 1", "Teil 2"}


def test_uniform_plan_serializes_without_the_new_slice_d_keys(
    facilities: tuple[Facility, ...],
) -> None:
    # Backward-compat guard: an existing uniform plan (both new fields defaulting to None) must
    # add NOTHING to the payload — the serialized form is byte-identical to pre-Slice-D gold, so
    # old blobs still load and re-dump identically. Explicitly forbid the new keys.
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
    base = facilities[0]
    facility = replace(base, basins=(replace(base.basins[0], lane_plan=plan), *base.basins[1:]))
    dumped = codec.dumps(facility)
    assert '"lanes_by_weekday"' not in dumped
    assert '"section"' not in dumped
    # And it still round-trips exactly with both new fields None.
    back = codec.loads(dumped)
    assert back == facility
    restored = back.basins[0].lane_plan
    assert isinstance(restored, LanePlan)
    assert restored.lanes_by_weekday is None
    assert all(r.section is None for r in restored.reservations)


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
        # The query-time TIMELINE is likewise derived-only. Its serialized keys would be
        # `lane_timeline`/`segments` — none containing "lane_availability" — so the guard must
        # forbid "timeline" explicitly, else a timeline leaked into the codec DTO stays green.
        assert "timeline" not in dumped
    # The stored plan itself must still be present (proves the guard rejects the derived type,
    # not lane data wholesale).
    assert "lane_plan" in codec.dumps(with_plan).lower()


# --- lane_plan_source + lane_plan extraction-outcome codec (reconciliation slice) ---

_ALL_PROVIDER_ERRORS: list[ProviderError] = [
    Timeout(url="https://x/a.pdf", after_s=12.5),
    ConnectionFailed(url="https://x/a.pdf", detail="connection refused"),
    HttpStatus(url="https://x/a.pdf", status=503, body_snippet="<html>down</html>"),
    RateLimited(url="https://x/a.pdf", retry_after_s=30.0),
    RateLimited(url="https://x/a.pdf", retry_after_s=None),
    DecodeError(source="belegungsplan", detail="bad gzip"),
    ParseError(source="belegungsplan", detail="unreadable PDF", raw_snippet="%PDF-1.4"),
    SchemaMismatch(source="belegungsplan", detail="no weekday header row"),
    TooLarge(url="https://x/a.pdf", limit_bytes=1048576),
    Redirect(url="https://x/a.pdf", location="https://y/", count=5),
    ProviderSpecific(provider="belegungsplan", detail={"code": 7, "nested": ["a", None, True]}),
    ProviderSpecific(provider="belegungsplan", detail="pdfplumber not installed"),
    ProviderSpecific(provider="belegungsplan", detail=None),
]


def test_lane_plan_source_round_trips_and_is_absent_when_unset(
    facilities: tuple[Facility, ...],
) -> None:
    base = facilities[0]
    # A basin with no source adds nothing to the payload (byte-stability of pre-existing blobs).
    assert '"lane_plan_source"' not in codec.dumps(base)

    source = LanePlanSource(url="https://example.test/city-schwimmerbecken.pdf")
    facility = replace(
        base, basins=(replace(base.basins[0], lane_plan_source=source), *base.basins[1:])
    )
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    assert back.basins[0].lane_plan_source == source
    # `section` is omitted from the payload when None (Slice-D-style pop-when-default).
    assert '"section"' not in codec.dumps(facility)


def test_provider_error_union_round_trips_losslessly_through_the_dto() -> None:
    # Acceptance: the FULL closed ProviderError union — incl. every ProviderSpecific payload shape
    # — survives the boundary codec as a `LanePlanUnavailable.cause`, deep-equal, no repr.
    base_facility = load_dataset(DATA_DIR)
    assert isinstance(base_facility, Ok)
    base = base_facility.value.facilities[0]
    for cause in _ALL_PROVIDER_ERRORS:
        unavailable = LanePlanUnavailable(
            source_url="https://example.test/a.pdf",
            section=None,
            cause=cause,
            observed_at=datetime(2026, 7, 18, 9, 0, tzinfo=ZoneInfo("Europe/Zurich")),
        )
        facility = replace(
            base, basins=(replace(base.basins[0], lane_plan=unavailable), *base.basins[1:])
        )
        back = codec.loads(codec.dumps(facility))
        assert back == facility, cause
        restored = back.basins[0].lane_plan
        assert isinstance(restored, LanePlanUnavailable)
        assert restored.cause == cause


def test_lane_plan_unavailable_and_lane_plan_are_discriminated_by_shape(
    facilities: tuple[Facility, ...],
) -> None:
    # The widened `lane_plan` slot carries either a parsed LanePlan OR a LanePlanUnavailable; the
    # smart union must restore each to the right domain type from the same JSON slot.
    base = facilities[0]
    plan = LanePlan(
        lane_count=6,
        reservations=(),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(PlanConfidence.COMPLETE, cells_total=0, cells_resolved=0),
    )
    unavailable = LanePlanUnavailable(
        source_url="https://example.test/a.pdf",
        section="sprungbecken",
        cause=HttpStatus(url="https://example.test/a.pdf", status=404, body_snippet=""),
        observed_at=datetime(2026, 7, 18, 9, 0, tzinfo=ZoneInfo("Europe/Zurich")),
    )
    with_plan = replace(base, basins=(replace(base.basins[0], lane_plan=plan), *base.basins[1:]))
    with_miss = replace(
        base, basins=(replace(base.basins[0], lane_plan=unavailable), *base.basins[1:])
    )
    assert isinstance(codec.loads(codec.dumps(with_plan)).basins[0].lane_plan, LanePlan)
    restored_miss = codec.loads(codec.dumps(with_miss)).basins[0].lane_plan
    assert isinstance(restored_miss, LanePlanUnavailable)
    assert restored_miss.section == "sprungbecken"


def test_legacy_basin_level_length_m_is_rejected(facilities: tuple[Facility, ...]) -> None:
    # The old flat `length_m` field is gone; a stale gold payload using it must fail
    # loudly (extra="forbid") instead of being silently dropped.
    payload = json.loads(codec.dumps(facilities[0]))
    payload["basins"][0]["length_m"] = 50
    with pytest.raises(ValidationError):
        codec.loads(json.dumps(payload))
