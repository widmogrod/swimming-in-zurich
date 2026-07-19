"""The gold store is self-contained: one DB round-trips the pool spine + facilities + calendar.

Writing the identity spine (`pool` + `pool_alias` + `pool_xref`), the transitional `facility`
table, and the calendar into one `:memory:` store and reading them back equal. The catalog
listing now serves from the same `pool` spine as `/swim` — one store, joinable by `pool.id`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.build.seed import build_spine
from swimzh.core.result import Ok
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility
from swimzh.domain.registry import Registry
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_catalog,
    open_db,
    write_calendar,
    write_facilities,
    write_pools,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.facilities


@pytest.fixture(scope="module")
def registry() -> Registry:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.registry


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


def test_one_db_holds_spine_facilities_and_calendar(
    facilities: tuple[Facility, ...],
    registry: Registry,
    catalog: tuple[PoolCatalogEntry, ...],
    calendar: ZurichCalendar,
) -> None:
    conn = open_db(":memory:")
    spine = build_spine(catalog, facilities, registry)

    write_pools(conn, spine)
    write_facilities(conn, facilities)
    write_calendar(conn, calendar)

    # /swim reads facilities from the transitional facility table.
    repo = GoldRepository(conn)
    loaded_facilities = {f.identity.facility_id: f for f in repo.load_all()}
    assert loaded_facilities == {f.identity.facility_id: f for f in facilities}

    # /pools reads the full roster from the pool spine — every catalog pool, one canonical id.
    roster = load_catalog(conn)
    assert {e.pool_id for e in roster} == {e.pool_id for e in catalog}

    assert _calendar_state(load_calendar(conn)) == _calendar_state(calendar)


def test_pool_write_is_idempotent(
    facilities: tuple[Facility, ...],
    registry: Registry,
    catalog: tuple[PoolCatalogEntry, ...],
) -> None:
    conn = open_db(":memory:")
    spine = build_spine(catalog, facilities, registry)
    write_pools(conn, spine)
    write_pools(conn, spine)  # full replace, not duplicate
    assert len(load_catalog(conn)) == len(catalog)
    assert conn.execute("SELECT COUNT(*) FROM pool_alias").fetchone()[0] == len(spine.aliases)
    assert conn.execute("SELECT COUNT(*) FROM pool_xref").fetchone()[0] == len(spine.xrefs)


def test_calendar_write_is_idempotent_singleton(calendar: ZurichCalendar) -> None:
    conn = open_db(":memory:")
    write_calendar(conn, calendar)
    write_calendar(conn, calendar)
    assert conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0] == 1


def test_load_calendar_missing_raises() -> None:
    conn = open_db(":memory:")
    with pytest.raises(LookupError):
        load_calendar(conn)


def test_spine_tables_present_and_strict() -> None:
    conn = open_db(":memory:")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"pool", "pool_alias", "pool_xref", "facility", "calendar"} <= tables
    # The retired `catalog` table is gone — the roster lives on the `pool` spine.
    assert "catalog" not in tables
