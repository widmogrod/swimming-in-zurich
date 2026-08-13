"""`compose` folds curated + scraped aspects per pool with declarative curated-wins precedence.

The load-bearing case (which the deleted ``drop_curated_duplicates`` filter got wrong): a
curated pool keeps its curated schedule AND gains a scraped price — a *per-aspect* merge, not a
whole-row drop.

Fixture note: the real ``data/pools/city.yaml`` carries curated prices, so to exercise the
"gains a scraped price" merge these tests build a price-less curated City. That isolates the
aspect-merge mechanism the plan's acceptance names; the store-level behaviour is covered
end-to-end in ``tests/test_cli.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from swimzh.build.compose import ScrapedAspects, _carry_bindings, carry_lane_plans, compose
from swimzh.domain.access import PublicSwim
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import LanePlan, PlanConfidence, PlanCoverage
from swimzh.domain.lockers import LockerCategory, LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Dimensions,
    Facility,
    Feature,
    FeatureKind,
    LanePlanSource,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.rentals import Gratis, Priced, RentalItem, RentalKind
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday

FETCHED = datetime(2026, 7, 19, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))
CITY = PoolId("hallenbad-city")

_CURATED_RULE = ScheduleRule(
    weekdays=frozenset({Weekday.MONDAY}),
    time=TimeRange(start=time(11, 0), end=time(22, 0)),
    access=PublicSwim(),
)


#: Module-level singleton default (`Unknown` is frozen and value-equal, so sharing is safe).
_UNKNOWN = Unknown()


def _curated_city(*, admission: Admission = _UNKNOWN) -> Facility:
    return Facility(
        identity=PoolIdentity(PoolId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="Sihlstrasse 71",
        provenance=Provenance(source="curated", curated=True, valid_as_of=date(2026, 7, 18)),
        basins=(Basin(basin_id=BasinId("city-50m"), name="50m-Becken", rules=(_CURATED_RULE,)),),
        admission=admission,
    )


def _scraped_city(*, admission: Admission = _UNKNOWN) -> ScrapedAspects:
    scraped_rule = ScheduleRule(
        weekdays=frozenset({Weekday.SATURDAY}),
        time=TimeRange(start=time(8, 0), end=time(20, 0)),
        access=PublicSwim(),
    )
    return ScrapedAspects(
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 71",
        geo=GeoPoint(lat=47.37, lon=8.53),
        basins=(
            Basin(
                basin_id=BasinId("hallenbad-city-main"), name="Hauptbecken", rules=(scraped_rule,)
            ),
        ),
        closures=(),
        notices=(),
        admission=admission,
        fetched_at=FETCHED,
    )


def _price(amount: str) -> PriceTable:
    return PriceTable(
        entries=(PriceEntry(PriceCategory.ADULT, Decimal(amount), f"Erwachsene CHF {amount}"),),
        valid_as_of=FETCHED.date(),
        source_url="https://example.test/prices",
    )


def test_curated_keeps_schedule_and_gains_scraped_price() -> None:
    scraped_price = _price("8.00")
    result = compose(
        (_curated_city(),),  # curated has a schedule but NO admission fact (Unknown)
        ((CITY, _scraped_city(admission=Tariff(scraped_price))),),
    )
    assert len(result.facilities) == 1
    merged = result.facilities[0]

    # Curated schedule kept (curated-wins on basins), the scraped basin discarded.
    assert {b.basin_id for b in merged.basins} == {BasinId("city-50m")}
    assert merged.basins[0].rules == (_CURATED_RULE,)
    # ...and the pool GAINED the scraped tariff the curated data lacked (the merge the old
    # whole-row filter dropped). `Unknown` is the admission zero object — it never wins a merge.
    assert merged.admission == Tariff(scraped_price)
    # Identity stays canonical; the merged facility remains the curated (facility-level) row.
    assert merged.identity.facility_id == PoolId("hallenbad-city")
    assert merged.provenance.curated is True


def test_curated_price_wins_when_both_sources_supply_it() -> None:
    result = compose(
        (_curated_city(admission=Tariff(_price("8.00"))),),
        ((CITY, _scraped_city(admission=Tariff(_price("9.50")))),),
    )
    merged = result.facilities[0]
    assert merged.admission == Tariff(_price("8.00"))  # curated-wins
    # A build note records that both sources supplied the admission aspect.
    assert any("admission" in note and "curated" in note for note in result.notes)


def test_a_scraped_free_fact_fills_a_curated_unknown() -> None:
    # `Free` is a supplied FACT (unlike the `Unknown` zero object), so a curated pool that states
    # nothing about admission gains it — exactly as it gains a scraped tariff.
    result = compose((_curated_city(),), ((CITY, _scraped_city(admission=Free())),))
    assert result.facilities[0].admission == Free()


def test_scraped_only_pool_passes_through() -> None:
    # An uncurated pool (no curated counterpart) keeps its scraped schedule + price.
    scraped = _scraped_city(admission=Tariff(_price("8.00")))
    result = compose((), ((CITY, scraped),))
    assert len(result.facilities) == 1
    merged = result.facilities[0]
    assert merged.identity.facility_id == PoolId("hallenbad-city")
    assert merged.basins[0].rules == scraped.basins[0].rules
    assert merged.admission == Tariff(_price("8.00"))
    assert merged.provenance.curated is False


def test_scraped_features_and_lockers_survive_compose_onto_non_curated_base() -> None:
    # Slice F acceptance: the widened ScrapedAspects (features/lockers) folds through
    # compose onto a scraped-only (non-curated) base.
    sauna = Feature(kind=FeatureKind.SAUNA, name="Sauna", surcharge_chf=Decimal("10.00"))
    locker = LockerOption(category=LockerCategory.VALUABLES, fee_chf=Decimal("2.00"))
    scraped = replace(
        _scraped_city(),
        features=(sauna,),
        lockers=(locker,),
    )
    result = compose((), ((CITY, scraped),))
    merged = result.facilities[0]
    assert merged.features == (sauna,)
    assert merged.lockers == (locker,)


def test_scraped_rentals_survive_compose_onto_non_curated_base() -> None:
    # mietobjekt-extraction S2: the rentals aspect folds through compose exactly like its
    # lockers sibling — including the fee union's stated-gratis arm, untouched by the merge.
    towel = RentalItem(kind=RentalKind.TOWEL, fee=Priced(Decimal("3.00")))
    lounger = RentalItem(kind=RentalKind.SUNLOUNGER, fee=Gratis(), deposit_chf=Decimal("2.00"))
    scraped = replace(_scraped_city(), rentals=(towel, lounger))
    result = compose((), ((CITY, scraped),))
    merged = result.facilities[0]
    assert merged.rentals == (towel, lounger)


def _stripped_curated_city() -> Facility:
    """A post-strip curated City: a schedule-less binding basin (only `lane_plan_source`), the shape
    `data/pools/city.yaml` reduces to once the curated schedule is deleted."""
    return Facility(
        identity=PoolIdentity(PoolId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="Sihlstrasse 71",
        provenance=Provenance(source="curated", curated=True),
        basins=(
            Basin(
                basin_id=BasinId("city-50m"),
                name="Schwimmerbecken",
                rules=(),
                lane_plan_source=LanePlanSource(url="https://example.test/city-schwimmer.pdf"),
            ),
        ),
    )


def test_scraped_schedule_carries_curated_lane_binding() -> None:
    # S3 crux: once the curated schedule is stripped, the scraped basin wins the timetable — but the
    # curated basin's `lane_plan_source` (the thin-crosswalk binding) must be CARRIED, not replaced
    # away, or `_attach_lanes` would abort on `attached == 0`.
    result = compose(
        (_stripped_curated_city(),),
        ((CITY, _scraped_city()),),
    )
    merged = result.facilities[0]
    # The scraped timetable is present...
    scraped_basin = next(b for b in merged.basins if b.basin_id == BasinId("hallenbad-city-main"))
    assert scraped_basin.rules  # the scraped schedule survived
    # ...AND the curated lane binding survived alongside it.
    lane_basin = next(b for b in merged.basins if b.basin_id == BasinId("city-50m"))
    assert lane_basin.lane_plan_source == LanePlanSource(
        url="https://example.test/city-schwimmer.pdf"
    )
    # A build note records the binding-carry.
    assert any("curated lane binding" in note for note in result.notes)
    # lane-stack-board S1: the carried basin also INHERITS the scraped timetable, so it clears
    # `query.py`'s Decision-#5 gate (`if not basin.rules: continue`) and produces its own session.
    assert lane_basin.rules == scraped_basin.rules
    # S4 honest provenance: the schedule came from the SCRAPER, so the composed facility must NOT
    # read as hand-verified even though a (thin-crosswalk) curated blob is its base. `curated` flips
    # to False and `source`/`valid_as_of` name the scrape — freshness stays the primary signal, but
    # the boolean no longer lies.
    assert merged.provenance.curated is False
    assert merged.provenance.source == "schedule_scraper"
    assert merged.provenance.valid_as_of == FETCHED.date()


def test_scraped_basin_url_already_declared_is_not_duplicated() -> None:
    # Defensive: if a scraped basin already carries the curated binding's URL, the curated basin is
    # not appended (no duplicate binding); the scraped basin wins.
    url = "https://example.test/city-schwimmer.pdf"
    scraped = replace(
        _scraped_city(),
        basins=(
            Basin(
                basin_id=BasinId("hallenbad-city-main"),
                name="Hauptbecken",
                rules=_scraped_city().basins[0].rules,
                lane_plan_source=LanePlanSource(url=url),
            ),
        ),
    )
    result = compose((_stripped_curated_city(),), ((CITY, scraped),))
    merged = result.facilities[0]
    assert [b.basin_id for b in merged.basins] == [BasinId("hallenbad-city-main")]


def _binding_basin() -> Basin:
    """A carried lane basin as the build really shapes it: the crosswalk `lane_plan_source` plus the
    WFS-sourced physicals `apply_physicals` populated, and NO rules of its own."""
    return Basin(
        basin_id=BasinId("city-50m"),
        name="Schwimmerbecken",
        rules=(),
        kind=BasinKind.LAP,
        dimensions=Dimensions(length_m=Decimal("50"), width_m=Decimal("15")),
        lanes=6,
        lane_plan_source=LanePlanSource(url="https://example.test/city-schwimmer.pdf"),
    )


def test_carried_lane_basin_inherits_the_scraped_timetable_and_keeps_its_identity() -> None:
    # lane-stack-board S1 / I2: only `rules` is added. `basin_id`, `name`, `lanes`, `dimensions`
    # and `lane_plan_source` are the carried basin's own — identity is never merged or overwritten.
    scraped = _scraped_city().basins
    binding = _binding_basin()

    merged = _carry_bindings(scraped, (binding,))

    assert merged[: len(scraped)] == scraped
    carried = merged[len(scraped)]
    assert carried.rules == scraped[0].rules
    assert replace(carried, rules=()) == binding


def test_carried_lane_basin_without_a_scraped_timetable_keeps_no_rules() -> None:
    # I1's other half: no scraped timetable => nothing to inherit. The binding is carried exactly as
    # before — no rules, so no session and no `/swim` option is invented for it.
    binding = _binding_basin()

    merged = _carry_bindings((), (binding,))

    assert merged == (binding,)


def test_two_rules_bearing_scraped_basins_fail_the_build() -> None:
    # I1: the timetable to inherit is "the single scraped basin bearing rules" — `etl/scrape` emits
    # exactly one synthetic `Hauptbecken` per facility. Should that ever stop holding, the build
    # fails loudly instead of silently picking a winner rule.
    scraped = _scraped_city().basins
    second = replace(scraped[0], basin_id=BasinId("hallenbad-city-second"), name="Lehrbecken")

    with pytest.raises(ValueError, match="ambiguous"):
        _carry_bindings((*scraped, second), (_binding_basin(),))


def test_output_is_ordered_by_canonical_id() -> None:
    other = ScrapedAspects(
        name="Hallenbad Oerlikon",
        kind=PoolKind.INDOOR,
        address="",
        geo=None,
        basins=(),
        closures=(),
        notices=(),
        admission=Unknown(),
        fetched_at=FETCHED,
    )
    result = compose(
        (),
        ((PoolId("hallenbad-oerlikon"), other), (CITY, _scraped_city())),
    )
    ids = [str(f.identity.facility_id) for f in result.facilities]
    assert ids == sorted(ids) == ["hallenbad-city", "hallenbad-oerlikon"]


# ── carry_lane_plans: the LANE tier crossing a curated rebuild ──────────────────────────────────
#
# A `scrape-gold` re-layer rebuilds the curated tier from `data/`, which carries each basin's
# `lane_plan_source` BINDING but no fetched `lane_plan` (the lane phase is a separate command). The
# plans a previous `scrape-lanes` attached are carried across that rebuild, or a successful re-layer
# would silently delete them.


def _plan(lane_count: int) -> LanePlan:
    return LanePlan(
        lane_count=lane_count,
        reservations=(),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(confidence=PlanConfidence.COMPLETE, cells_total=0, cells_resolved=0),
    )


def _stored_city_with_plan(plan: LanePlan) -> Facility:
    """The store as a previous `build` + `scrape-lanes` left it: the binding basin, plan on it."""
    curated = _stripped_curated_city()
    return replace(curated, basins=(replace(curated.basins[0], lane_plan=plan),))


def test_a_rebuilt_curated_tier_regains_the_lane_plan_the_store_holds() -> None:
    plan = _plan(6)
    carried = carry_lane_plans((_stripped_curated_city(),), (_stored_city_with_plan(plan),))
    # The PLAN itself crosses, not merely "a plan": a carry that attached some other sheet's
    # LanePlan to the right basin would satisfy a "is not None" assertion.
    assert [b.lane_plan for b in carried[0].basins] == [plan]
    # …and nothing else about the basin moved (I2: identity is never merged).
    assert (
        carried[0].basins[0].lane_plan_source == _stripped_curated_city().basins[0].lane_plan_source
    )


def test_a_repointed_binding_does_not_inherit_the_old_sheets_plan() -> None:
    # `LanePlanSource` IS the join key a plan was bound on. Re-point a basin's sheet in `data/` and
    # the stored plan — parsed from the OLD sheet — must NOT ride across onto the new binding: that
    # is the mis-attach the URL-keyed join exists to prevent. The basin waits for `scrape-lanes`.
    curated = _stripped_curated_city()
    repointed = replace(
        curated,
        basins=(
            replace(
                curated.basins[0],
                lane_plan_source=LanePlanSource(url="https://example.test/city-NEW-sheet.pdf"),
            ),
        ),
    )
    carried = carry_lane_plans((repointed,), (_stored_city_with_plan(_plan(6)),))
    assert carried[0].basins[0].lane_plan is None
    assert carried == (repointed,)  # untouched, not merely plan-less


def test_a_section_token_change_is_also_a_different_binding() -> None:
    # The `section` token routes one sub-grid of a STACKED multi-basin sheet, so two basins can
    # share a url and differ only there — it belongs in the key just as much as the url does.
    curated = _stripped_curated_city()
    url = str(curated.basins[0].lane_plan_source and curated.basins[0].lane_plan_source.url)
    sectioned = replace(
        curated,
        basins=(
            replace(
                curated.basins[0],
                lane_plan_source=LanePlanSource(url=url, section="sprungbecken"),
            ),
        ),
    )
    carried = carry_lane_plans((sectioned,), (_stored_city_with_plan(_plan(6)),))
    assert carried[0].basins[0].lane_plan is None


def test_a_basin_that_already_carries_a_plan_is_never_overwritten() -> None:
    fresh, stale = _plan(8), _plan(6)
    carried = carry_lane_plans((_stored_city_with_plan(fresh),), (_stored_city_with_plan(stale),))
    assert [b.lane_plan for b in carried[0].basins] == [fresh]
