"""Shared app-test fixtures.

The app now reads exclusively from the SQLite gold store, so every test needs a built
gold DB and `SWIMZH_GOLD_DB` pointing at it. We build one self-contained gold DB per
session (via the offline `swimzh build` path) and aim the app at it by default; tests that
need a bespoke store override `SWIMZH_GOLD_DB` themselves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.etl.build import build_store

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


@pytest.fixture(scope="session")
def gold_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A complete, self-contained gold DB built offline from the committed inputs."""
    db = tmp_path_factory.mktemp("gold") / "gold.sqlite"
    result = build_store(DATA_DIR, db)
    assert isinstance(result, Ok), result
    return db


@pytest.fixture(autouse=True)
def _point_app_at_gold_db(gold_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aim the app at the session gold DB by default (tests may override)."""
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(gold_db))
