"""The seed loader assembles the identity spine from committed inputs.

Acceptance for S2's spine content: exactly 57 pool rows with correct derived statuses, the
Käferberg kind decision (curated-wins → thermal), and a crosswalk whose lookups resolve every
alias/xref to its canonical id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.build.reconcile import Name, Xref
from swimzh.build.seed import build_crosswalk, build_spine
from swimzh.core.result import Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import BasinSource, PoolId, PoolKind
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.storage import catalog_json, codec
from swimzh.storage.rows import PoolSpine

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
    # Curation is not stored on the spine; it is derived from `facility_doc` by the single
    # shared rule (`codec.is_curated`) — the same predicate for every consumer.
    curated = {p.id for p in spine.pools if codec.is_curated(p.facility_doc)}
    # Exactly the curated facilities that carry at least one basin with a rule.
    expected = {
        PoolId(str(f.identity.facility_id))
        for f in dataset.facilities
        if any(b.rules for b in f.basins)
    }
    assert curated == expected
    assert len(curated) == 4
    # The remaining 53 roster pools derive uncurated.
    assert sum(1 for p in spine.pools if not codec.is_curated(p.facility_doc)) == 53


def test_curated_pools_carry_a_facility_blob_uncurated_carry_at_most_prose(
    spine: PoolSpine,
) -> None:
    for p in spine.pools:
        if codec.is_curated(p.facility_doc):
            assert p.facility_doc is not None
        else:
            # S1: every catalog pool now carries a non-NULL blob, but an uncurated one is always
            # SCHEDULE-LESS (no rule → no `/swim` option). It is one of three kinds: a location-only
            # pool (ZERO basins — an outdoor pin like Freibad Heuried whose prose names no basin), a
            # Slice-F prose pool (auto-extracted PARSED_PROSE basins), or a lane-plan-only pool (a
            # hand-authored CURATED basin carrying only a `lane_plan_source` — leimbach/blaesi/
            # käferberg). All three are legitimately uncurated.
            assert p.facility_doc is not None  # S1: no roster pool has a NULL blob any more
            facility = codec.loads(p.facility_doc)
            assert not any(b.rules for b in facility.basins)
            for basin in facility.basins:
                if basin.physical_source is BasinSource.PARSED_PROSE:
                    continue  # prose pool
                # otherwise a lane-plan-only curated basin: it must carry a lane_plan_source
                assert basin.lane_plan_source is not None


def test_facility_doc_geo_equals_committed_catalog_geo(
    spine: PoolSpine, catalog: tuple[PoolCatalogEntry, ...]
) -> None:
    # B1 parity: the geo carried inside `pool.facility_doc` equals the committed `data/catalog.json`
    # (= WFS) geo — compared OFFLINE against the committed catalog, never a live WFS merge. This is
    # the coordinate the offline read path serves (Plan C deleted the `facility` table), so it must
    # match the authoritative catalog here. Slice F extends the blob-bearing set beyond the 4
    # curated pools (prose pools also stamp `entry.geo`), so the parity is asserted for every blob.
    catalog_geo = {e.pool_id: e.geo for e in catalog}
    rows_with_doc = [p for p in spine.pools if p.facility_doc is not None]
    assert len(rows_with_doc) >= 4  # the 4 curated pools, plus any Slice-F prose pools
    for row in rows_with_doc:
        assert row.facility_doc is not None
        facility = codec.loads(row.facility_doc)
        assert facility.geo == catalog_geo[str(row.id)]


def test_build_extracts_parsed_prose_basins_for_a_location_only_pool(spine: PoolSpine) -> None:
    # Slice F acceptance: Hallenbad Altstetten is in the catalog but absent from the curated
    # dataset (location-only). Its WFS `infrastruktur` prose names swimmable basins, so the build
    # mints a SCHEDULE-LESS facility of PARSED_PROSE basins + amenity features.
    row = next(p for p in spine.pools if p.id == PoolId("hallenbad-altstetten"))
    assert row.facility_doc is not None
    facility = codec.loads(row.facility_doc)
    assert facility.provenance.curated is False
    assert facility.basins  # the prose named basins
    assert all(b.physical_source is BasinSource.PARSED_PROSE for b in facility.basins)
    assert all(b.rules == () for b in facility.basins)  # schedule-less (Decision #5)
    # The diving basin carries its parsed platform heights, and amenity Features were emitted.
    diving = next(b for b in facility.basins if b.diving_platforms_m)
    assert diving.diving_platforms_m  # e.g. (1, 3, 5) from "Sprungbecken 1/3/5m"
    assert facility.features  # sauna/steam/slide/… from the non-Becken segments


def test_every_catalog_pool_has_a_non_null_facility_doc(
    spine: PoolSpine, catalog: tuple[PoolCatalogEntry, ...]
) -> None:
    # S1: universal detail. Every one of the ~57 catalog pools now carries a non-NULL
    # `facility_doc`, so `/pools/{id}` never 404s for a real catalog pin (Heuried included).
    assert len(spine.pools) == len(catalog) == 57
    assert all(p.facility_doc is not None for p in spine.pools)


def test_location_only_pool_is_zero_basin_and_uncurated(spine: PoolSpine) -> None:
    # S1: Freibad Heuried is an outdoor pin whose catalog description is the literal "NULL" (no
    # prose basins). It gets a location-only facility with ZERO basins that stays uncurated — so
    # it is viewable in detail but never a `/swim` option.
    row = next(p for p in spine.pools if p.id == PoolId("freibad-heuried"))
    assert row.facility_doc is not None
    facility = codec.loads(row.facility_doc)
    assert facility.basins == ()  # location-only: no basin at all
    assert facility.provenance.curated is False
    assert codec.is_curated(row.facility_doc) is False


def test_uncurated_pool_with_registry_entry_keeps_its_identity(spine: PoolSpine) -> None:
    # S1 (round-2 fix): the location-only mint builds its `PoolIdentity` from `registry.get(id)`
    # when a registry entry exists — so an *uncurated* pool's external identity fields survive the
    # mint AND the gold round-trip (dumps in `build_spine` → `codec.loads` here). This is the exact
    # seam S2's `baditicker_poiid` rides on; here the authored `aliases` prove a REGISTRY identity
    # (not a bare `PoolIdentity(id, name, kind)`, whose aliases/keys would be empty) reached it.
    row = next(p for p in spine.pools if p.id == PoolId("freibad-heuried"))
    assert row.facility_doc is not None
    identity = codec.loads(row.facility_doc).identity
    assert identity.aliases == ("heuried", "Freibad Heuried")  # authored registry aliases survive
    assert identity.crowdmonitor_keys == ()  # empty as authored (round-trips faithfully)


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


def test_crosswalk_resolves_aliases_and_xrefs(spine: PoolSpine) -> None:
    crosswalk = build_crosswalk(spine)
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
