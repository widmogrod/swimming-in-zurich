"""Gold stage: write conformed facilities into the SQLite source of truth."""

from __future__ import annotations

import sqlite3

from swimzh.domain.models import Facility
from swimzh.storage.sqlite_repo import GoldRepository, write_facilities


def write_gold(conn: sqlite3.Connection, facilities: tuple[Facility, ...]) -> GoldRepository:
    write_facilities(conn, facilities)
    return GoldRepository(conn)
