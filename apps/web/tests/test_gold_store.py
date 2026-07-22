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
    # Every curated facility reaches the read path; Slice F adds schedule-less prose pools too, so
    # the served set is a superset of the curated dataset.
    served_ids = {str(f.identity.facility_id) for f in data.facilities()}
    curated_ids = {str(f.identity.facility_id) for f in dataset.value.facilities}
    assert curated_ids <= served_ids
    assert len(data.facilities()) >= len(dataset.value.facilities)
    # The calendar is sourced from the gold `calendar` table, never from data/.
    assert data.calendar().covers(date(2026, 3, 10))


def test_roster_holds_the_full_catalog_with_curation(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    data = GoldSwimStore.open(db)
    roster = data.roster()
    # The roster is the whole catalog (~57 pools), far more than the handful of curated ones.
    assert len(roster) >= 50
    # A pool is `curated` iff a facility with a SCHEDULE backs it. `data.facilities()` now also
    # includes Slice-F schedule-less prose pools, which are NOT curated — filter to scheduled.
    scheduled_ids = {
        str(f.identity.facility_id) for f in data.facilities() if any(b.rules for b in f.basins)
    }
    assert {r.entry.pool_id for r in roster if r.curated} == scheduled_ids


def test_facility_resolves_a_catalog_pool_to_its_schedule(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    data = GoldSwimStore.open(db)
    # A curated catalog id resolves to its facility (schedule) via the canonical-id join.
    facility = data.facility("hallenbad-city")
    assert facility is not None and facility.identity.name == "Hallenbad City"
    # A pure location-only pool (no prose describing a basin) has no facility_doc → None (→ 404).
    assert data.facility("schulschwimmanlage-hardau") is None
    assert data.facility("does-not-exist") is None
    # Slice F: a location-only pool whose WFS prose names basins resolves to a SCHEDULE-LESS
    # facility (auto-extracted PARSED_PROSE basins) — surfaced in detail, but never a /swim option.
    altstetten = data.facility("hallenbad-altstetten")
    assert altstetten is not None
    assert altstetten.basins and not any(b.rules for b in altstetten.basins)


def test_empty_store_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # creates the schema but no rows
    with pytest.raises(RuntimeError, match="empty"):
        GoldSwimStore.open(db)
