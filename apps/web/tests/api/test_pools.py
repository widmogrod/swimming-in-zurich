"""The /pools and /access-types endpoints over the committed catalog."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from apps.web.api.pools.service import facility_detail_out
from apps.web.main import app
from swimzh.core.errors import ProviderError
from swimzh.core.result import Ok, Result
from swimzh.domain.access import PublicSwim
from swimzh.domain.catalog import ScheduleFreshness
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
from swimzh.domain.query import FacilityDetail, FeatureStatus, TempReading, TempUnavailable
from swimzh.domain.schedule import OpenDay, ResolvedSession, TimeRange

_ZURICH = ZoneInfo("Europe/Zurich")


class _FakeTemperatureProvider:
    """In-memory `TemperatureProvider` for the app tests — returns a canned reading for any
    poiid (S2 proves the wiring end-to-end; the real Baditicker adapter lands later)."""

    def __init__(self, result: Result[TempReading, ProviderError]) -> None:
        self._result = result

    def read(self, poiid: str) -> Result[TempReading, ProviderError]:
        return self._result


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


def test_pool_detail_location_only_pool_is_viewable() -> None:
    """S1 acceptance: an outdoor pin with no facility of its own still returns a location-only
    detail (200) rather than a 404. Name + location come back on the detail; its `kind` +
    coordinates are served by the `/pools` listing (`PoolOut`), and its `basins` list is empty.

    The subject is `seebad-enge`, not Heuried: seasonal-hours S3 admitted the outdoor/lake/river
    pools that publish a seasonal table, and Heuried is scraped now. Enge's page is a private
    operator's that no parser here understands (`etl.scrape._UNPARSEABLE_OPERATOR_PAGES`), so it
    stays the honest location-only case — an open-air pin, schedule-less, zero basins."""
    with TestClient(app) as client:
        detail = client.get("/pools/seebad-enge")
        listing = client.get("/pools").json()
    assert detail.status_code == 200  # was 404 before S1
    body = detail.json()
    assert body["facility_id"] == "seebad-enge"
    assert body["facility_name"] == "Seebad Enge"  # name
    assert body["address"]  # location (the catalog address is present)
    assert body["basins"] == []  # location-only: zero basins, rendered without error
    assert body["lane_panels"] == [] and body["features"] == []
    assert body["provenance"]["curated"] is False  # never flipped to curated
    # kind + geo (location) are on the listing entry for the same pool.
    enge = next(p for p in listing["pools"] if p["pool_id"] == "seebad-enge")
    assert enge["kind"] == "lake"
    assert enge["lat"] is not None and enge["lon"] is not None
    # Excluded from the scrape → `no_source`, never `scraped` and never `awaiting_scrape`.
    assert enge["freshness"] == "no_source"
    # …and a lake/outdoor pool that IS scraped reads differently, so this is not just "not indoor".
    heuried = next(p for p in listing["pools"] if p["pool_id"] == "freibad-heuried")
    assert heuried["freshness"] == "scraped"


def test_location_only_pool_is_never_a_swim_option_nor_closed() -> None:
    """S1 schedule-less invariant: a location-only pool (Enge, see above for why not Heuried)
    produces NO `/swim` option and no spurious `closed` status — it is reported with its freshness
    status (`no_source`, identity known, schedule not), never conflated with a real session or a
    stated closure."""
    swim_params = {
        "at": "2026-09-15T09:00",
        "gender": "female",
        "age": 34,
        "eligible_only": "false",
    }
    with TestClient(app) as client:
        swim = client.get("/swim", params=swim_params).json()
    assert "Seebad Enge" not in {o["facility"] for o in swim["options"]}
    closed = {s["facility"] for s in swim["statuses"] if s["status"] == "closed"}
    assert "Seebad Enge" not in closed  # no spurious "closed" for a rule-less facility
    schedule_less = {
        s["facility"] for s in swim["statuses"] if s["status"] in {"awaiting_scrape", "no_source"}
    }
    assert "Seebad Enge" in schedule_less


def test_pool_detail_has_no_lane_panels_without_a_plan(
    offline_gold_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without a scraped lane plan the detail resolves (200) but its lane-panel list is empty —
    # never an invented panel. Read against the PRE-SCRAPE store: the atomic `build` attaches
    # City's lane plan, so "no plan" is the pre-scrape (`build_store`) state.
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(offline_gold_db))
    with TestClient(app) as client:
        response = client.get("/pools/hallenbad-city", params={"at": "2026-09-15T07:00"})
    assert response.status_code == 200
    body = response.json()
    assert body["facility_id"] == "hallenbad-city"
    assert body["facility_name"] == "Hallenbad City"
    assert body["lane_panels"] == []


def test_pool_detail_surfaces_basins_physicals_and_prices() -> None:
    """Slice C acceptance (post delete-curated-schedule-tier S3): `/pools/{city}` JSON carries the
    physical statics the domain computes — per-basin dimensions/lanes/temperature key and the
    physical_source caveat, the scraped price table, and provenance. City's `Schwimmerbecken` basin
    gains its 50 m / 6-lane physicals from the WFS `infrastruktur` prose (`apply_physicals`), tagged
    `parsed_prose`. Features/lockers are not produced by the sourced pipeline (their projection is
    pinned by the mapping unit test `test_facility_detail_out_...`), so they are empty here."""
    with TestClient(app) as client:
        response = client.get("/pools/hallenbad-city", params={"at": "2026-09-15T09:00"})
    assert response.status_code == 200
    body = response.json()

    # Basins: the scraped schedule basin + the physical `Schwimmerbecken` (its 50 m / 6-lane
    # physicals sourced from the WFS prose, tagged parsed_prose).
    basins = {b["basin_id"]: b for b in body["basins"]}
    assert "city-50m" in basins
    lap = basins["city-50m"]
    assert lap["kind"] == "lap"
    assert lap["length_m"] == 50.0
    assert lap["lanes"] == 6
    assert lap["nominal_temp_c"] == 28.0  # "28°C" sourced from the WFS infrastruktur prose
    assert lap["physical_source"] == "parsed_prose"  # sourced from infrastruktur, honesty caveat

    # Features/lockers: not produced by the sourced pipeline (curated statics were deleted in S3).
    assert body["features"] == []
    assert body["lockers"] == []

    # Prices: the whole scraped facility price table, with its freshness date present.
    prices = body["prices"]
    assert prices is not None
    entries = {e["category"]: e for e in prices["entries"]}
    assert entries["adult"]["amount_chf"] == 8.0
    assert entries["adult"]["display"]
    assert prices["valid_as_of"]  # a scrape freshness date is stamped

    # Provenance: the curated flag reaches the detail view.
    assert "curated" in body["provenance"]


def test_pool_detail_surfaces_lane_plan_source_url() -> None:
    """S1 acceptance: `/pools/{id}` projects each basin's declared Belegungsplan PDF URL
    (`Basin.lane_plan_source.url`) as `lane_plan_url`. Oerlikon's two crosswalk basins declare
    DISTINCT PDFs (both survive the S3 strip + the scrape's binding-carry compose); the scraped
    schedule basin declares none (`null`). The price source_url still reaches the boundary."""
    _plan = "https://www.stadt-zuerich.ch/content/dam/web/de/stadtleben/sport-und-erholung/dokumente/badeanlagen/belegungsplaene"
    with TestClient(app) as client:
        oerlikon = client.get("/pools/hallenbad-oerlikon").json()
        city = client.get("/pools/hallenbad-city").json()

    # Oerlikon: its two crosswalk basins each carry the EXACT distinct PDF authored in the YAML.
    oerlikon_basins = {b["basin_id"]: b for b in oerlikon["basins"]}
    assert (
        oerlikon_basins["oerlikon-50m"]["lane_plan_url"] == f"{_plan}/oerlikon-schwimmerbecken.pdf"
    )
    assert (
        oerlikon_basins["oerlikon-sprungbecken"]["lane_plan_url"]
        == f"{_plan}/oerlikon-nichtschwimmer-sprungbecken.pdf"
    )
    # The two basins' URLs are genuinely distinct (not one repeated).
    assert (
        oerlikon_basins["oerlikon-50m"]["lane_plan_url"]
        != oerlikon_basins["oerlikon-sprungbecken"]["lane_plan_url"]
    )
    # The scraped schedule basin declares no `lane_plan_source` → projects `null`.
    assert oerlikon_basins["hallenbad-oerlikon-main"]["lane_plan_url"] is None
    # Regression guard: the price source URL still reaches the boundary.
    assert oerlikon["prices"]["source_url"] is not None

    # City: its `Schwimmerbecken` crosswalk basin carries the URL; the scraped basin projects null.
    city_basins = {b["basin_id"]: b for b in city["basins"]}
    assert city_basins["city-50m"]["lane_plan_url"] == f"{_plan}/city-schwimmerbecken.pdf"
    assert city_basins["hallenbad-city-main"]["lane_plan_url"] is None


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
        TempUnavailable(reason="no baditicker key"),
        ScheduleFreshness.AWAITING_SCRAPE,
    )
    # The live facility temp is additive and labelled — it never overwrites a basin's temp.
    assert out.live_water_temp.available is False
    assert out.live_water_temp.reason == "no baditicker key"
    assert out.basins[0].nominal_temp_c == 32.0
    assert out.basins[0].physical_source == "parsed_prose"  # drives the UI caveat
    assert out.basins[0].width_m == 8.0
    assert out.features[0].open_now is False
    assert [(h.start, h.end) for h in out.features[0].hours] == [("09:00", "21:00")]
    assert out.prices is not None and out.prices.entries[0].display == "Adult CHF 8"
    assert out.provenance.curated is False and out.provenance.valid_as_of == "2026-07-01"
    # The detail carries the SAME three-state freshness as the `/pools` row, so the panel's
    # trust line no longer has to read the (now always-False) `curated` flag.
    assert out.freshness == "awaiting_scrape"


def test_parsed_prose_pool_shows_in_detail_but_never_a_swim_option(
    offline_gold_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slice F / Decision #5 acceptance: a location-only pool whose WFS prose names basins gains
    auto-extracted PARSED_PROSE basins visible in `/pools/{id}` detail (with caveat), yet produces
    NO `/swim` option — it stays reported with its freshness status, never conflated with a
    real session (Altstetten is indoor + schedule-less → `awaiting_scrape`).

    Read against the PRE-SCRAPE store: the atomic `build` would scrape Altstetten into a real
    schedule, so the schedule-less/prose-only state this pins is only observable before the fold.
    """
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(offline_gold_db))
    swim_params = {
        "at": "2026-09-15T09:00",
        "gender": "female",
        "age": 34,
        "eligible_only": "false",
    }
    with TestClient(app) as client:
        detail = client.get("/pools/hallenbad-altstetten", params={"at": "2026-09-15T09:00"}).json()
        swim = client.get("/swim", params=swim_params).json()

    # Detail: the auto-extracted basins are present and EVERY one is tagged parsed_prose (which
    # drives the honesty caveat), including the diving basin with its platform heights.
    assert detail["basins"], "prose pool must surface its auto-extracted basins in detail"
    assert all(b["physical_source"] == "parsed_prose" for b in detail["basins"])
    diving = [b for b in detail["basins"] if b["kind"] == "diving"]
    assert diving and diving[0]["diving_platforms_m"] == [1.0, 3.0, 5.0]

    # /swim: the gate. Never an option; reported `awaiting_scrape` instead — the test fails the
    # moment a PARSED_PROSE basin leaks into an option.
    assert "Hallenbad Altstetten" not in {o["facility"] for o in swim["options"]}
    awaiting = {s["facility"] for s in swim["statuses"] if s["status"] == "awaiting_scrape"}
    assert "Hallenbad Altstetten" in awaiting


