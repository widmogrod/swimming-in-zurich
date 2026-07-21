"""GoldRepository round-trips the curated schedule blob through `pool.facility_doc`.

Post-B2 the read path is `pool.facility_doc` (written by the single `write_schedules` door),
not the `facility` table — so the round-trip is seeded via `write_pools` + `write_schedules`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swimzh.build.seed import build_spine
from swimzh.core.result import Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility, PoolId
from swimzh.domain.registry import Registry
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json, codec
from swimzh.storage.rows import PoolSpine
from swimzh.storage.sqlite_repo import GoldRepository, open_db, write_pools, write_schedules

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def spine() -> PoolSpine:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    catalog: tuple[PoolCatalogEntry, ...] = catalog_json.loads(
        (DATA_DIR / "catalog.json").read_text(encoding="utf-8")
    )
    registry: Registry = result.value.registry
    return build_spine(catalog, result.value.facilities, registry)


def _keyed(spine: PoolSpine) -> dict[PoolId, Facility]:
    """The curated `(PoolId, Facility)` pairs `write_schedules` lands on `pool.facility_doc`."""
    return {p.id: codec.loads(p.facility_doc) for p in spine.pools if p.facility_doc is not None}


def _seed(spine: PoolSpine) -> sqlite3.Connection:
    conn = open_db(":memory:")
    write_pools(conn, spine)
    write_schedules(conn, tuple(_keyed(spine).items()))
    return conn


def test_write_then_load_all_roundtrips(spine: PoolSpine) -> None:
    repo = GoldRepository(_seed(spine))
    expected = _keyed(spine)

    # 4 curated pools + 2 Slice-F prose pools (schedule-less PARSED_PROSE blobs).
    assert repo.count() == len(expected) == 6
    loaded = {f.identity.facility_id: f for f in repo.load_all()}
    assert loaded == expected


def test_get_by_id_and_missing(spine: PoolSpine) -> None:
    repo = GoldRepository(_seed(spine))
    keyed = _keyed(spine)

    some_id, some_facility = next(iter(keyed.items()))
    assert repo.get(some_id) == some_facility
    assert repo.get(PoolId("does-not-exist")) is None


def test_write_schedules_is_idempotent(spine: PoolSpine) -> None:
    conn = _seed(spine)
    write_schedules(conn, tuple(_keyed(spine).items()))  # UPDATE again, not duplicate
    assert GoldRepository(conn).count() == 6  # 4 curated + 2 Slice-F prose pools
