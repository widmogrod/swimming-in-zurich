"""GoldSwimData reads facilities + calendar from the SQLite gold store and fails fast when
the store is empty. No curated `data/` tree is read at runtime."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from apps.web.services.gold_store import GoldSwimData
from swimzh.core.result import Ok
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import open_db

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def test_reads_facilities_and_calendar(tmp_path: Path) -> None:
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    data = GoldSwimData.open(db)
    assert len(data.facilities()) == len(dataset.value.facilities)
    # The calendar is sourced from the gold `calendar` table, never from data/.
    assert data.calendar().covers(date(2026, 3, 10))


def test_empty_store_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # creates the schema but no rows
    with pytest.raises(RuntimeError, match="empty"):
        GoldSwimData.open(db)
