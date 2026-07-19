"""GoldSwimStore reads facilities, the roster, and the calendar from the SQLite gold store and
fails fast when the store is empty. No curated `data/` tree is read at runtime."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from apps.web.services.gold_store import GoldSwimStore
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

    data = GoldSwimStore.open(db)
    assert len(data.facilities()) == len(dataset.value.facilities)
    # The calendar is sourced from the gold `calendar` table, never from data/.
    assert data.calendar().covers(date(2026, 3, 10))


def test_roster_holds_the_full_catalog_with_curation(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    data = GoldSwimStore.open(db)
    roster = data.roster()
    # The roster is the whole catalog (~57 pools), far more than the handful of curated ones.
    assert len(roster) >= 50
    curated_ids = {str(f.identity.facility_id) for f in data.facilities()}
    # A pool is `curated` iff a curated facility with a schedule backs it (roster ⊇ curated).
    assert {r.entry.pool_id for r in roster if r.curated} == curated_ids


def test_facility_resolves_a_catalog_pool_to_its_schedule(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    data = GoldSwimStore.open(db)
    # A curated catalog id resolves to its facility (schedule) via the canonical-id join.
    facility = data.facility("hallenbad-city")
    assert facility is not None and facility.identity.name == "Hallenbad City"
    # An uncurated catalog pool has no schedule; an unknown id resolves to None (→ 404 upstream).
    assert data.facility("hallenbad-altstetten") is None
    assert data.facility("does-not-exist") is None


def test_empty_store_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # creates the schema but no rows
    with pytest.raises(RuntimeError, match="empty"):
        GoldSwimStore.open(db)
