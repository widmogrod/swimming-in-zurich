"""The /pools and /access-types endpoints over the committed catalog."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from fastapi.testclient import TestClient

from apps.web.api.pools.service import facility_detail_out
from apps.web.main import app
from swimzh.domain.access import PublicSwim
from swimzh.domain.lockers import LockerCategory, LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    BasinSource,
    Dimensions,
    Feature,
    FeatureKind,
    PoolId,
    Provenance,
)
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.query import FacilityDetail, FeatureStatus
from swimzh.domain.schedule import OpenDay, ResolvedSession, TimeRange


def test_pools_lists_all_categories() -> None:
    with TestClient(app) as client:
        response = client.get("/pools")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 50
    # every listed pool has an official link and a kind
    assert all(p["url"] for p in body["pools"])
    assert {"indoor", "outdoor", "lake"} <= set(body["kinds"])


def test_pools_filter_by_kind() -> None:
    with TestClient(app) as client:
        response = client.get("/pools", params={"kind": "indoor"})
    assert response.status_code == 200
    pools = response.json()["pools"]
    assert pools and all(p["kind"] == "indoor" for p in pools)


def test_pools_invalid_kind_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/pools", params={"kind": "spaceship"})
    assert response.status_code == 400


def test_pool_detail_unknown_facility_is_404() -> None:
    with TestClient(app) as client:
        response = client.get("/pools/does-not-exist")
    assert response.status_code == 404


def test_pool_detail_has_no_lane_panels_without_a_plan() -> None:
    # The curated app carries no lane plans yet: the detail resolves (200) but its lane-panel
    # list is empty — never an invented panel.
    with TestClient(app) as client:
        response = client.get("/pools/hallenbad-city", params={"at": "2026-09-15T07:00"})
    assert response.status_code == 200
    body = response.json()
    assert body["facility_id"] == "hallenbad-city"
    assert body["facility_name"] == "Hallenbad City"
    assert body["lane_panels"] == []


def test_pool_detail_surfaces_basins_features_lockers_prices() -> None:
    """Slice C acceptance: `/pools/{city}` JSON now carries the physical statics the domain
    already computes — basins (nominal_temp_c, lanes, dimensions, physical_source caveat),
    features resolved for the queried moment, lockers, the price table, and provenance —
    not just id/name/address/website/lane_panels."""
    with TestClient(app) as client:
        # A Tuesday at 09:00 — the sauna (08:00–22:00, all days) is open at the queried moment.
        response = client.get("/pools/hallenbad-city", params={"at": "2026-09-15T09:00"})
    assert response.status_code == 200
    body = response.json()

    # Basins: the 50m lap basin surfaces its size, lane count, temperature key, and its
    # curated-vs-parsed_prose caveat.
    basins = {b["basin_id"]: b for b in body["basins"]}
    assert set(basins) == {"city-50m", "city-lehrbecken"}
    lap = basins["city-50m"]
    assert lap["kind"] == "lap"
    assert lap["length_m"] == 50.0
    assert lap["lanes"] == 6
    assert "nominal_temp_c" in lap and lap["nominal_temp_c"] is None  # no temp curated yet
    assert lap["physical_source"] == "curated"  # the honesty caveat is present

    # Features: the sauna, resolved open at 09:00, with its stated hours and surcharge.
    features = {f["kind"]: f for f in body["features"]}
    assert "sauna" in features
    sauna = features["sauna"]
    assert sauna["open_now"] is True  # open-at-query-time, resolved for the queried moment
    assert sauna["hours"] == [{"start": "08:00", "end": "22:00"}]
    assert sauna["surcharge_chf"] == 10.0

    # Lockers: all three rows, with the orthogonal fee/deposit/period axes intact.
    lockers = {locker["category"]: locker for locker in body["lockers"]}
    assert set(lockers) == {"wardrobe", "valuables", "laundry"}
    assert lockers["wardrobe"]["fee_chf"] is None and lockers["wardrobe"]["deposit_chf"] == 5.0
    assert lockers["laundry"]["fee_chf"] == 400.0 and lockers["laundry"]["period"] == "1 Jahr"

    # Prices: the whole facility price table (not the per-person pick), with its freshness date.
    prices = body["prices"]
    assert prices is not None
    entries = {e["category"]: e for e in prices["entries"]}
    assert entries["adult"]["display"] == "Erwachsene CHF 8.00"
    assert entries["adult"]["amount_chf"] == 8.0
    assert prices["valid_as_of"] == "2026-07-18"

    # Provenance: the curated flag reaches the detail view.
    assert body["provenance"]["curated"] is True


def test_facility_detail_out_surfaces_temp_and_parsed_prose_caveat() -> None:
    """The temperature badge datum and the PARSED_PROSE caveat are real projections: a basin
    with a nominal temperature tagged `parsed_prose` surfaces both. (No curated pool carries a
    temperature yet — Slice F wires prose extraction — so this is proven at the mapping layer.)"""
    basin = Basin(
        basin_id=BasinId("warm-1"),
        name="Warmwasserbecken",
        rules=(),
        kind=BasinKind.NON_SWIMMER,
        dimensions=Dimensions(length_m=Decimal("12.5"), width_m=Decimal("8")),
        lanes=None,
        nominal_temp_c=Decimal("32.0"),
        physical_source=BasinSource.PARSED_PROSE,
    )
    sauna = FeatureStatus(
        feature=Feature(kind=FeatureKind.SAUNA, name="Sauna", surcharge_chf=Decimal("5.00")),
        schedule=OpenDay(
            sessions=(ResolvedSession(TimeRange(time(9, 0), time(21, 0)), PublicSwim()),)
        ),
        open_at_query_time=False,
    )
    detail = FacilityDetail(
        facility_id=PoolId("prose-pool"),
        facility_name="Prose Pool",
        address="Somewhere 1",
        website=None,
        basins=(basin,),
        features=(sauna,),
        lockers=(LockerOption(category=LockerCategory.WARDROBE, deposit_chf=Decimal("2")),),
        provenance=Provenance(source="pool-page", curated=False, valid_as_of=date(2026, 7, 1)),
    )
    out = facility_detail_out(
        detail,
        PriceTable(
            entries=(PriceEntry(PriceCategory.ADULT, Decimal("8"), "Adult CHF 8"),),
            valid_as_of=date(2026, 7, 1),
        ),
    )
    assert out.basins[0].nominal_temp_c == 32.0
    assert out.basins[0].physical_source == "parsed_prose"  # drives the UI caveat
    assert out.basins[0].width_m == 8.0
    assert out.features[0].open_now is False
    assert [(h.start, h.end) for h in out.features[0].hours] == [("09:00", "21:00")]
    assert out.prices is not None and out.prices.entries[0].display == "Adult CHF 8"
    assert out.provenance.curated is False and out.provenance.valid_as_of == "2026-07-01"


def test_access_types_explained() -> None:
    with TestClient(app) as client:
        response = client.get("/access-types")
    assert response.status_code == 200
    types = {t["key"]: t for t in response.json()["types"]}
    assert "women-only" in types
    assert types["women-only"]["description"]
    assert "school-reserved" in types
