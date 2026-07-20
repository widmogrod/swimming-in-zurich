"""End-to-end medallion: raw -> silver -> gold (SQLite), then the query reads from gold.
Driven by httpx.MockTransport so it is deterministic and offline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from swimzh.core.errors import HttpStatus
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.models import Facility
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import SwimQuery, find_swim_options
from swimzh.etl import pipeline
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec
from swimzh.storage.sqlite_repo import open_db

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
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


def _client(response: httpx.Response) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(lambda _r: response))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def _facility_table(conn: object) -> tuple[Facility, ...]:
    """Read the legacy ``facility`` table directly — pipeline.run's only write target.

    ``pipeline.run`` (the legacy build-gold path, retired in Plan C) writes the transitional
    ``facility`` table but not the ``pool`` spine; the flipped ``GoldRepository`` reads
    ``pool.facility_doc``, so its output is verified on the facility table here.
    """
    cursor = conn.execute("SELECT doc FROM facility ORDER BY facility_id")  # type: ignore[attr-defined]
    return tuple(codec.loads(row[0]) for row in cursor.fetchall())


def test_pipeline_end_to_end_then_query(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    result = pipeline.run(
        data_dir=DATA_DIR,
        db_path=db,
        client=_client(httpx.Response(200, json=GEOJSON)),
        fetched_at=FETCHED_AT,
    )
    assert isinstance(result, Ok), result

    facilities = _facility_table(open_db(db))
    assert len(facilities) == 4
    by_id = {str(f.identity.facility_id): f for f in facilities}
    city = by_id["hallenbad-city"]
    assert city.geo is not None
    assert city.identity.geo_sport_id == "poi_hallenbad_view.2"
    assert city.provenance.fetched_at == FETCHED_AT

    # The gold store feeds the query surface (Tuesday 18:00, in term).
    calendar_result = load_dataset(DATA_DIR)
    assert isinstance(calendar_result, Ok)
    query = SwimQuery(
        person=Person(gender=Gender.MALE, age=40),
        at=datetime(2026, 9, 15, 18, 0, tzinfo=ZURICH),
    )
    answer = find_swim_options(query, facilities, calendar_result.value.calendar)
    assert answer.eligible_options()


def test_pipeline_persists_raw(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    result = pipeline.run(
        data_dir=DATA_DIR,
        db_path=":memory:",
        client=_client(httpx.Response(200, json=GEOJSON)),
        fetched_at=FETCHED_AT,
        raw_dir=raw_dir,
    )
    assert isinstance(result, Ok)
    raw_file = raw_dir / "geo_sport.json"
    assert raw_file.exists()
    assert b"FeatureCollection" in raw_file.read_bytes()


def test_pipeline_propagates_fetch_failure() -> None:
    result = pipeline.run(
        data_dir=DATA_DIR,
        db_path=":memory:",
        client=_client(httpx.Response(500, text="boom")),
        fetched_at=FETCHED_AT,
    )
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
