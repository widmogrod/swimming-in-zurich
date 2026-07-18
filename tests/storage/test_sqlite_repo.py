"""GoldRepository round-trips facilities through SQLite faithfully."""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.domain.models import Facility
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import GoldRepository, open_db, write_facilities

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def facilities() -> tuple[Facility, ...]:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value.facilities


def test_write_then_load_all_roundtrips(facilities: tuple[Facility, ...]) -> None:
    conn = open_db(":memory:")
    write_facilities(conn, facilities)
    repo = GoldRepository(conn)

    assert repo.count() == len(facilities)
    loaded = {f.identity.facility_id: f for f in repo.load_all()}
    original = {f.identity.facility_id: f for f in facilities}
    assert loaded == original


def test_get_by_id_and_missing(facilities: tuple[Facility, ...]) -> None:
    conn = open_db(":memory:")
    write_facilities(conn, facilities)
    repo = GoldRepository(conn)

    some_id = facilities[0].identity.facility_id
    assert repo.get(some_id) == facilities[0]
    from swimzh.domain.models import FacilityId

    assert repo.get(FacilityId("does-not-exist")) is None


def test_write_is_idempotent(facilities: tuple[Facility, ...]) -> None:
    conn = open_db(":memory:")
    write_facilities(conn, facilities)
    write_facilities(conn, facilities)  # upsert, not duplicate
    assert GoldRepository(conn).count() == len(facilities)
