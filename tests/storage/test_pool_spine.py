"""The DB is the airtight lock: UNIQUE + FK make the split-brain an unrepresentable write.

These prove the constraints, not assume them — a duplicate alias/xref raises `IntegrityError`,
and an orphan crosswalk row is rejected by the foreign key.
"""

from __future__ import annotations

import sqlite3

import pytest

from swimzh.storage.sqlite_repo import open_db


def _add_pool(conn: sqlite3.Connection, pool_id: str) -> None:
    conn.execute(
        "INSERT INTO pool (id, name, kind, address) VALUES (?, ?, ?, ?)",
        (pool_id, pool_id.title(), "indoor", "addr"),
    )


def test_duplicate_alias_norm_raises_integrity_error() -> None:
    conn = open_db(":memory:")
    _add_pool(conn, "pool-a")
    _add_pool(conn, "pool-b")
    conn.execute("INSERT INTO pool_alias (pool_id, alias, norm) VALUES ('pool-a', 'A', 'shared')")
    with pytest.raises(sqlite3.IntegrityError):
        # A second pool claiming the same normalized name is the exact split-brain bug — the
        # UNIQUE(norm) constraint rejects it at write time.
        conn.execute(
            "INSERT INTO pool_alias (pool_id, alias, norm) VALUES ('pool-b', 'A', 'shared')"
        )


def test_duplicate_xref_namespace_ext_id_raises_integrity_error() -> None:
    conn = open_db(":memory:")
    _add_pool(conn, "pool-a")
    _add_pool(conn, "pool-b")
    conn.execute(
        "INSERT INTO pool_xref (pool_id, namespace, ext_id) VALUES ('pool-a', 'geo_sport', 'x.1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pool_xref (pool_id, namespace, ext_id) "
            "VALUES ('pool-b', 'geo_sport', 'x.1')"
        )


def test_alias_for_missing_pool_is_rejected_by_foreign_key() -> None:
    conn = open_db(":memory:")  # open_db enables PRAGMA foreign_keys = ON
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pool_alias (pool_id, alias, norm) VALUES ('ghost', 'G', 'g')")


def test_deleting_a_pool_cascades_to_its_crosswalk() -> None:
    conn = open_db(":memory:")
    _add_pool(conn, "pool-a")
    conn.execute("INSERT INTO pool_alias (pool_id, alias, norm) VALUES ('pool-a', 'A', 'a')")
    conn.execute("INSERT INTO pool_xref (pool_id, namespace, ext_id) VALUES ('pool-a', 'n', 'e')")
    conn.execute("DELETE FROM pool WHERE id = 'pool-a'")
    assert conn.execute("SELECT COUNT(*) FROM pool_alias").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pool_xref").fetchone()[0] == 0
