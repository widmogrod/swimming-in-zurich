"""B2 parity: the flipped read path (``pool.facility_doc``) serves the same schedules the
retired ``facility``-table read path did, for an offline build.

The one *intended* divergence is geo: ``pool.facility_doc`` carries B1's authoritative
committed-catalog coords, while the transitional ``facility`` table still carries the curated
YAML coords. So the parity assertion normalizes geo out and compares everything else
(identity, basins/schedule, prices, closures, amenities, …); a companion assertion pins the
by-design geo *shift* so it can never regress into a silent full-equality expectation.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from swimzh.core.result import Ok
from swimzh.domain.models import Facility, PoolId
from swimzh.etl.build import build_store
from swimzh.storage import catalog_json, codec
from swimzh.storage.sqlite_repo import GoldRepository, open_db

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# The curated pools whose YAML coords differ from the committed catalog (per B1's ledger:
# bungertwies, oerlikon, city shift; aemtler is identical).
_GEO_SHIFTED = {"hallenbad-bungertwies", "hallenbad-oerlikon", "hallenbad-city"}


def _facility_table_read(conn: object) -> dict[str, Facility]:
    """The retired read path, reconstructed inline: ``SELECT doc FROM facility``."""
    cursor = conn.execute("SELECT doc FROM facility ORDER BY facility_id")  # type: ignore[attr-defined]
    facilities = tuple(codec.loads(row[0]) for row in cursor.fetchall())
    return {str(f.identity.facility_id): f for f in facilities}


def _without_geo(f: Facility) -> Facility:
    return replace(f, geo=None)


def test_pool_facility_doc_read_matches_facility_table_read_modulo_geo(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    old_read = _facility_table_read(conn)

    # Same curated pools land on both paths — nothing dropped or invented by the flip.
    assert set(new_read) == set(old_read)
    assert set(new_read) == {
        "hallenbad-city",
        "hallenbad-oerlikon",
        "hallenbad-bungertwies",
        "schulschwimmanlage-aemtler",
    }

    # Everything but geo is identical: the schedule/identity/basins/prices the read path serves
    # is unchanged by the flip.
    for pool_id in new_read:
        assert _without_geo(new_read[pool_id]) == _without_geo(old_read[pool_id]), pool_id


def test_geo_divergence_is_by_design_catalog_over_yaml(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    old_read = _facility_table_read(conn)
    catalog = {
        e.pool_id: e.geo
        for e in catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    }

    # The read path (pool.facility_doc) serves the authoritative committed-catalog geo…
    for pool_id, facility in new_read.items():
        assert facility.geo == catalog[pool_id]

    # …and for the 3 shifted pools that is genuinely different from the facility table's YAML geo.
    diverged = {pid for pid in new_read if new_read[pid].geo != old_read[pid].geo}
    assert diverged == _GEO_SHIFTED


def test_get_by_id_reads_pool_facility_doc(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    repo = GoldRepository(open_db(db))

    city = repo.get(PoolId("hallenbad-city"))
    assert city is not None and str(city.identity.facility_id) == "hallenbad-city"
    # An uncurated roster pool has a NULL facility_doc → no schedule blob to read.
    assert repo.get(PoolId("does-not-exist")) is None
