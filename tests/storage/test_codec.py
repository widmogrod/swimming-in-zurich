"""The gold codec must be an exact inverse: loads(dumps(f)) == f for real facilities,
including nested tagged-union access, prices (Decimal), closures, and provenance."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
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
from swimzh.domain.access import ClubReserved, GirlsOnly, PublicSwim
from swimzh.domain.admission import Free, Tariff, Unknown
from swimzh.domain.lane_plan import LanePlan, LaneReservation, PlanConfidence, PlanCoverage
from swimzh.domain.lockers import LockerCategory, LockerMechanism, LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    BasinSource,
    Dimensions,
    Facility,
    Feature,
    FeatureKind,
    LanePlanSource,
    LanePlanUnavailable,
    OperatingSeason,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.rentals import Gratis, Priced, RentalItem, RentalKind, Unstated
from swimzh.domain.schedule import (
    AnnualWindow,
    DatePrecision,
    MonthDay,
    ResolvedSession,
    ScheduleException,
    ScheduleRule,
    TimeRange,
    Weather,
    Weekday,
)
from swimzh.storage import codec

_RULE = ScheduleRule(
    weekdays=frozenset({Weekday.MONDAY}),
    time=TimeRange(start=time(11, 0), end=time(22, 0)),
    access=PublicSwim(),
)


def _rich_facility() -> Facility:
    """A fully-populated facility standing in for a composed store row: a ruled basin carrying
    physicals + a lane binding, plus facility-level statics (features/lockers). Built
    in-memory because curated YAML no longer carries any of this (delete-curated-schedule-tier S3);
    the codec is a pure inverse, so a synthetic subject exercises it exactly as a real one did."""
    return Facility(
        identity=PoolIdentity(PoolId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="Sihlstrasse 71, 8001 Zürich",
        provenance=Provenance(
            source="schedule_scraper", curated=False, valid_as_of=date(2026, 7, 18)
        ),
        basins=(
            Basin(
                basin_id=BasinId("city-50m"),
                name="Schwimmerbecken",
                rules=(_RULE,),
                kind=BasinKind.LAP,
                dimensions=Dimensions(length_m=Decimal("50")),
                physical_source=BasinSource.CURATED,
            ),
        ),
        features=(
            Feature(
                kind=FeatureKind.SAUNA,
                name="Gemischte Sauna",
                hours=(_RULE,),
                surcharge_chf=Decimal("10.00"),
            ),
        ),
        lockers=tuple(LockerOption(category=cat) for cat in LockerCategory),
    )


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    # A synthetic pair: a rich composed-store row + a minimal lane-binding-only pool.
    minimal = Facility(
        identity=PoolIdentity(PoolId("hallenbad-blaesi"), "Hallenbad Bläsi", PoolKind.INDOOR),
        address="Limmattalstrasse 154, 8049 Zürich",
        provenance=Provenance(source="curated", curated=True),
        basins=(Basin(basin_id=BasinId("blaesi-25m"), name="25m-Becken", rules=()),),
    )
    return (_rich_facility(), minimal)


def test_roundtrip_all_facilities(facilities: tuple[Facility, ...]) -> None:
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


def test_basins_carry_kind_and_decimal_dimensions(
    facilities: tuple[Facility, ...],
) -> None:
    # A basin's physicals (kind + Decimal dimensions + physical_source) survive the codec exactly.
    fifty = next(b for b in facilities[0].basins if str(b.basin_id) == "city-50m")
    assert fifty.kind is BasinKind.LAP
    assert fifty.dimensions == Dimensions(length_m=Decimal("50"))
    assert fifty.physical_source is BasinSource.CURATED
    assert codec.loads(codec.dumps(facilities[0])).basins[0] == fifty


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
        last_admission_before=timedelta(minutes=30),
    )
    back = codec.loads(codec.dumps(facility))
    assert back == facility
    assert back.basins[0].measured_temp_c == Decimal("26.5")
    assert back.basins[0].diving_platforms_m == (Decimal("1"), Decimal("3"), Decimal("5"))
    assert back.last_admission_before == timedelta(minutes=30)


def test_basin_without_slice_f_fields_serializes_without_the_new_keys(
    facilities: tuple[Facility, ...],
) -> None:
    # Additive-and-invisible guard (mirrors the Slice-D lane-plan guard): a basin with neither
    # Slice-F basin field set must add NOTHING to the payload, so pre-Slice-F gold is byte-stable.
    dumped = codec.dumps(facilities[0])
    assert '"measured_temp_c"' not in dumped
    assert '"diving_platforms_m"' not in dumped


def test_a_default_source_text_adds_no_key_to_the_blob(
    facilities: tuple[Facility, ...],
) -> None:
    # `ScheduleRule.source_text` rides on EVERY rule in every blob (including FeatureDTO.hours),
    # so a rule that has none must serialise to exactly the same bytes as before the field. The
    # round-trip equality assertions cannot see a new key; only this can.
    dumped = codec.dumps(facilities[0])
    assert '"source_text"' not in dumped


def test_a_scraped_rules_source_text_round_trips(facilities: tuple[Facility, ...]) -> None:
    # ...and when the source DID say something, it must survive the store verbatim.
    cell = "Öffentliches Schwimmen (für\xa0Mädchen, Tiefe 125 cm)"
    base = facilities[0]
    basin = base.basins[0]
    rule = replace(basin.rules[0], access=GirlsOnly(), source_text=cell)
    facility = replace(
        base, basins=(replace(basin, rules=(rule, *basin.rules[1:])), *base.basins[1:])
    )
    dumped = codec.dumps(facility)
    assert '"source_text"' in dumped
    assert codec.loads(dumped) == facility


def test_facility_level_statics_survive_the_codec(facilities: tuple[Facility, ...]) -> None:
    # Facility-level statics (features/lockers) round-trip through the codec.
    city = codec.loads(codec.dumps(facilities[0]))
    assert {f.kind for f in city.features} == {FeatureKind.SAUNA}
    assert city.features[0].hours, "sauna hours should survive as ScheduleRules"
    assert {lo.category for lo in city.lockers} == set(LockerCategory)


def test_roundtrip_covers_every_facility_level_static_field(
    facilities: tuple[Facility, ...],
) -> None:
    # Populate every new Facility field — feature hours, surcharge/temp/note, and all
    # locker axes at once (incl. mechanism) — and prove the codec stays an exact inverse.
    base = facilities[0]
    facility = replace(
        base,
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


def test_a_facility_without_rentals_serializes_without_the_key(
    facilities: tuple[Facility, ...],
) -> None:
    """S2 acceptance: `rentals` is POPPED when empty (the recorded deviation from the
    facility-level emit-unconditionally rule — the `admission_state`/`operating_season`/
    `min_age` precedent), so every blob without rentals — including a LOCKER-carrying one
    like the rich fixture — is byte-identical to its pre-S2 form."""
    for facility in facilities:
        assert facility.rentals == ()
        assert '"rentals"' not in codec.dumps(facility)
    assert facilities[0].lockers  # popping is per-field: lockers alone never emit rentals


def test_rentals_round_trip_losslessly_across_all_three_fee_arms(
    facilities: tuple[Facility, ...],
) -> None:
    """The full `RentalFee` union survives the store exactly: `Priced` rides `fee_chf`,
    `Gratis` rides the popped-when-absent `fee_state` discriminant, and `Unstated` rides
    neither — so a stated-gratis Liegestuhl and an `auf Anfrage` Mehrzweckraum can never
    collapse into one null in the blob (the S1-review directive, at the codec seam)."""
    rentals = (
        RentalItem(
            kind=RentalKind.TOWEL,
            fee=Priced(Decimal("3.00")),
            deposit_chf=Decimal("20.00"),
            raw="Badetuch | Fr. 3.–, plus Depot Fr. 20.–",
        ),
        RentalItem(
            kind=RentalKind.SUNLOUNGER,
            fee=Gratis(),
            deposit_chf=Decimal("2.00"),
            raw="Liegestuhl | gratis, plus Depot Fr. 2.–",
        ),
        RentalItem(
            kind=RentalKind.CABIN,
            fee=Priced(Decimal("120.00")),
            deposit_chf=Decimal("20.00"),
            period="Saison",
            raw="Saisonkabine | Fr. 120.–, plus Depot Fr. 20.–",
        ),
        RentalItem(kind=RentalKind.OTHER, fee=Unstated(), raw="Mehrzweckraum | auf Anfrage"),
    )
    facility = replace(facilities[0], rentals=rentals)
    dumped = codec.dumps(facility)
    # Only the stated-gratis row carries the discriminant key.
    assert dumped.count('"fee_state":"gratis"') == 1
    back = codec.loads(dumped)
    assert back == facility
    assert [r.fee for r in back.rentals] == [
        Priced(Decimal("3.00")),
        Gratis(),
        Priced(Decimal("120.00")),
        Unstated(),
    ]


def test_a_pre_s2_blob_without_the_rentals_key_loads_with_no_rentals(
    facilities: tuple[Facility, ...],
) -> None:
    # A gold blob written before S2 has no `rentals` key at all; it must load as the honest
    # empty tuple (and re-dump byte-identically, per the pop above).
    blob = json.loads(codec.dumps(facilities[1]))
    assert "rentals" not in blob
    assert codec.loads(json.dumps(blob)).rentals == ()


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


def test_price_min_age_round_trips_and_is_absent_when_unstated(
    facilities: tuple[Facility, ...],
) -> None:
    base = replace(
        facilities[0],
        admission=Tariff(
            PriceTable(entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Adult"),))
        ),
    )
    # An entry whose source printed no bound adds nothing to the payload.
    assert '"min_age"' not in codec.dumps(base)

    priced = replace(
        base,
        admission=Tariff(
            PriceTable(
                entries=(
                    PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Erwachsene", min_age=20),
                )
            )
        ),
    )
    back = codec.loads(codec.dumps(priced))
    assert back == priced
    assert isinstance(back.admission, Tariff)
    assert back.admission.table.entries[0].min_age == 20


# --- the admission union rides the `prices` key + one optional discriminant (admission-union S1) —


def test_tariff_and_unknown_facilities_serialize_without_the_admission_state_key(
    facilities: tuple[Facility, ...],
) -> None:
    """Byte-stability: only the `Free` arm adds bytes. A `Tariff` facility and an `Unknown` one
    must serialize exactly as they did before the union existed — no `admission_state` key."""
    unknown = facilities[1]
    assert unknown.admission == Unknown()
    tariff = replace(
        facilities[0],
        admission=Tariff(
            PriceTable(entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Adult"),))
        ),
    )
    for facility in (unknown, tariff):
        assert '"admission_state"' not in codec.dumps(facility)


def test_free_round_trips_via_the_discriminant_and_a_null_prices_key(
    facilities: tuple[Facility, ...],
) -> None:
    free = replace(facilities[0], admission=Free())
    dumped = codec.dumps(free)
    payload = json.loads(dumped)
    assert payload["admission_state"] == "free"
    assert payload["prices"] is None  # `Free` never invents a table
    back = codec.loads(dumped)
    assert back == free
    assert back.admission == Free()


def test_a_pre_union_blob_with_null_prices_loads_as_unknown(
    facilities: tuple[Facility, ...],
) -> None:
    """A blob written before the union carries `prices: null` and NO `admission_state` — the
    honest reading is `Unknown`, which is what keeps `scrape-gold`/`scrape-lanes` (which reload
    existing blobs) working across the change."""
    blob = json.loads(codec.dumps(facilities[1]))
    assert blob["prices"] is None
    assert "admission_state" not in blob  # this IS the pre-union shape, byte-for-byte
    assert codec.loads(json.dumps(blob)).admission == Unknown()


def test_provider_error_union_round_trips_losslessly_through_the_dto() -> None:
    # Acceptance: the FULL closed ProviderError union — incl. every ProviderSpecific payload shape
    # — survives the boundary codec as a `LanePlanUnavailable.cause`, deep-equal, no repr.
    base = _rich_facility()
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


# --- seasonal hours: additive AND invisible -------------------------------------------


def test_default_season_and_weather_add_no_key_to_the_blob(
    facilities: tuple[Facility, ...],
) -> None:
    # `season`/`weather` ride on EVERY rule in every blob (including `FeatureDTO.hours`), so an
    # all-year rule must serialise to exactly the same bytes as before the fields existed.
    # `RuleDTO._serialize` pops BY NAME, so a new defaulted field is invisible only if added there.
    dumped = codec.dumps(facilities[0])
    assert '"season"' not in dumped
    assert '"weather"' not in dumped


def test_default_weather_adds_no_key_to_an_exception_bearing_blob(
    facilities: tuple[Facility, ...],
) -> None:
    # The `ResolvedSessionDTO` path, reached via `ExceptionDTO.sessions`. That DTO had NO
    # serializer at all, so a bare additive `weather` field would have added a key to every
    # blob carrying a `ScheduleException` with sessions.
    base = facilities[0]
    basin = base.basins[0]
    exception = ScheduleException(
        date=date(2026, 5, 1),
        reason="Gala",
        sessions=(ResolvedSession(TimeRange(time(9), time(12)), PublicSwim()),),
    )
    facility = replace(base, basins=(replace(basin, exceptions=(exception,)), *base.basins[1:]))

    dumped = codec.dumps(facility)
    assert '"sessions":[{' in dumped, "the exception path must actually be exercised"
    assert '"weather"' not in dumped
    assert codec.loads(dumped) == facility


def test_a_seasoned_rule_round_trips(facilities: tuple[Facility, ...]) -> None:
    base = facilities[0]
    basin = base.basins[0]
    rules = (
        replace(basin.rules[0], season=AnnualWindow.whole_months(5, 9)),
        replace(
            basin.rules[0],
            time=TimeRange(start=time(14, 0), end=time(21, 0)),
            season=AnnualWindow(start=MonthDay(5, 30), end=MonthDay(8, 16)),
            weather=Weather.FAIR_ONLY,
        ),
    )
    facility = replace(base, basins=(replace(basin, rules=rules), *base.basins[1:]))

    dumped = codec.dumps(facility)
    assert '"season"' in dumped
    assert '"weather":"fair_only"' in dumped
    back = codec.loads(dumped)
    assert back == facility
    # `precision` is what makes "Mai–September" mean WHOLE months; losing it would silently
    # narrow the window to 1 May – 1 September.
    assert back.basins[0].rules[0].season == AnnualWindow.whole_months(5, 9)
    assert back.basins[0].rules[0].season is not None
    assert back.basins[0].rules[1].weather is Weather.FAIR_ONLY


def test_no_operating_season_adds_no_key_to_the_blob(
    facilities: tuple[Facility, ...],
) -> None:
    # Additive-and-invisible (sharedsource-fanout S1): the facility-level `operating_season`
    # is POPPED when None, so every pool without one — 44 of 57 — serializes byte-identically
    # to before the field existed.
    for facility in facilities:
        assert facility.operating_season is None
        assert '"operating_season"' not in codec.dumps(facility)


def test_an_operating_season_round_trips_losslessly(
    facilities: tuple[Facility, ...],
) -> None:
    # The Planschbecken shape: a rule-less facility carrying the page's month-granular season
    # + weather condition. Both must survive the store exactly — losing `precision` would
    # silently narrow "Mai–September" to 1 May – 1 September.
    season = OperatingSeason(window=AnnualWindow.whole_months(5, 9), weather=Weather.FAIR_ONLY)
    seasoned = replace(facilities[1], operating_season=season)
    dumped = codec.dumps(seasoned)
    assert '"operating_season"' in dumped
    back = codec.loads(dumped)
    assert back == seasoned
    assert back.operating_season == season
    assert back.operating_season is not None
    assert back.operating_season.window.precision is DatePrecision.MONTH
    assert back.operating_season.weather is Weather.FAIR_ONLY


def test_a_pre_slice_blob_without_the_key_loads_with_no_season(
    facilities: tuple[Facility, ...],
) -> None:
    # A gold blob written before this slice has no `operating_season` key at all; it must
    # load as the honest None (and re-dump byte-identically, per the pop above).
    blob = json.loads(codec.dumps(facilities[1]))
    assert "operating_season" not in blob
    assert codec.loads(json.dumps(blob)).operating_season is None


def test_a_fair_weather_exception_session_round_trips(
    facilities: tuple[Facility, ...],
) -> None:
    base = facilities[0]
    basin = base.basins[0]
    exception = ScheduleException(
        date=date(2026, 5, 1),
        reason="Gala",
        sessions=(
            ResolvedSession(TimeRange(time(14), time(21)), PublicSwim(), weather=Weather.FAIR_ONLY),
        ),
    )
    facility = replace(base, basins=(replace(basin, exceptions=(exception,)), *base.basins[1:]))

    dumped = codec.dumps(facility)
    assert '"weather":"fair_only"' in dumped
    assert codec.loads(dumped) == facility
