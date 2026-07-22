"""Silver lane-plan reconciliation: a deterministic URL-keyed inner join (no fuzzy matching),
with extraction failures recorded as first-class `LanePlanUnavailable` state."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.errors import HttpStatus, ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok
from swimzh.domain.lane_plan import LanePlan, PlanConfidence, PlanCoverage
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    LanePlanSource,
    LanePlanUnavailable,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.etl.silver import (
    BoundPlan,
    _Binding,
    attach_lane_plans,
    bind_plans,
    build_url_bindings,
    index_bound_plans,
)
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


def _parsed(
    source_url: str, basin_hint: str = "anything", valid_from: date | None = None
) -> ParsedPlan:
    return ParsedPlan(basin_hint=basin_hint, plan=_plan(valid_from), source_url=source_url)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def _declared(dataset: Dataset) -> dict[tuple[str, str], str]:
    """(pool_id, basin_id) -> declared lane_plan_source.url for every basin that declares one."""
    out: dict[tuple[str, str], str] = {}
    for facility in dataset.facilities:
        for basin in facility.basins:
            if basin.lane_plan_source is not None:
                out[(str(facility.identity.facility_id), str(basin.basin_id))] = (
                    basin.lane_plan_source.url
                )
    return out


def _url(dataset: Dataset, pool_id: str, basin_id: str) -> str:
    return _declared(dataset)[(pool_id, basin_id)]


# --- URL-keyed inner join (header-independence) --------------------------------------


def test_bungertwies_binds_by_url_despite_a_garbled_basin_hint(dataset: Dataset) -> None:
    # Acceptance: reconciliation is URL-origin, not title. A deliberately garbled `basin_hint`
    # (the Bungertwies sheet's header omits the basin word entirely) STILL binds by its URL.
    url = _url(dataset, "hallenbad-bungertwies", "bungertwies-25m")
    parsed = _parsed(url, basin_hint="!!! total gibberish header — not a facility name !!!")
    result = attach_lane_plans(dataset.facilities, [parsed], {}, FETCHED_AT)
    assert isinstance(result, Ok), result
    by_id = {f.identity.facility_id: f for f in result.value.facilities}
    basin = next(
        b
        for b in by_id[PoolId("hallenbad-bungertwies")].basins
        if b.basin_id == BasinId("bungertwies-25m")
    )
    assert isinstance(basin.lane_plan, LanePlan)
    assert basin.lane_plan.fetched_at == FETCHED_AT


def test_city_and_oerlikon_50m_still_attach(dataset: Dataset) -> None:
    parsed = [
        _parsed(_url(dataset, "hallenbad-city", "city-50m")),
        _parsed(_url(dataset, "hallenbad-oerlikon", "oerlikon-50m")),
    ]
    result = attach_lane_plans(dataset.facilities, parsed, {}, FETCHED_AT)
    assert isinstance(result, Ok)
    by_id = {f.identity.facility_id: f for f in result.value.facilities}
    city_lap = next(
        b for b in by_id[PoolId("hallenbad-city")].basins if b.basin_id == BasinId("city-50m")
    )
    oerlikon_lap = next(
        b
        for b in by_id[PoolId("hallenbad-oerlikon")].basins
        if b.basin_id == BasinId("oerlikon-50m")
    )
    assert isinstance(city_lap.lane_plan, LanePlan)
    assert isinstance(oerlikon_lap.lane_plan, LanePlan)
    # The un-declared Oerlikon Sprungbecken is untouched (its stacked sheet is S2).
    sprung = next(
        b
        for b in by_id[PoolId("hallenbad-oerlikon")].basins
        if b.basin_id == BasinId("oerlikon-sprungbecken")
    )
    assert sprung.lane_plan is None


def test_leimbach_blaesi_kaeferberg_now_attach(dataset: Dataset) -> None:
    # These pools were unmatched under the old fuzzy matcher; their lane-plan-only basins now
    # attach by URL.
    targets = [
        ("hallenbad-leimbach", "leimbach-25m"),
        ("hallenbad-blaesi", "blaesi-25m"),
        ("waermebad-kaeferberg", "kaeferberg-mehrzweckbecken"),
    ]
    parsed = [_parsed(_url(dataset, pid, bid)) for pid, bid in targets]
    result = attach_lane_plans(dataset.facilities, parsed, {}, FETCHED_AT)
    assert isinstance(result, Ok)
    by_id = {str(f.identity.facility_id): f for f in result.value.facilities}
    for pid, bid in targets:
        basin = next(b for b in by_id[pid].basins if str(b.basin_id) == bid)
        assert isinstance(basin.lane_plan, LanePlan), (pid, bid)


def test_golden_set_pins_the_exact_bound_set(dataset: Dataset) -> None:
    # Feed one parsed plan per declared source; the bound set is EXACTLY the declared basins.
    declared = _declared(dataset)
    parsed = [_parsed(url) for url in declared.values()]
    result = attach_lane_plans(dataset.facilities, parsed, {}, FETCHED_AT)
    assert isinstance(result, Ok)
    bound = {
        (str(f.identity.facility_id), str(b.basin_id))
        for f in result.value.facilities
        for b in f.basins
        if isinstance(b.lane_plan, LanePlan)
    }
    assert bound == {
        ("hallenbad-city", "city-50m"),
        ("hallenbad-oerlikon", "oerlikon-50m"),
        ("hallenbad-bungertwies", "bungertwies-25m"),
        ("hallenbad-leimbach", "leimbach-25m"),
        ("hallenbad-blaesi", "blaesi-25m"),
        ("waermebad-kaeferberg", "kaeferberg-mehrzweckbecken"),
    }


# --- extraction failure recorded as first-class state (scoped-failure) ---------------


def test_failed_source_records_lane_plan_unavailable_and_facility_still_builds(
    dataset: Dataset,
) -> None:
    # Acceptance: a declared source whose fetch/parse FAILED stamps LanePlanUnavailable carrying
    # the EXACT ProviderError cause — and the failure is scoped to that basin's lane_plan; the
    # facility, its schedule, and its other basins are untouched.
    url = _url(dataset, "hallenbad-city", "city-50m")
    cause: ProviderError = HttpStatus(url=url, status=503, body_snippet="down")
    result = attach_lane_plans(dataset.facilities, [], {url: cause}, FETCHED_AT)
    assert isinstance(result, Ok)
    city = next(
        f for f in result.value.facilities if str(f.identity.facility_id) == "hallenbad-city"
    )
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlanUnavailable)
    assert lap.lane_plan.cause == cause  # the real typed cause, losslessly
    assert lap.lane_plan.observed_at == FETCHED_AT
    # Scoped failure: the schedule survives, and the sibling teaching basin is unaffected.
    assert any(b.rules for b in city.basins)
    teaching = next(b for b in city.basins if b.basin_id == BasinId("city-lehrbecken"))
    assert teaching.lane_plan is None


# --- loud failures -------------------------------------------------------------------


def _basin(basin_id: str, url: str, section: str | None = None) -> Basin:
    return Basin(
        basin_id=BasinId(basin_id),
        name=basin_id,
        rules=(),
        kind=BasinKind.LAP,
        lane_plan_source=LanePlanSource(url=url, section=section),
    )


def _facility(pool_id: str, basins: tuple[Basin, ...]) -> Facility:
    return Facility(
        identity=PoolIdentity(facility_id=PoolId(pool_id), name=pool_id, kind=PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="test", curated=True, valid_as_of=date(2026, 1, 1)),
        basins=basins,
    )


def test_duplicate_url_section_binding_is_a_fatal_named_err() -> None:
    # Two basins claiming the SAME (url, section) makes routing ambiguous -> fatal, named.
    url = "https://example.test/dup.pdf"
    facilities = [
        _facility("p", (_basin("p-a", url), _basin("p-b", url))),
    ]
    result = build_url_bindings(facilities)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "duplicate lane_plan_source binding" in result.error.detail
    assert url in result.error.detail
    # attach_lane_plans surfaces the same fatal error.
    assert isinstance(attach_lane_plans(facilities, [], {}, FETCHED_AT), Err)


def test_single_basin_source_split_into_many_is_count_guarded_to_unbound() -> None:
    # A single-basin binding that receives several parsed sections (a sheet that split) is never
    # positionally misbound: the structural count-guard leaves every fragment unbound.
    url = "https://example.test/one.pdf"
    facilities = [_facility("p", (_basin("p-a", url),))]
    result = attach_lane_plans(facilities, [_parsed(url), _parsed(url)], {}, FETCHED_AT)
    assert isinstance(result, Ok)
    assert all(b.lane_plan is None for f in result.value.facilities for b in f.basins)
    assert len(result.value.unbound) == 2
    assert all("split into 2" in u.reason for u in result.value.unbound)


def test_bind_plans_defers_stacked_multi_binding_urls_to_unbound() -> None:
    # A URL with N section-bindings (a stacked sheet) is NOT routed in S1 (section routing is S2):
    # the plans surface as unbound with a deferral reason, never a guessed positional bind.
    url = "https://example.test/stacked.pdf"
    bindings = {
        url: (
            _Binding(PoolId("p"), BasinId("p-a"), "nichtschwimmer"),
            _Binding(PoolId("p"), BasinId("p-b"), "sprungbecken"),
        )
    }
    bound, unbound = bind_plans([_parsed(url, basin_hint="Sprungbecken")], bindings)
    assert bound == ()
    assert len(unbound) == 1 and "stacked" in unbound[0].reason


def test_two_bound_plans_on_one_basin_is_a_fatal_err() -> None:
    # The structural guard behind attach: two plans bound to one basin never silently overwrite —
    # it is a fatal, named `Err`. (Unreachable via the single-basin URL join, so exercised on the
    # extracted indexer directly; it becomes reachable under S2 stacked routing.)
    collision = (
        BoundPlan(PoolId("p"), BasinId("p-a"), _plan(None)),
        BoundPlan(PoolId("p"), BasinId("p-a"), _plan(None)),
    )
    result = index_bound_plans(collision)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "two lane plans bound to one basin" in result.error.detail


# --- unbound + staleness (non-fatal reporting) --------------------------------------


def test_url_no_basin_claims_is_reported_unbound_not_fatal(dataset: Dataset) -> None:
    parsed = _parsed("https://example.test/nobody-claims-this.pdf", basin_hint="Orphan")
    result = attach_lane_plans(dataset.facilities, [parsed], {}, FETCHED_AT)
    assert isinstance(result, Ok)
    assert all(
        not isinstance(b.lane_plan, LanePlan) for f in result.value.facilities for b in f.basins
    )
    assert len(result.value.unbound) == 1
    assert result.value.unbound[0].source_url == "https://example.test/nobody-claims-this.pdf"


def test_staleness_warning_when_plan_predates_schedule(dataset: Dataset) -> None:
    # City schedule valid_as_of is 2026-07-18; a Jan plan predates it -> staleness warning.
    url = _url(dataset, "hallenbad-city", "city-50m")
    parsed = _parsed(url, valid_from=date(2026, 1, 1))
    result = attach_lane_plans(dataset.facilities, [parsed], {}, FETCHED_AT)
    assert isinstance(result, Ok)
    assert any("predates schedule valid_as_of" in w for w in result.value.warnings)