def test_pool_detail_surfaces_live_water_temp_from_a_wired_provider() -> None:
    """S2 acceptance: with a fake provider @ 23 °C wired into `app.state`, `/pools/freibad-heuried`
    (the UNCURATED pin whose `fb012` key rides the S1 location-only mint into gold) surfaces a
    facility-level `live_water_temp` with a numeric age — the whole live-attach path end-to-end."""
    measured_at = datetime.now(_ZURICH) - timedelta(minutes=15)
    reading = TempReading(
        measured_at=measured_at, celsius=Decimal("23.0"), is_open=True, source="baditicker"
    )
    with TestClient(app) as client:
        app.state.temperature = _FakeTemperatureProvider(Ok(reading))
        try:
            body = client.get("/pools/freibad-heuried").json()
        finally:
            app.state.temperature = None
    temp = body["live_water_temp"]
    assert temp["available"] is True
    assert temp["celsius"] == 23.0
    assert isinstance(temp["age_min"], int) and temp["age_min"] >= 0  # derived freshness
    assert temp["is_open"] is True
    assert temp["source"] == "baditicker"
    assert temp["reason"] is None
    assert temp["measured_at"] is not None


def test_pool_detail_live_water_temp_unavailable_without_a_key() -> None:
    """A pool with no `baditicker_poiid` (Hallenbad Altstetten — genuinely absent from the
    Baditicker feed) never asks the provider: the facility-level temp reports the unavailable
    reason, not a stale number."""
    reading = TempReading(
        measured_at=datetime.now(_ZURICH),
        celsius=Decimal("23.0"),
        is_open=True,
        source="baditicker",
    )
    with TestClient(app) as client:
        app.state.temperature = _FakeTemperatureProvider(Ok(reading))
        try:
            body = client.get("/pools/hallenbad-altstetten").json()
        finally:
            app.state.temperature = None
    temp = body["live_water_temp"]
    assert temp["available"] is False
    assert temp["celsius"] is None
    assert temp["reason"] == "no baditicker key"


def test_pool_detail_live_water_temp_fail_open_when_unconfigured() -> None:
    """Fail-open: the default app wires NO temperature provider, so the detail reports an
    explainable unavailable reason (never an exception, never a fabricated reading)."""
    with TestClient(app) as client:
        body = client.get("/pools/freibad-heuried").json()
    temp = body["live_water_temp"]
    assert temp["available"] is False
    assert temp["reason"] == "live temperature not configured"


def test_access_types_are_keys_the_client_translates() -> None:
    """S5: the endpoint serves KEYS, not English prose.

    It used to ship `label`/`description`, which made the server decide the explanation's
    language. The client now renders both from its own catalogue, so one response serves
    every locale — and the endpoint's contract is the key set.
    """
    with TestClient(app) as client:
        response = client.get("/access-types")
    assert response.status_code == 200
    types = response.json()["types"]
    keys = {t["key"] for t in types}
    assert "women-only" in keys
    assert "school-reserved" in keys
    assert all(set(t) == {"key"} for t in types), "no prose should remain on the wire"
