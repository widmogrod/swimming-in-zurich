"""GoldSwimData reads facilities from the SQLite gold store and fails fast when empty."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from apps.web.services.gold_store import GoldSwimData
from swimzh.core.result import Ok
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import open_db, write_facilities

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def test_reads_facilities_and_calendar(tmp_path: Path) -> None:
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    db = tmp_path / "gold.sqlite"
    write_facilities(open_db(db), dataset.value.facilities)

    data = GoldSwimData.open(db, DATA_DIR)
    assert len(data.facilities()) == len(dataset.value.facilities)
    assert data.calendar().covers(date(2026, 3, 10))


def test_empty_store_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # creates the schema but no rows
    with pytest.raises(RuntimeError, match="empty"):
        GoldSwimData.open(db, DATA_DIR)
