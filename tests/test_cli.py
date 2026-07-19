"""The build-gold CLI command writes a usable gold store (driven by MockTransport)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from apps.web.services.gold_store import GoldSwimData

from swimzh.cli import build_catalog_file, build_gold, main, scrape_gold
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.providers.geo_sport import POOL_LAYERS
from swimzh.storage import catalog_json

FIXTURE_HTML = Path(__file__).resolve().parent / "providers" / "fixtures" / "hallenbad_city.html"

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

    # The written store is readable through the same SwimData port the app uses.
    data = GoldSwimData.open(db, DATA_DIR)
    assert len(data.facilities()) == 4


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
    data = GoldSwimData.open(db, DATA_DIR)
    assert len(data.facilities()) == 1


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_build_gold_requires_db() -> None:
    with pytest.raises(SystemExit):
        main(["build-gold"])
