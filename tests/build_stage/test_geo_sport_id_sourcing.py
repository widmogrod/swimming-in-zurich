"""S5b: `geo_sport_id` is SOURCED from the WFS `poi_id`, not the registry crosswalk.

The roster carries each layer's `poi_id` (e.g. `hb001`); `build_spine` stamps it as the facility's
`geo_sport_id`. These tests pin the flow end to end — `poi_id` through `build_catalog` into the
serialized `facility_doc` — and that the registry no longer carries the (retired) placeholder.

The real `poi_id` values live in the recorded indoor `geo_sport` cassette (hb001–hb007), replayed
offline via `recorded_indoor_client_with_poi_ids()` (no live network, no VCR record-mode).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.boundary.curated_dto import IdentityDTO
from swimzh.build.seed import build_spine
from swimzh.core.result import Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.domain.registry import Registry
from swimzh.etl.catalog import build_catalog
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.providers.geo_sport import GeoPool, fetch_indoor_pools
from swimzh.storage import codec
from tests.providers.wfs_snapshot import recorded_indoor_client_with_poi_ids

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# The recorded indoor WFS layer's poi_id per pool (the canonical spine id → its WFS poi_id).
EXPECTED_POI_IDS = {
    "hallenbad-city": "hb001",
    "hallenbad-bungertwies": "hb002",
    "hallenbad-altstetten": "hb003",
    "hallenbad-oerlikon": "hb004",
    "hallenbad-blaesi": "hb005",
    "hallenbad-leimbach": "hb006",
    "waermebad-kaeferberg": "hb007",
}


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def _geo_pool(poi_id: str | None, name: str) -> GeoPool:
    return GeoPool(
        source_id=f"poi_hallenbad_view.{name}",
        poi_id=poi_id,
        name=name,
        kind=PoolKind.INDOOR,
        address="Somewhere 1, 8000 Zürich",
        geo=GeoPoint(lat=47.37, lon=8.54),
        url=None,
        category=None,
        description=None,
        phone=None,
    )


def test_build_catalog_carries_poi_id_from_the_wfs_pool() -> None:
    # The roster projection keeps the WFS `poi_id` (previously discarded) on the catalog entry —
    # the field the spine later stamps as `geo_sport_id`.
    pools = [_geo_pool("hb042", "Hallenbad Example"), _geo_pool(None, "Freibad No Poi")]
    entries = {e.name: e for e in build_catalog(pools)}
    assert entries["Hallenbad Example"].poi_id == "hb042"
    assert entries["Freibad No Poi"].poi_id is None  # a null WFS poi_id stays None, not ""


def test_spine_geo_sport_id_equals_wfs_poi_id(dataset: Dataset) -> None:
    # End to end against the recorded indoor WFS layer: fetch → build_catalog → build_spine, then
    # read the serialized facility_doc. Every indoor pool's stored `geo_sport_id` equals its WFS
    # `poi_id` — the S5b acceptance.
    fetched = fetch_indoor_pools(recorded_indoor_client_with_poi_ids())
    assert isinstance(fetched, Ok), fetched
    catalog = build_catalog(fetched.value)

    # The roster projection itself carries the poi_id for every recorded indoor pool.
    by_id = {e.pool_id: e for e in catalog}
    assert {pid: by_id[pid].poi_id for pid in EXPECTED_POI_IDS} == EXPECTED_POI_IDS

    spine = build_spine(catalog, dataset.facilities, dataset.registry)
    docs = {str(p.id): p.facility_doc for p in spine.pools}
    for pool_id, poi_id in EXPECTED_POI_IDS.items():
        doc = docs[pool_id]
        assert doc is not None
        identity = codec.loads(doc).identity
        assert identity.geo_sport_id == poi_id, pool_id


def test_spine_sources_geo_sport_id_for_a_pool_with_no_registry_entry() -> None:
    # A bare location-only pool (no registry identity at all) still gets its `geo_sport_id` from
    # the roster `poi_id` — the sourcing does not depend on a curated crosswalk row existing.
    entry = PoolCatalogEntry(
        pool_id="freibad-brand-new",
        name="Freibad Brand New",
        kind=PoolKind.OUTDOOR,
        address="Neu 1, 8000 Zürich",
        geo=GeoPoint(lat=47.37, lon=8.54),
        url=None,
        description=None,
        phone=None,
        poi_id="fb099",
    )
    spine = build_spine((entry,), facilities=(), registry=Registry([]))
    (row,) = spine.pools
    assert row.facility_doc is not None
    assert codec.loads(row.facility_doc).identity.geo_sport_id == "fb099"


def test_geo_sport_xref_is_built_from_the_wfs_poi_id(dataset: Dataset) -> None:
    # The pool_xref geo_sport rows are keyed by the sourced poi_id (previously the registry
    # placeholder was null, so no geo_sport xref existed at all).
    fetched = fetch_indoor_pools(recorded_indoor_client_with_poi_ids())
    assert isinstance(fetched, Ok), fetched
    spine = build_spine(build_catalog(fetched.value), dataset.facilities, dataset.registry)
    geo_sport = {str(x.pool_id): x.ext_id for x in spine.xrefs if x.namespace == "geo_sport"}
    for pool_id, poi_id in EXPECTED_POI_IDS.items():
        assert geo_sport[pool_id] == poi_id, pool_id


def test_registry_dto_no_longer_carries_geo_sport_id() -> None:
    # Structural guard for "stop reading the placeholder": the crosswalk DTO deliberately dropped
    # the field, so a stray `geo_sport_id:` in registry.yaml would now be an extra-forbidden error
    # rather than a silently-read null.
    assert "geo_sport_id" not in IdentityDTO.model_fields
