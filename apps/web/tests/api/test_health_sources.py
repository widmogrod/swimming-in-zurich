"""`/health` reports the store's per-source provenance: which source each fact came from, when it
was fetched, and whether the build kept it STALE. The wire shape is the lake's silver header plus
the age at build time, so an operator can read "roster from 08-31, stale" off one endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.pipeline_clients import recorded_build_clients

from apps.web.main import app
from swimzh.cli import EXIT_BUILT_STALE, build
from swimzh.storage.lake import Lake

_ZURICH = ZoneInfo("Europe/Zurich")
_MONDAY = datetime(2026, 8, 31, 5, 0, tzinfo=_ZURICH)
DATA_DIR = Path(__file__).resolve().parents[4] / "data"


def _wfs_down(request: httpx.Request) -> httpx.Response | None:
    if request.url.params.get("TYPENAME"):
        return httpx.Response(503, text="down")
    return None


def test_health_lists_each_source_with_its_status_and_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "gold.sqlite"
    lake = Lake(tmp_path / "lake")
    assert (
        build(
            db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(), lake=lake, now=_MONDAY
        )
        == 0
    )
    friday = _MONDAY + timedelta(days=20)
    assert (
        build(
            db_path=db,
            data_dir=DATA_DIR,
            clients=recorded_build_clients(_wfs_down),
            lake=lake,
            now=friday,
        )
        == EXIT_BUILT_STALE
    )

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    by_source = {row["source"]: row for row in body["sources"]}
    assert set(by_source) == {"roster", "prices", "schedules", "lane_plans"}
    assert by_source["roster"]["status"] == "stale"
    assert by_source["roster"]["fetched_at"] == _MONDAY.isoformat()
    assert by_source["roster"]["age_days"] == 20.0
    assert by_source["schedules"]["status"] == "fresh"
    assert by_source["schedules"]["age_days"] == 0.0
