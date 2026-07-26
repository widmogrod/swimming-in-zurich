"""Facility-detail query surface: the static "what does this pool offer?" answer.

Feature hours are ordinary `ScheduleRule`s resolved through the *existing* resolver, so
"is the sauna open now?" honours weekday/time, and facility-wide closures shut the sauna
during the Revision too — no separate feature resolver exists.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.result import Ok
from swimzh.domain.access import ClubReserved, PublicSwim
from swimzh.domain.closure import ClosureCode
from swimzh.domain.lane_plan import (
    LanePlan,
    LaneReservation,
    PlanConfidence,
    PlanCoverage,
    PublicWindow,
)
from swimzh.domain.lockers import LockerCategory
from swimzh.domain.models import Basin, Facility, FeatureKind
from swimzh.domain.query import facility_detail
from swimzh.domain.schedule import ClosedDay, OpenDay, TimeRange, Weekday
from swimzh.providers.curated import Dataset, load_dataset

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ZURICH = ZoneInfo("Europe/Zurich")


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


@pytest.fixture(scope="module")
def city(dataset: Dataset) -> Facility:
    return next(f for f in dataset.facilities if str(f.identity.facility_id) == "hallenbad-city")


def test_detail_surfaces_website_lockers_and_basins(dataset: Dataset, city: Facility) -> None:
    detail = facility_detail(city, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH), dataset.calendar)
    assert detail.facility_name == "Hallenbad City"
    assert detail.website is not None
    assert detail.website.endswith("/hallenbaeder/city.html")
    assert detail.basins == city.basins  # per-basin physicals ride along unmodified

    by_category = {lo.category: lo for lo in detail.lockers}
    wardrobe = by_category[LockerCategory.WARDROBE]
    assert wardrobe.fee_chf is None  # free to use, deposit only
    assert wardrobe.deposit_chf == Decimal("5.00")
    laundry = by_category[LockerCategory.LAUNDRY]
    assert laundry.fee_chf == Decimal("400.00")
    assert laundry.period == "1 Jahr"
    assert laundry.raw.startswith("Wäschefach")


def test_sauna_open_now_via_existing_resolver(dataset: Dataset, city: Facility) -> None:
    # Tuesday 18:00 in term: the sauna (daily 08:00-22:00) is open.
    detail = facility_detail(city, datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH), dataset.calendar)
    sauna = next(fs for fs in detail.features if fs.feature.kind is FeatureKind.SAUNA)
    assert sauna.feature.surcharge_chf == Decimal("10.00")  # "Eintritt Fr. 10.-"
    assert isinstance(sauna.schedule, OpenDay)
    assert sauna.open_at_query_time is True


def test_sauna_closed_after_hours(dataset: Dataset, city: Facility) -> None:
    # Same Tuesday at 22:30: the day has sauna sessions, but none contains 22:30.
    detail = facility_detail(city, datetime(2026, 3, 10, 22, 30, tzinfo=ZURICH), dataset.calendar)
    sauna = next(fs for fs in detail.features if fs.feature.kind is FeatureKind.SAUNA)
    assert isinstance(sauna.schedule, OpenDay)
    assert sauna.open_at_query_time is False


def test_facility_closure_shuts_the_sauna_too(dataset: Dataset, city: Facility) -> None:
    # 2026-07-20 falls in City's "Sommerpause / Revision" closure: resolver reuse means
    # the sauna is closed for the same reason, not silently "open 08:00-22:00".
    detail = facility_detail(city, datetime(2026, 7, 20, 12, 0, tzinfo=ZURICH), dataset.calendar)
    sauna = next(fs for fs in detail.features if fs.feature.kind is FeatureKind.SAUNA)
    assert sauna.schedule == ClosedDay(code=ClosureCode.SEASONAL_BREAK_MAINTENANCE)
    # The curated German is CLASSIFIED at build time (S4), so the sauna's closure carries
    # a machine identity — not just prose the UI would have to print verbatim.
    assert sauna.schedule.code is ClosureCode.SEASONAL_BREAK_MAINTENANCE
    assert sauna.open_at_query_time is False


def _basin_with_plan(basin: Basin) -> Basin:
    """Give a basin a Tuesday lane plan: lanes 1–2 held by ASVZ, 3–6 public 06:00–08:00."""
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
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
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )
    return replace(basin, lane_plan=plan)


def test_detail_surfaces_a_lane_panel_for_basins_with_a_plan(
    dataset: Dataset, city: Facility
) -> None:
    # Attach a plan to City's first basin; the facility detail must derive its lane panel
    # for the queried weekday (a Tuesday). Basins without a plan contribute no panel.
    first, *rest = city.basins
    planned = replace(city, basins=(_basin_with_plan(first), *rest))
    # 2026-09-15 is a Tuesday.
    detail = facility_detail(planned, datetime(2026, 9, 15, 7, 0, tzinfo=ZURICH), dataset.calendar)
    assert len(detail.lane_panels) == 1  # only the one basin we gave a plan
    bp = detail.lane_panels[0]
    assert bp.basin_id == first.basin_id
    assert bp.panel.day_view.weekday == Weekday.TUESDAY
    assert bp.panel.best_public == PublicWindow(
        time=TimeRange(time(6, 0), time(8, 0)), public_lanes=4
    )
    assert [r.club for r in bp.panel.roster] == ["ASVZ"]  # public excluded from the roster


def test_detail_has_no_lane_panels_when_no_basin_has_a_plan(
    dataset: Dataset, city: Facility
) -> None:
    # The curated dataset carries no lane plans yet → an empty (never invented) panel list.
    detail = facility_detail(city, datetime(2026, 9, 15, 7, 0, tzinfo=ZURICH), dataset.calendar)
    assert detail.lane_panels == ()


def test_feature_without_stated_hours_is_unknown_not_closed(
    dataset: Dataset, city: Facility
) -> None:
    hourless = tuple(replace(f, hours=()) for f in city.features)
    detail = facility_detail(
        replace(city, features=hourless),
        datetime(2026, 3, 10, 18, 0, tzinfo=ZURICH),
        dataset.calendar,
    )
    sauna = next(fs for fs in detail.features if fs.feature.kind is FeatureKind.SAUNA)
    assert sauna.schedule is None
    assert sauna.open_at_query_time is None  # unknown — never conflated with closed
