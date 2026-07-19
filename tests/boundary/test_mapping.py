"""Feature/locker DTO<->domain mapping.

The locker cost axes are orthogonal on purpose: the three real pool-page row shapes
(free usage + deposit / fee + rental period / fee + deposit) must each map losslessly.
The token-table parity tests close the silent-gap trap: a new enum member missing from
a hand-written `_X_TO` table would otherwise only fail at runtime on first use.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import (
    AdultsOnlyDTO,
    ClubReservedDTO,
    FeatureDTO,
    LanePlanDTO,
    LaneReservationDTO,
    LockerOptionDTO,
    PlanCoverageDTO,
    PublicDTO,
    RuleDTO,
)
from swimzh.domain.access import AdultsOnly, ClubReserved, PublicSwim
from swimzh.domain.lane_plan import LaneReservation, PlanConfidence
from swimzh.domain.lockers import LockerCategory, LockerMechanism
from swimzh.domain.models import BasinKind, BasinSource, FeatureKind
from swimzh.domain.schedule import DayScope, TimeRange, Weekday

# --- the three real locker-row shapes ----------------------------------------------


def test_locker_free_usage_plus_refundable_deposit() -> None:
    dto = LockerOptionDTO(
        category="wardrobe",
        deposit_chf=Decimal("5.00"),
        raw="Garderobenkasten gratis, plus Depot Fr. 5.–",
    )
    locker = mapping.locker_from_dto(dto)
    assert locker.category is LockerCategory.WARDROBE
    assert locker.fee_chf is None  # free to use ...
    assert locker.deposit_chf == Decimal("5.00")  # ... but a refundable Pfand
    assert locker.period is None
    assert locker.mechanism is None  # unstated on the page
    assert mapping.locker_to_dto(locker) == dto


def test_locker_fee_plus_rental_period() -> None:
    dto = LockerOptionDTO(
        category="laundry",
        fee_chf=Decimal("400.00"),
        period="1 Jahr",
        raw="Wäschefach (1 Jahr) Fr. 400.–",
    )
    locker = mapping.locker_from_dto(dto)
    assert locker.category is LockerCategory.LAUNDRY
    assert locker.fee_chf == Decimal("400.00")
    assert locker.deposit_chf is None
    assert locker.period == "1 Jahr"
    assert mapping.locker_to_dto(locker) == dto


def test_locker_fee_plus_deposit() -> None:
    dto = LockerOptionDTO(
        category="valuables",
        fee_chf=Decimal("3.00"),
        deposit_chf=Decimal("20.00"),
        mechanism="key",
        raw="Badetuch Fr. 3.–, plus Depot Fr. 20.–",
    )
    locker = mapping.locker_from_dto(dto)
    assert locker.fee_chf == Decimal("3.00")  # a fee AND a deposit co-occur —
    assert locker.deposit_chf == Decimal("20.00")  # exactly why this is not a tagged union
    assert locker.mechanism is LockerMechanism.KEY
    assert locker.raw == "Badetuch Fr. 3.–, plus Depot Fr. 20.–"
    assert mapping.locker_to_dto(locker) == dto


# --- features ----------------------------------------------------------------------


def test_feature_maps_hours_as_schedule_rules() -> None:
    dto = FeatureDTO(
        kind="sauna",
        name="Gemischte Sauna",
        hours=[
            RuleDTO(
                weekdays=["mon", "sun"],
                start=time(8, 0),
                end=time(22, 0),
                access=PublicDTO(type="public"),
            )
        ],
        surcharge_chf=Decimal("10.00"),
        temp_c=Decimal("85"),
        note="gemischt",
    )
    feature = mapping.feature_from_dto(dto)
    assert feature.kind is FeatureKind.SAUNA
    assert len(feature.hours) == 1
    rule = feature.hours[0]
    assert rule.weekdays == frozenset({Weekday.MONDAY, Weekday.SUNDAY})
    assert rule.scope is DayScope.ALWAYS
    assert feature.surcharge_chf == Decimal("10.00")
    assert feature.temp_c == Decimal("85")
    assert mapping.feature_to_dto(feature) == dto


# --- access ------------------------------------------------------------------------


def test_adults_only_access_round_trips() -> None:
    dto = AdultsOnlyDTO(type="adults_only", min_age=18, note="Erwachsenenschwimmen")
    access = mapping.access_from_dto(dto)
    assert access == AdultsOnly(min_age=18, note="Erwachsenenschwimmen")
    assert mapping.access_to_dto(access) == dto


# --- lane reservations (Belegungsplan) ----------------------------------------------


def test_lane_reservation_round_trips_with_sorted_frozensets() -> None:
    # A DTO whose weekdays/lanes are given out of order must map to a domain frozenset and
    # serialise back *sorted* — the exact round-trip the codec test relies on.
    dto = LaneReservationDTO(
        weekdays=["wed", "mon"],
        start=time(6, 0),
        end=time(8, 0),
        lanes=[2, 1],
        access=ClubReservedDTO(type="club_reserved", club="ASVZ"),
    )
    reservation = mapping.lane_reservation_from_dto(dto)
    assert reservation.weekdays == frozenset({Weekday.MONDAY, Weekday.WEDNESDAY})
    assert reservation.lanes == frozenset({1, 2})
    assert reservation.access == ClubReserved(club="ASVZ")
    round_tripped = mapping.lane_reservation_to_dto(reservation)
    assert round_tripped == LaneReservationDTO(
        weekdays=["mon", "wed"],  # sorted, regardless of input order
        start=time(6, 0),
        end=time(8, 0),
        lanes=[1, 2],  # sorted
        access=ClubReservedDTO(type="club_reserved", club="ASVZ"),
    )


def test_lane_plan_round_trips_with_coverage() -> None:
    dto = LanePlanDTO(
        lane_count=6,
        reservations=[
            LaneReservationDTO(
                weekdays=["tue"],
                start=time(6, 0),
                end=time(8, 0),
                lanes=[3, 4, 5, 6],
                access=PublicDTO(type="public"),
            )
        ],
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverageDTO(
            confidence="partial",
            cells_total=1344,
            cells_resolved=1300,
            unresolved_lanes=[5, 1],
        ),
    )
    plan = mapping.lane_plan_from_dto(dto)
    assert plan.lane_count == 6
    assert plan.valid_from == date(2026, 1, 1)
    assert plan.coverage.confidence is PlanConfidence.PARTIAL
    assert plan.coverage.unresolved_lanes == frozenset({1, 5})
    assert plan.reservations[0] == LaneReservation(
        weekdays=frozenset({Weekday.TUESDAY}),
        time=TimeRange(time(6, 0), time(8, 0)),
        lanes=frozenset({3, 4, 5, 6}),
        access=PublicSwim(),
    )
    back = mapping.lane_plan_to_dto(plan)
    assert back.coverage.unresolved_lanes == [1, 5]  # sorted, regardless of input order
    # Everything else survives the round trip unchanged.
    assert back.model_copy(update={"coverage": dto.coverage}) == dto


# --- token-table parity (no enum member silently unmapped) --------------------------


def test_token_tables_cover_their_enums() -> None:
    assert set(mapping._FEATURE_KIND_TO) == set(FeatureKind)
    assert set(mapping._LOCKER_CATEGORY_TO) == set(LockerCategory)
    assert set(mapping._LOCKER_MECHANISM_TO) == set(LockerMechanism)
    assert set(mapping._BASIN_KIND_TO) == set(BasinKind)
    assert set(mapping._BASIN_SOURCE_TO) == set(BasinSource)
    assert set(mapping._PLAN_CONFIDENCE_TO) == set(PlanConfidence)
