"""The seed loader assembles the identity spine from committed inputs.

Acceptance for S2's spine content: exactly 57 pool rows with correct derived statuses, the
Käferberg kind decision (curated-wins → thermal), and a crosswalk whose lookups resolve every
alias/xref to its canonical id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.build.reconcile import Name, Xref
from swimzh.build.seed import CURATED, UNCURATED, PoolSpine, build_crosswalk, build_spine
from swimzh.core.result import Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import PoolId, PoolKind
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.storage import catalog_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


@pytest.fixture(scope="module")
def catalog() -> tuple[PoolCatalogEntry, ...]:
    return catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spine(dataset: Dataset, catalog: tuple[PoolCatalogEntry, ...]) -> PoolSpine:
    return build_spine(catalog, dataset.facilities, dataset.registry)


def test_spine_has_one_row_per_catalog_pool(
    spine: PoolSpine, catalog: tuple[PoolCatalogEntry, ...]
) -> None:
    assert len(spine.pools) == 57 == len(catalog)
    assert {p.id for p in spine.pools} == {PoolId(e.pool_id) for e in catalog}


def test_curation_status_is_derived(spine: PoolSpine, dataset: Dataset) -> None:
    curated = {p.id for p in spine.pools if p.curation_status == CURATED}
    # Exactly the curated facilities that carry at least one basin with a rule.
    expected = {
        PoolId(str(f.identity.facility_id))
        for f in dataset.facilities
        if any(b.rules for b in f.basins)
    }
    assert curated == expected
    assert len(curated) == 4
    # Every other roster pool is uncurated, and only these two statuses ever appear.
    assert {p.curation_status for p in spine.pools} == {CURATED, UNCURATED}


def test_curated_pools_carry_a_facility_blob_uncurated_do_not(spine: PoolSpine) -> None:
    for p in spine.pools:
        if p.curation_status == CURATED:
            assert p.facility_doc is not None
        else:
            assert p.facility_doc is None


def test_kaeferberg_kind_is_curated_wins_thermal(spine: PoolSpine) -> None:
    # S1 discovery: registry says `thermal`, catalog (WFS) says `indoor`. Decision: curated
    # authoring wins (thermal is the richer, hand-verified classification).
    kaeferberg = next(p for p in spine.pools if p.id == PoolId("waermebad-kaeferberg"))
    assert kaeferberg.kind is PoolKind.THERMAL


def test_uncurated_pool_kind_comes_from_catalog(
    spine: PoolSpine, catalog: tuple[PoolCatalogEntry, ...]
) -> None:
    # A pool with no registry/curated authoring keeps the catalog (WFS) kind verbatim.
    by_id = {e.pool_id: e for e in catalog}
    registry_ids = {"waermebad-kaeferberg"}  # the only kind that diverges from catalog
    for p in spine.pools:
        if str(p.id) not in registry_ids:
            assert p.kind is by_id[str(p.id)].kind


def test_crosswalk_resolves_aliases_and_xrefs(spine: PoolSpine, dataset: Dataset) -> None:
    crosswalk = build_crosswalk(spine, dataset.facilities)
    # Every alias resolves to the pool it was minted for.
    for alias_row in spine.aliases:
        assert crosswalk.resolve(Name(alias_row.alias)) == Ok(alias_row.pool_id)
    # Every xref (crowdmonitor key etc.) resolves to its pool.
    for xref_row in spine.xrefs:
        assert crosswalk.resolve(Xref(xref_row.namespace, xref_row.ext_id)) == Ok(xref_row.pool_id)


def test_aliases_have_globally_unique_norms(spine: PoolSpine) -> None:
    norms = [a.norm for a in spine.aliases]
    assert len(norms) == len(set(norms))


def test_xrefs_have_globally_unique_namespace_ext_id(spine: PoolSpine) -> None:
    keys = [(x.namespace, x.ext_id) for x in spine.xrefs]
    assert len(keys) == len(set(keys))
