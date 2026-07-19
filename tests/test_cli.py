"""The build-gold CLI command writes a usable gold store (driven by MockTransport)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.cli import build, build_catalog_file, build_gold, main, scrape_gold, scrape_lanes
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import BasinId, FacilityId, PoolKind
from swimzh.providers.curated import load_dataset
from swimzh.providers.geo_sport import POOL_LAYERS
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_catalog,
    open_db,
)

_FIXTURES = Path(__file__).resolve().parent / "providers" / "fixtures"
FIXTURE_HTML = _FIXTURES / "hallenbad_city.html"
FIXTURE_PDF = _FIXTURES / "city-schwimmerbecken.pdf"

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ZURICH = ZoneInfo("Europe/Zurich")
FETCHED_AT = datetime(2026, 7, 18, 9, 0, tzinfo=ZURICH)


def _feature(fid: str, name: str, lon: float, lat: float) -> dict[str, object]:
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name},
    }


GEOJSON: dict[str, object] = {
    "type": "FeatureCollection",
    "features": [
        _feature("poi_hallenbad_view.2", "Hallenbad City", 8.5330, 47.3723),
        _feature("poi_hallenbad_view.5", "Hallenbad Oerlikon", 8.5567, 47.4104),
        _feature("poi_hallenbad_view.1", "Hallenbad Bungertwies", 8.5601, 47.3720),
    ],
}


def _client() -> HttpClient:
    inner = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=GEOJSON))
    )
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def test_build_gold_writes_readable_store(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    code = build_gold(db_path=db, data_dir=DATA_DIR, client=_client(), fetched_at=FETCHED_AT)
    assert code == 0
    assert db.exists()

    # The written store's facilities are readable through the gold read side.
    assert len(GoldRepository(open_db(db)).load_all()) == 4


def test_build_gold_reports_failure(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    bad = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500, text="x")))
    client = HttpClient(bad, source="geo_sport", retry=RetryPolicy(max_attempts=1))
    code = build_gold(db_path=db, data_dir=DATA_DIR, client=client, fetched_at=FETCHED_AT)
    assert code == 1


def _layer_handler(request: httpx.Request) -> httpx.Response:
    typename = request.url.params.get("TYPENAME", "")
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"{typename}.1",
                "geometry": {"type": "Point", "coordinates": [8.5, 47.3]},
                "properties": {"name": f"Pool {typename}"},
            }
        ],
    }
    return httpx.Response(200, json=fc)


def test_build_catalog_writes_all_layers(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    inner = httpx.Client(transport=httpx.MockTransport(_layer_handler))
    client = HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))
    code = build_catalog_file(out=out, client=client, generated_at=FETCHED_AT)
    assert code == 0

    entries = catalog_json.loads(out.read_text(encoding="utf-8"))
    assert len(entries) == len(POOL_LAYERS)  # one feature per layer
    assert {e.kind.value for e in entries} == {k.value for k in POOL_LAYERS.values()}


def test_scrape_gold_writes_store_from_catalog(tmp_path: Path) -> None:
    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 71",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url="https://example.test/city.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")

    body = FIXTURE_HTML.read_bytes()
    inner = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body))
    )
    client = HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))

    db = tmp_path / "gold.sqlite"
    code = scrape_gold(db_path=db, catalog_path=catalog_file, client=client, fetched_at=FETCHED_AT)
    assert code == 0
    assert len(GoldRepository(open_db(db)).load_all()) == 1


def _pdf_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def test_scrape_lanes_attaches_plan_to_curated_basin(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    build_gold(db_path=db, data_dir=DATA_DIR, client=_client(), fetched_at=FETCHED_AT)

    body = FIXTURE_PDF.read_bytes()
    client = _pdf_client(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(
        db_path=db, client=client, fetched_at=FETCHED_AT, urls=("https://example.test/city.pdf",)
    )
    assert code == 0

    city = GoldRepository(open_db(db)).get(FacilityId("city"))
    assert city is not None
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert lap.lane_plan is not None
    assert lap.lane_plan.lane_count == 6
    assert lap.lane_plan.fetched_at == FETCHED_AT


def test_scrape_lanes_missing_db_is_error(tmp_path: Path) -> None:
    client = _pdf_client(lambda _r: httpx.Response(200, content=b""))
    code = scrape_lanes(db_path=tmp_path / "absent.sqlite", client=client, fetched_at=FETCHED_AT)
    assert code == 1


def test_scrape_lanes_reports_when_no_pdf_parses(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    build_gold(db_path=db, data_dir=DATA_DIR, client=_client(), fetched_at=FETCHED_AT)
    client = _pdf_client(lambda _r: httpx.Response(503, text="down"))
    code = scrape_lanes(
        db_path=db, client=client, fetched_at=FETCHED_AT, urls=("https://example.test/city.pdf",)
    )
    assert code == 1


def test_scrape_lanes_empty_store_is_error(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # schema only, no facilities
    client = _pdf_client(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    code = scrape_lanes(
        db_path=db, client=client, fetched_at=FETCHED_AT, urls=("https://example.test/city.pdf",)
    )
    assert code == 1


def test_build_produces_complete_offline_store(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    code = build(db_path=db, data_dir=DATA_DIR)
    assert code == 0
    assert db.exists()

    conn = open_db(db)
    # Catalog table holds every known pool (committed data/catalog.json).
    assert len(load_catalog(conn)) == 57
    # Calendar table covers the current planning horizon.
    assert load_calendar(conn).covers(datetime(2026, 1, 1, tzinfo=ZURICH).date())
    # Facility table holds the curated facilities — no geo/network enrichment needed.
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    stored = {f.identity.facility_id for f in GoldRepository(conn).load_all()}
    assert stored == {f.identity.facility_id for f in dataset.value.facilities}


def test_build_via_main_offline(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    code = main(["build", "--db", str(db), "--data", str(DATA_DIR)])
    assert code == 0
    assert len(load_catalog(open_db(db))) == 57


def test_build_missing_catalog_is_error(tmp_path: Path) -> None:
    # A data dir with calendar/registry/pools but no catalog.json.
    data = tmp_path / "data"
    (data / "pools").mkdir(parents=True)
    (data / "calendar").mkdir()
    (data / "registry.yaml").write_bytes((DATA_DIR / "registry.yaml").read_bytes())
    (data / "calendar" / "zurich.yaml").write_bytes(
        (DATA_DIR / "calendar" / "zurich.yaml").read_bytes()
    )
    for pool in (DATA_DIR / "pools").glob("*.yaml"):
        (data / "pools" / pool.name).write_bytes(pool.read_bytes())

    code = build(db_path=tmp_path / "gold.sqlite", data_dir=data)
    assert code == 1


def test_build_then_scrape_gold_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    before = GoldRepository(open_db(db)).count()

    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 71",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url="https://example.test/city.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")
    body = FIXTURE_HTML.read_bytes()
    inner = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body))
    )
    client = HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))

    scraped = scrape_gold(
        db_path=db, catalog_path=catalog_file, client=client, fetched_at=FETCHED_AT
    )
    assert scraped == 0
    # Enrichment adds/updates facilities on top of the offline build; catalog+calendar survive.
    conn = open_db(db)
    assert GoldRepository(conn).count() >= before
    assert len(load_catalog(conn)) == 57
    assert load_calendar(conn).covers(datetime(2026, 6, 1, tzinfo=ZURICH).date())


def test_build_then_scrape_lanes_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0

    body = FIXTURE_PDF.read_bytes()
    client = _pdf_client(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(
        db_path=db, client=client, fetched_at=FETCHED_AT, urls=("https://example.test/city.pdf",)
    )
    assert code == 0

    conn = open_db(db)
    city = GoldRepository(conn).get(FacilityId("city"))
    assert city is not None
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert lap.lane_plan is not None
    # Catalog + calendar assembled by `build` are untouched by lane enrichment.
    assert len(load_catalog(conn)) == 57


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_build_gold_requires_db() -> None:
    with pytest.raises(SystemExit):
        main(["build-gold"])
