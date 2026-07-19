"""The gold store: SQLite as the single source of truth the query surface reads from.

Each facility is one row: queryable columns (id, name, kind, lat, lon, freshness) for
listing/location filtering, plus a `doc` column holding the faithful JSON of the full
domain `Facility` (via `codec`). `GoldRepository.load_all()` rehydrates domain objects for
`find_swim_options`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility, FacilityId
from swimzh.storage import calendar_codec, catalog_json, codec

# One store, three tables: `facility` (with schedules), `catalog` (every known pool), and
# `calendar` (the Zürich overlay as a single JSON row). All `CREATE TABLE IF NOT EXISTS`, so
# opening a pre-existing facility-only DB is backward-compatible — the new tables are added.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS facility (
    facility_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    lat           REAL,
    lon           REAL,
    valid_as_of   TEXT,
    fetched_at    TEXT,
    doc           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog (
    pool_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    lat           REAL,
    lon           REAL,
    url           TEXT,
    doc           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar (
    id            TEXT PRIMARY KEY,
    doc           TEXT NOT NULL
);
"""

_CALENDAR_ROW_ID = "singleton"


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a gold database with the schema applied."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def write_facilities(conn: sqlite3.Connection, facilities: tuple[Facility, ...]) -> None:
    """Upsert facilities into the gold store (idempotent on facility_id)."""
    rows = [
        (
            str(f.identity.facility_id),
            f.identity.name,
            f.identity.kind.value,
            f.geo.lat if f.geo is not None else None,
            f.geo.lon if f.geo is not None else None,
            f.provenance.valid_as_of.isoformat() if f.provenance.valid_as_of is not None else None,
            f.provenance.fetched_at.isoformat() if f.provenance.fetched_at is not None else None,
            codec.dumps(f),
        )
        for f in facilities
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO facility "
        "(facility_id, name, kind, lat, lon, valid_as_of, fetched_at, doc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def write_catalog(conn: sqlite3.Connection, entries: tuple[PoolCatalogEntry, ...]) -> None:
    """Upsert catalog entries into the gold store (idempotent on pool_id)."""
    rows = [
        (
            e.pool_id,
            e.name,
            e.kind.value,
            e.geo.lat if e.geo is not None else None,
            e.geo.lon if e.geo is not None else None,
            e.url,
            catalog_json.entry_dumps(e),
        )
        for e in entries
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO catalog (pool_id, name, kind, lat, lon, url, doc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def load_catalog(conn: sqlite3.Connection) -> tuple[PoolCatalogEntry, ...]:
    """Rehydrate every catalog entry from the gold store, ordered by pool_id."""
    cursor = conn.execute("SELECT doc FROM catalog ORDER BY pool_id")
    return tuple(catalog_json.entry_loads(row[0]) for row in cursor.fetchall())


def write_calendar(conn: sqlite3.Connection, calendar: ZurichCalendar) -> None:
    """Persist the Zürich calendar as the store's single `calendar` row (idempotent)."""
    conn.execute(
        "INSERT OR REPLACE INTO calendar (id, doc) VALUES (?, ?)",
        (_CALENDAR_ROW_ID, calendar_codec.dumps(calendar)),
    )
    conn.commit()


def load_calendar(conn: sqlite3.Connection) -> ZurichCalendar:
    """Rehydrate the Zürich calendar; raise if the store has none (build it first)."""
    cursor = conn.execute("SELECT doc FROM calendar WHERE id = ?", (_CALENDAR_ROW_ID,))
    row = cursor.fetchone()
    if row is None:
        raise LookupError("gold store has no calendar row; build the store first")
    return calendar_codec.loads(row[0])


class GoldRepository:
    """Read side over the gold store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def load_all(self) -> tuple[Facility, ...]:
        cursor = self._conn.execute("SELECT doc FROM facility ORDER BY facility_id")
        return tuple(codec.loads(row[0]) for row in cursor.fetchall())

    def get(self, facility_id: FacilityId) -> Facility | None:
        cursor = self._conn.execute(
            "SELECT doc FROM facility WHERE facility_id = ?", (str(facility_id),)
        )
        row = cursor.fetchone()
        return codec.loads(row[0]) if row is not None else None

    def count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM facility")
        return int(cursor.fetchone()[0])
