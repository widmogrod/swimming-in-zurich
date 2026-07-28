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
from swimzh.domain.models import BasinSource, Facility, PoolId
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import GoldRepository, open_db

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
# Since S3 the roster is a `build_store` argument sourced from the WFS. The committed
# catalog.json IS that WFS snapshot, so it is the recorded roster double for these build tests.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))

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
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    curated = _curated_yaml_facilities()

    # The curated (scheduled) pools land on the read path — nothing dropped or invented by the
    # flip. Both Slice-F prose pools AND the reconciliation slice's lane-plan-only pools are
    # SCHEDULE-LESS; isolate the scheduled ones (those with a schedule rule) for the parity check.
    scheduled_curated = {pid: f for pid, f in curated.items() if any(b.rules for b in f.basins)}
    scheduled = {pid: f for pid, f in new_read.items() if any(b.rules for b in f.basins)}
    assert set(scheduled) == set(scheduled_curated)
    assert set(scheduled) == {
        "hallenbad-city",
        "hallenbad-oerlikon",
        "hallenbad-bungertwies",
        "schulschwimmanlage-aemtler",
    }

    # Everything but geo is identical: the schedule/identity/basins/prices the read path serves
    # is unchanged by the flip.
    for pool_id in scheduled:
        assert _without_geo(scheduled[pool_id]) == _without_geo(scheduled_curated[pool_id]), pool_id

    # Schedule-less read-path pools are of THREE kinds (S1 added the third). Pin each exactly so a
    # catalog/curation change surfaces here, not silently: location-only pools (ZERO basins — the
    # universal-detail remainder), Slice-F prose pools (all PARSED_PROSE basins), and lane-plan-only
    # curated pools (CURATED basins carrying only a `lane_plan_source`).
    schedule_less = {pid for pid, f in new_read.items() if not any(b.rules for b in f.basins)}
    location_only = {pid for pid in schedule_less if not new_read[pid].basins}
    assert "freibad-heuried" in location_only  # S1: the exemplar outdoor pin, zero basins
    assert location_only, "S1: every catalog pool that names no basin is a location-only blob"
    with_basins = schedule_less - location_only
    prose = {
        pid
        for pid in with_basins
        if all(b.physical_source is BasinSource.PARSED_PROSE for b in new_read[pid].basins)
    }
    assert prose == {"hallenbad-altstetten", "strandbad-tiefenbrunnen"}
    for pid in prose:
        assert new_read[pid].basins
    lane_only = with_basins - prose
    assert lane_only == {"hallenbad-leimbach", "hallenbad-blaesi", "waermebad-kaeferberg"}
    for pid in lane_only:
        basins = new_read[pid].basins
        assert basins and all(b.lane_plan_source is not None for b in basins)


def test_geo_divergence_is_by_design_catalog_over_yaml(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    conn = open_db(db)

    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    curated = _curated_yaml_facilities()
    catalog = {
        e.pool_id: e.geo
        for e in catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    }

    # The read path (pool.facility_doc) serves the authoritative committed-catalog geo — for the
    # curated pools AND the Slice-F prose pools (both stamp `entry.geo`).
    for pool_id, facility in new_read.items():
        assert facility.geo == catalog[pool_id]

    # …and for the 3 shifted pools that is genuinely different from the curated YAML geo. Only a
    # curated pool that actually authored a YAML geo can diverge; the lane-plan-only pools declare
    # no geo (None), so they are excluded rather than counted as a trivial divergence.
    diverged = {
        pid
        for pid in curated
        if curated[pid].geo is not None and new_read[pid].geo != curated[pid].geo
    }
    assert diverged == _GEO_SHIFTED


def test_get_by_id_reads_pool_facility_doc(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    repo = GoldRepository(open_db(db))

    city = repo.get(PoolId("hallenbad-city"))
    assert city is not None and str(city.identity.facility_id) == "hallenbad-city"
    # An uncurated roster pool has a NULL facility_doc → no schedule blob to read.
    assert repo.get(PoolId("does-not-exist")) is None
