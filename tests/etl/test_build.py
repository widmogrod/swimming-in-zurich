"""B1/B2 parity: the read path (``pool.facility_doc``) serves the curated schedules with the
authoritative committed-catalog geo stamped onto them, for an offline build.

The now-deleted ``facility`` table (Plan C) used to carry the raw curated YAML coords; the
equivalent source is the curated dataset (``load_dataset``) it was built from. So the parity
assertion normalizes geo out and compares everything else (identity, basins/schedule, prices,
closures, amenities, …) against the raw curated facilities; a companion assertion pins the
by-design geo *shift* — ``pool.facility_doc`` carries the committed ``catalog.json`` geo (B1),
which for the shifted pools genuinely differs from the curated YAML — so it can never regress
into a silent full-equality expectation.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from swimzh.core.result import Ok
from swimzh.domain.models import Facility, PoolId
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import GoldRepository, open_db

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# The curated pools whose YAML coords differ from the committed catalog (per B1's ledger:
# bungertwies, oerlikon, city shift; aemtler is identical).
_GEO_SHIFTED = {"hallenbad-bungertwies", "hallenbad-oerlikon", "hallenbad-city"}


def _curated_yaml_facilities() -> dict[str, Facility]:
    """The raw curated facilities (YAML geo) — the content the retired ``facility`` table held."""
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return {str(f.identity.facility_id): f for f in result.value.facilities}


def _without_geo(f: Facility) -> Facility:
    return replace(f, geo=None)


def test_pool_facility_doc_read_matches_curated_dataset_modulo_geo(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    curated = _curated_yaml_facilities()

    # Same curated pools land on the read path — nothing dropped or invented by the flip.
    assert set(new_read) == set(curated)
    assert set(new_read) == {
        "hallenbad-city",
        "hallenbad-oerlikon",
        "hallenbad-bungertwies",
        "schulschwimmanlage-aemtler",
    }

    # Everything but geo is identical: the schedule/identity/basins/prices the read path serves
    # is unchanged by the flip.
    for pool_id in new_read:
        assert _without_geo(new_read[pool_id]) == _without_geo(curated[pool_id]), pool_id


def test_geo_divergence_is_by_design_catalog_over_yaml(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    curated = _curated_yaml_facilities()
    catalog = {
        e.pool_id: e.geo
        for e in catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    }

    # The read path (pool.facility_doc) serves the authoritative committed-catalog geo…
    for pool_id, facility in new_read.items():
        assert facility.geo == catalog[pool_id]

    # …and for the 3 shifted pools that is genuinely different from the curated YAML geo.
    diverged = {pid for pid in new_read if new_read[pid].geo != curated[pid].geo}
    assert diverged == _GEO_SHIFTED


def test_get_by_id_reads_pool_facility_doc(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    repo = GoldRepository(open_db(db))

    city = repo.get(PoolId("hallenbad-city"))
    assert city is not None and str(city.identity.facility_id) == "hallenbad-city"
    # An uncurated roster pool has a NULL facility_doc → no schedule blob to read.
    assert repo.get(PoolId("does-not-exist")) is None
