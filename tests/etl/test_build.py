"""The offline `build_store` read path (``pool.facility_doc``) serves the thin crosswalk — lane
bindings + WFS-prose physicals — with the authoritative committed-catalog geo stamped on, and is
uniformly SCHEDULE-LESS (delete-curated-schedule-tier S3: curated YAML carries no schedule; the
real timetable is composed in by the scrape phase, proven end-to-end in tests/test_cli.py).

Geo is now unambiguously catalog-sourced: curated YAML no longer authors any geo, so there is
nothing left to diverge — every served coordinate is the committed ``catalog.json`` (= WFS) one.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.core.result import Ok
from swimzh.domain.models import BasinId, BasinSource, PoolId
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import GoldRepository, open_db

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
# Since S3 the roster is a `build_store` argument sourced from the WFS. The committed
# catalog.json IS that WFS snapshot, so it is the recorded roster double for these build tests.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))

# The pools whose stripped YAML carries a `lane_plan_source` binding on ≥1 basin.
_LANE_BINDING_POOLS = {
    "hallenbad-city",
    "hallenbad-oerlikon",
    "hallenbad-bungertwies",
    "hallenbad-blaesi",
    "hallenbad-leimbach",
    "waermebad-kaeferberg",
}


def test_build_store_is_schedule_less_and_serves_crosswalk_bindings(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    conn = open_db(db)
    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}

    # Offline build carries NO schedule — every roster pool is schedule-less until the scrape folds
    # the real timetable in. Nothing derives a `/swim` option from `build_store` alone.
    assert all(not any(b.rules for b in f.basins) for f in new_read.values())

    # Every pool whose stripped YAML authors a lane binding surfaces it on ≥1 basin, so the lane
    # phase can attach — the thin-crosswalk binding survives the seed.
    for pid in _LANE_BINDING_POOLS:
        basins = new_read[pid].basins
        assert basins and any(b.lane_plan_source is not None for b in basins), pid

    # WFS `infrastruktur` prose physicals are applied to a curated facility's named basins (S1):
    # City's `Schwimmerbecken` gains 50 x 15 m, Bungertwies its 25 m — sourced, not authored.
    city_lap = next(
        b for b in new_read["hallenbad-city"].basins if b.basin_id == BasinId("city-50m")
    )
    assert city_lap.dimensions is not None and city_lap.physical_source is BasinSource.PARSED_PROSE
    bungertwies = new_read["hallenbad-bungertwies"].basins[0]
    assert bungertwies.dimensions is not None
    # Oerlikon's WFS `infrastruktur` is empty ("NULL") — a recorded physicals drop; basins bare.
    assert all(b.dimensions is None for b in new_read["hallenbad-oerlikon"].basins)

    # Location-only pools (no basin at all): the school pool and outdoor pins.
    assert new_read["schulschwimmanlage-aemtler"].basins == ()
    assert new_read["freibad-heuried"].basins == ()

    # Prose-only pools (PARSED_PROSE basins, no authored lane binding) still mint from prose.
    for pid in ("hallenbad-altstetten", "strandbad-tiefenbrunnen"):
        basins = new_read[pid].basins
        assert basins and all(b.physical_source is BasinSource.PARSED_PROSE for b in basins)
        assert all(b.lane_plan_source is None for b in basins)


def test_geo_is_catalog_sourced_with_no_curated_yaml_divergence(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    conn = open_db(db)
    new_read = {str(f.identity.facility_id): f for f in GoldRepository(conn).load_all()}
    catalog = {
        e.pool_id: e.geo
        for e in catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    }

    # The read path serves the authoritative committed-catalog geo for every pool.
    for pool_id, facility in new_read.items():
        assert facility.geo == catalog[pool_id]

    # Curated YAML no longer authors any geo (delete-curated-schedule-tier S3), so geo is now
    # unambiguously catalog-sourced — nothing can diverge.
    curated = load_dataset(DATA_DIR)
    assert isinstance(curated, Ok)
    assert all(f.geo is None for f in curated.value.facilities)


def test_get_by_id_reads_pool_facility_doc(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    repo = GoldRepository(open_db(db))

    city = repo.get(PoolId("hallenbad-city"))
    assert city is not None and str(city.identity.facility_id) == "hallenbad-city"
    # An uncurated roster pool has a NULL facility_doc → no schedule blob to read.
    assert repo.get(PoolId("does-not-exist")) is None
