"""The gold store: SQLite as the single source of truth the query surface reads from.

The identity spine is one ``pool`` table (all ~57 published pools, canonical id PK, a
**derived** ``curation_status``), plus its DB-enforced crosswalk: ``pool_alias`` with a
global ``UNIQUE(norm)`` and ``pool_xref`` with ``UNIQUE(namespace, ext_id)`` — so "same
entity → two ids" is a write-time ``IntegrityError``, not a convention. These are ``STRICT``
tables and their FKs cascade from ``pool``. The curated schedule payload rides as a typed
blob on the ``pool`` row (``facility_doc``); row-normalizing it is a later plan.

The legacy ``facility`` table (queryable columns + a full-``Facility`` ``doc`` blob) is kept
transiently as the ``/swim`` schedule read path and the network-enrichment write target; it
is retired when the app and scrapers are rewired to the ``pool`` spine.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry, RosterEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import Facility, FacilityId
from swimzh.storage import calendar_codec, codec
from swimzh.storage.codec import _KIND_FROM

if TYPE_CHECKING:
    from swimzh.build.seed import PoolSpine

# The identity spine (`pool` + `pool_alias` + `pool_xref`) alongside the transitional
# `facility` table and the singleton `calendar` row. All `CREATE TABLE IF NOT EXISTS`, so an
# existing store gains the spine additively. `STRICT` + `UNIQUE` + FK `ON DELETE CASCADE` make
# the split-brain (one pool, two ids) an unrepresentable write.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pool (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    address         TEXT NOT NULL,
    lat             REAL,
    lon             REAL,
    url             TEXT,
    description     TEXT,
    phone           TEXT,
    curation_status TEXT NOT NULL CHECK (curation_status IN ('curated', 'uncurated')),
    facility_doc    TEXT
) STRICT;
CREATE TABLE IF NOT EXISTS pool_alias (
    pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    norm    TEXT NOT NULL,
    UNIQUE(norm)
) STRICT;
CREATE TABLE IF NOT EXISTS pool_xref (
    pool_id   TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    ext_id    TEXT NOT NULL,
    UNIQUE(namespace, ext_id)
) STRICT;
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
CREATE TABLE IF NOT EXISTS calendar (
    id            TEXT PRIMARY KEY,
    doc           TEXT NOT NULL
);
"""

_CALENDAR_ROW_ID = "singleton"


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a gold database with the schema + FK enforcement applied."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
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


def write_pools(conn: sqlite3.Connection, spine: PoolSpine) -> None:
    """Write the identity spine (``pool`` + ``pool_alias`` + ``pool_xref``).

    The write side is typed on ``PoolSpine`` — whose rows carry a ``PoolId`` minted only by
    ``build.seed``/``build.reconcile`` — so no caller can reach a ``pool`` row without a
    reconciled id. A full replace (cascade-clearing the crosswalk) keeps a re-build idempotent
    and its rows deterministic.
    """
    conn.execute("DELETE FROM pool")  # FK ON DELETE CASCADE clears alias/xref too
    conn.executemany(
        "INSERT INTO pool "
        "(id, name, kind, address, lat, lon, url, description, phone, "
        "curation_status, facility_doc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                str(p.id),
                p.name,
                p.kind.value,
                p.address,
                p.geo.lat if p.geo is not None else None,
                p.geo.lon if p.geo is not None else None,
                p.url,
                p.description,
                p.phone,
                p.curation_status,
                p.facility_doc,
            )
            for p in spine.pools
        ],
    )
    conn.executemany(
        "INSERT INTO pool_alias (pool_id, alias, norm) VALUES (?, ?, ?)",
        [(str(a.pool_id), a.alias, a.norm) for a in spine.aliases],
    )
    conn.executemany(
        "INSERT INTO pool_xref (pool_id, namespace, ext_id) VALUES (?, ?, ?)",
        [(str(x.pool_id), x.namespace, x.ext_id) for x in spine.xrefs],
    )
    conn.commit()


def load_alias_rows(conn: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    """Project ``pool_alias`` to plain ``(norm, pool_id)`` pairs — the reconcile-lookup input.

    Returns strings, not ``PoolId``s: minting the canonical id from these rows is
    ``build.reconcile``'s job (``crosswalk_from_rows``), keeping the two allowed minting seams.
    """
    cursor = conn.execute("SELECT norm, pool_id FROM pool_alias")
    return tuple((str(norm), str(pool_id)) for norm, pool_id in cursor.fetchall())


def load_xref_rows(conn: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    """Project ``pool_xref`` to ``(namespace, ext_id, pool_id)`` string triples (not ids)."""
    cursor = conn.execute("SELECT namespace, ext_id, pool_id FROM pool_xref")
    return tuple(
        (str(namespace), str(ext_id), str(pool_id))
        for namespace, ext_id, pool_id in cursor.fetchall()
    )


def load_catalog(conn: sqlite3.Connection) -> tuple[PoolCatalogEntry, ...]:
    """Rehydrate the full pool roster from the ``pool`` spine, ordered by canonical id.

    The catalog listing (``/pools``) now serves from the same identity spine as ``/swim`` —
    one store, joinable by ``pool.id``.
    """
    cursor = conn.execute(
        "SELECT id, name, kind, address, lat, lon, url, description, phone FROM pool ORDER BY id"
    )
    return tuple(_catalog_entry(row) for row in cursor.fetchall())


def load_roster(conn: sqlite3.Connection) -> tuple[RosterEntry, ...]:
    """Rehydrate the full roster (all ~57 pools) from the ``pool`` spine, ordered by canonical
    id, each carrying its **derived** ``curation_status`` as a ``curated`` flag.

    This is the single read that backs both ``/pools`` (catalog + schedule indicator) and the
    runtime ``uncurated = roster − scheduled`` computation — one store, joinable by ``pool.id``.
    """
    cursor = conn.execute(
        "SELECT id, name, kind, address, lat, lon, url, description, phone, curation_status "
        "FROM pool ORDER BY id"
    )
    return tuple(_roster_entry(row) for row in cursor.fetchall())


def _roster_entry(row: tuple[Any, ...]) -> RosterEntry:
    *catalog_cols, curation_status = row
    return RosterEntry(
        entry=_catalog_entry(tuple(catalog_cols)),
        curated=str(curation_status) == "curated",
    )


def _catalog_entry(row: tuple[Any, ...]) -> PoolCatalogEntry:
    pool_id, name, kind, address, lat, lon, url, description, phone = row
    geo = GeoPoint(lat=float(lat), lon=float(lon)) if lat is not None and lon is not None else None
    return PoolCatalogEntry(
        pool_id=str(pool_id),
        name=str(name),
        kind=_KIND_FROM[str(kind)],
        address=str(address),
        geo=geo,
        url=str(url) if url is not None else None,
        description=str(description) if description is not None else None,
        phone=str(phone) if phone is not None else None,
    )


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
