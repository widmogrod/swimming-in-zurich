"""Feature/locker DTO<->domain mapping.

The locker cost axes are orthogonal on purpose: the three real pool-page row shapes
(free usage + deposit / fee + rental period / fee + deposit) must each map losslessly.
The token-table parity tests close the silent-gap trap: a new enum member missing from
a hand-written `_X_TO` table would otherwise only fail at runtime on first use.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import FeatureDTO, LockerOptionDTO, PublicDTO, RuleDTO
from swimzh.domain.lockers import LockerCategory, LockerMechanism
from swimzh.domain.models import BasinKind, BasinSource, FeatureKind
from swimzh.domain.schedule import DayScope, Weekday

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


# --- token-table parity (no enum member silently unmapped) --------------------------


def test_token_tables_cover_their_enums() -> None:
    assert set(mapping._FEATURE_KIND_TO) == set(FeatureKind)
    assert set(mapping._LOCKER_CATEGORY_TO) == set(LockerCategory)
    assert set(mapping._LOCKER_MECHANISM_TO) == set(LockerMechanism)
    assert set(mapping._BASIN_KIND_TO) == set(BasinKind)
    assert set(mapping._BASIN_SOURCE_TO) == set(BasinSource)
