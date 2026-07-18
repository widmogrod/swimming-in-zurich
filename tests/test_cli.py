"""The build-gold CLI command writes a usable gold store (driven by MockTransport)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from apps.web.services.gold_store import GoldSwimData

from swimzh.cli import build_gold, main
from swimzh.core.http import HttpClient, RetryPolicy

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
    assert len(data.facilities()) == 3


def test_build_gold_reports_failure(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    bad = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500, text="x")))
    client = HttpClient(bad, source="geo_sport", retry=RetryPolicy(max_attempts=1))
    code = build_gold(db_path=db, data_dir=DATA_DIR, client=client, fetched_at=FETCHED_AT)
    assert code == 1


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_build_gold_requires_db() -> None:
    with pytest.raises(SystemExit):
        main(["build-gold"])
