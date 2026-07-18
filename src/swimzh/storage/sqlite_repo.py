"""The gold store: SQLite as the single source of truth the query surface reads from.

Each facility is one row: queryable columns (id, name, kind, lat, lon, freshness) for
listing/location filtering, plus a `doc` column holding the faithful JSON of the full
domain `Facility` (via `codec`). `GoldRepository.load_all()` rehydrates domain objects for
`find_swim_options`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from swimzh.domain.models import Facility, FacilityId
from swimzh.storage import codec

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
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a gold database with the schema applied."""
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
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
