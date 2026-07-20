"""Silver lane-plan reconciliation: basin-hint lookup with loud failure on ambiguity."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.errors import SchemaMismatch
from swimzh.core.result import Err, Ok
from swimzh.domain.lane_plan import LanePlan, PlanConfidence, PlanCoverage
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.etl.silver import attach_lane_plans
from swimzh.providers.belegungsplan import ParsedPlan
from swimzh.providers.curated import Dataset, load_dataset

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FETCHED_AT = datetime(2026, 7, 18, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))


def _plan(valid_from: date | None) -> LanePlan:
    return LanePlan(
        lane_count=6,
        reservations=(),
        valid_from=valid_from,
        coverage=PlanCoverage(PlanConfidence.COMPLETE, cells_total=0, cells_resolved=0),
        fetched_at=None,
    )


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


# --- basin-granular lane-plan reconciliation ----------------------------------------


def _facility(identity: PoolIdentity, basins: tuple[Basin, ...], valid_as_of: date) -> Facility:
    return Facility(
        identity=identity,
        address="",
        provenance=Provenance(source="test", curated=True, valid_as_of=valid_as_of),
        basins=basins,
    )


def test_attach_lane_plan_reconciles_hint_and_stamps_fetched_at(dataset: Dataset) -> None:
    # "Hallenbad City Schwimmerbecken" resolves to the City 50m (LAP) basin, not the
    # teaching basin, and the plan is stamped with the run's fetched_at.
    parsed = ParsedPlan(basin_hint="Hallenbad City Schwimmerbecken", plan=_plan(date(2026, 1, 1)))
    result = attach_lane_plans(dataset.facilities, [parsed], FETCHED_AT)
    assert isinstance(result, Ok), result

    by_id = {f.identity.facility_id: f for f in result.value.facilities}
    basins = {b.basin_id: b for b in by_id[PoolId("hallenbad-city")].basins}
    lap = basins[BasinId("city-50m")]
    assert lap.lane_plan is not None
    assert lap.lane_plan.lane_count == 6
    assert lap.lane_plan.fetched_at == FETCHED_AT
    # The teaching basin is untouched — no over-broad attachment.
    assert basins[BasinId("city-lehrbecken")].lane_plan is None


def test_attach_lane_plan_warns_when_plan_predates_schedule(dataset: Dataset) -> None:
    # City schedule valid_as_of is 2026-07-18; a Jan plan predates it -> staleness warning.
    parsed = ParsedPlan(basin_hint="Hallenbad City Schwimmerbecken", plan=_plan(date(2026, 1, 1)))
    result = attach_lane_plans(dataset.facilities, [parsed], FETCHED_AT)
    assert isinstance(result, Ok)
    assert any("predates schedule valid_as_of" in w for w in result.value.warnings)


def test_attach_lane_plan_no_warning_when_current(dataset: Dataset) -> None:
    parsed = ParsedPlan(basin_hint="Hallenbad City Schwimmerbecken", plan=_plan(date(2027, 1, 1)))
    result = attach_lane_plans(dataset.facilities, [parsed], FETCHED_AT)
    assert isinstance(result, Ok)
    assert result.value.warnings == ()


def test_attach_lane_plan_batch_attaches_matched_reports_unmatched(dataset: Dataset) -> None:
    # A real batch: one hint reconciles (City Schwimmerbecken → the lap basin), one does not.
    # The matched plan attaches; the unmatched hint is reported; the run does not abort.
    matched = ParsedPlan(basin_hint="Hallenbad City Schwimmerbecken", plan=_plan(None))
    unmatched = ParsedPlan(basin_hint="Hallenbad City Variobecken", plan=_plan(None))
    result = attach_lane_plans(dataset.facilities, [matched, unmatched], FETCHED_AT)
    assert isinstance(result, Ok)
    assert result.value.unmatched == ("Hallenbad City Variobecken",)
    attached = [b for f in result.value.facilities for b in f.basins if b.lane_plan is not None]
    assert len(attached) == 1 and attached[0].kind is BasinKind.LAP


def test_attach_lane_plan_unmatched_hint_is_reported_not_fatal(dataset: Dataset) -> None:
    # A hint matching NO curated basin (uncurated basin/pool) is reported in `unmatched`, not a
    # fatal error — a batch scrape should still attach the plans it can. (Ambiguous stays loud.)
    parsed = ParsedPlan(basin_hint="Hallenbad Nonexistent Schwimmerbecken", plan=_plan(None))
    result = attach_lane_plans(dataset.facilities, [parsed], FETCHED_AT)
    assert isinstance(result, Ok)
    assert result.value.unmatched == ("Hallenbad Nonexistent Schwimmerbecken",)
    # nothing attached
    assert all(b.lane_plan is None for f in result.value.facilities for b in f.basins)


def test_attach_lane_plan_ambiguous_hint_is_loud_failure() -> None:
    # Two lap basins in one facility both key to "…Schwimmerbecken" -> ambiguous, never guessed.
    identity = PoolIdentity(facility_id=PoolId("twin"), name="Twin Bad", kind=PoolKind.INDOOR)
    basins = (
        Basin(basin_id=BasinId("twin-a"), name="Becken A", rules=(), kind=BasinKind.LAP),
        Basin(basin_id=BasinId("twin-b"), name="Becken B", rules=(), kind=BasinKind.LAP),
    )
    facility = _facility(identity, basins, date(2026, 1, 1))
    parsed = ParsedPlan(basin_hint="Twin Bad Schwimmerbecken", plan=_plan(None))
    result = attach_lane_plans([facility], [parsed], FETCHED_AT)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "Twin Bad Schwimmerbecken" in result.error.detail
