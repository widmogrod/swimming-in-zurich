"""When SWIMZH_GOLD_DB points at a populated gold store, the app serves from it (the same
answers, now sourced through the SQLite gold path)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app
from swimzh.core.result import Ok
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import open_db, write_facilities

DATA_DIR = Path(__file__).resolve().parents[4] / "data"


def test_app_serves_from_gold_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    db = tmp_path / "gold.sqlite"
    write_facilities(open_db(db), dataset.value.facilities)

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34}
        )
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" in accesses
