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

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from swimzh.build.compose import ScrapedAspects, compose
from swimzh.build.reconcile import PoolId
from swimzh.domain.access import PublicSwim
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday

FETCHED = datetime(2026, 7, 19, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))
CITY = PoolId("hallenbad-city")

_CURATED_RULE = ScheduleRule(
    weekdays=frozenset({Weekday.MONDAY}),
    time=TimeRange(start=time(11, 0), end=time(22, 0)),
    access=PublicSwim(),
)


def _curated_city(*, prices: PriceTable | None) -> Facility:
    return Facility(
        identity=PoolIdentity(FacilityId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="Sihlstrasse 71",
        provenance=Provenance(source="curated", curated=True, valid_as_of=date(2026, 7, 18)),
        basins=(Basin(basin_id=BasinId("city-50m"), name="50m-Becken", rules=(_CURATED_RULE,)),),
        prices=prices,
    )


def _scraped_city(*, prices: PriceTable | None) -> ScrapedAspects:
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
        prices=prices,
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
        (_curated_city(prices=None),),  # curated has a schedule but NO price
        ((CITY, _scraped_city(prices=scraped_price)),),
    )
    assert len(result.facilities) == 1
    merged = result.facilities[0]

    # Curated schedule kept (curated-wins on basins), the scraped basin discarded.
    assert {b.basin_id for b in merged.basins} == {BasinId("city-50m")}
    assert merged.basins[0].rules == (_CURATED_RULE,)
    # ...and the pool GAINED the scraped price the curated data lacked (the merge the old
    # whole-row filter dropped).
    assert merged.prices == scraped_price
    # Identity stays canonical; the merged facility remains the curated (facility-level) row.
    assert merged.identity.facility_id == FacilityId("hallenbad-city")
    assert merged.provenance.curated is True


def test_curated_price_wins_when_both_sources_supply_it() -> None:
    result = compose(
        (_curated_city(prices=_price("8.00")),),
        ((CITY, _scraped_city(prices=_price("9.50"))),),
    )
    merged = result.facilities[0]
    assert merged.prices == _price("8.00")  # curated-wins
    # A build note records that both sources supplied the price aspect.
    assert any("prices" in note and "curated" in note for note in result.notes)


def test_scraped_only_pool_passes_through() -> None:
    # An uncurated pool (no curated counterpart) keeps its scraped schedule + price.
    scraped = _scraped_city(prices=_price("8.00"))
    result = compose((), ((CITY, scraped),))
    assert len(result.facilities) == 1
    merged = result.facilities[0]
    assert merged.identity.facility_id == FacilityId("hallenbad-city")
    assert merged.basins[0].rules == scraped.basins[0].rules
    assert merged.prices == _price("8.00")
    assert merged.provenance.curated is False


def test_output_is_ordered_by_canonical_id() -> None:
    other = ScrapedAspects(
        name="Hallenbad Oerlikon",
        kind=PoolKind.INDOOR,
        address="",
        geo=None,
        basins=(),
        closures=(),
        notices=(),
        prices=None,
        fetched_at=FETCHED,
    )
    result = compose(
        (),
        ((PoolId("hallenbad-oerlikon"), other), (CITY, _scraped_city(prices=None))),
    )
    ids = [str(f.identity.facility_id) for f in result.facilities]
    assert ids == sorted(ids) == ["hallenbad-city", "hallenbad-oerlikon"]
