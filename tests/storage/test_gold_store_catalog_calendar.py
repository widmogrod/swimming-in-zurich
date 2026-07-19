"""The gold store is self-contained: one DB round-trips facilities + catalog + calendar.

Proves S1's acceptance — writing all three curated sources into one `:memory:` store and
reading them back equal — and that the new tables are additive (a facility-only DB still
opens and round-trips facilities).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_catalog,
    open_db,
    write_calendar,
    write_catalog,
    write_facilities,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.facilities


@pytest.fixture(scope="module")
def calendar() -> ZurichCalendar:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.calendar


@pytest.fixture(scope="module")
def catalog() -> tuple[PoolCatalogEntry, ...]:
    return catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


def _calendar_state(cal: ZurichCalendar) -> tuple[object, object, object]:
    return (cal._public, cal._school, cal._known_years)


def test_one_db_holds_all_three_and_reads_them_back_equal(
    facilities: tuple[Facility, ...],
    catalog: tuple[PoolCatalogEntry, ...],
    calendar: ZurichCalendar,
) -> None:
    conn = open_db(":memory:")

    write_facilities(conn, facilities)
    write_catalog(conn, catalog)
    write_calendar(conn, calendar)

    repo = GoldRepository(conn)
    loaded_facilities = {f.identity.facility_id: f for f in repo.load_all()}
    assert loaded_facilities == {f.identity.facility_id: f for f in facilities}

    assert load_catalog(conn) == tuple(sorted(catalog, key=lambda e: e.pool_id))

    assert _calendar_state(load_calendar(conn)) == _calendar_state(calendar)


def test_catalog_write_is_idempotent(catalog: tuple[PoolCatalogEntry, ...]) -> None:
    conn = open_db(":memory:")
    write_catalog(conn, catalog)
    write_catalog(conn, catalog)  # upsert, not duplicate
    assert len(load_catalog(conn)) == len(catalog)


def test_calendar_write_is_idempotent_singleton(calendar: ZurichCalendar) -> None:
    conn = open_db(":memory:")
    write_calendar(conn, calendar)
    write_calendar(conn, calendar)
    assert conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0] == 1


def test_load_calendar_missing_raises() -> None:
    conn = open_db(":memory:")
    with pytest.raises(LookupError):
        load_calendar(conn)


def test_new_tables_are_backward_compatible(
    tmp_path: Path,
    facilities: tuple[Facility, ...],
    catalog: tuple[PoolCatalogEntry, ...],
) -> None:
    # A store created before catalog/calendar existed (facility table only) must still open
    # via open_db, gain the new tables, keep its facilities, and accept catalog rows.
    db_path = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        "CREATE TABLE facility ("
        "facility_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, "
        "lat REAL, lon REAL, valid_as_of TEXT, fetched_at TEXT, doc TEXT NOT NULL);"
    )
    write_facilities(legacy, facilities)
    legacy.close()

    conn = open_db(db_path)  # re-open the legacy DB: schema is applied additively
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"facility", "catalog", "calendar"} <= tables

    assert GoldRepository(conn).count() == len(facilities)  # existing rows survived
    write_catalog(conn, catalog)  # new table is usable
    assert len(load_catalog(conn)) == len(catalog)
