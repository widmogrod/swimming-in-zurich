"""S1 — curated identity is re-keyed to the catalog slug namespace, losslessly.

These guard the unblocker slice of pool-identity-unification:

- Referential integrity: every curated `facility_id` (both registry identities and the
  per-pool schedule files) is a `catalog.json` `pool_id`. Before S1 the two id namespaces
  were disjoint (`city` vs `hallenbad-city`); this asserts they now share one key.
- Lossless legacy ids: every pre-unification short id (`city`, `oerlikon`, …) still
  resolves to its canonical slug via `Registry.resolve_name` — no lookup path is lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.domain.catalog import slug
from swimzh.domain.models import FacilityId
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.storage import catalog_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# The pre-unification short ids and the canonical catalog slug each now points at.
LEGACY_IDS: dict[str, str] = {
    "city": "hallenbad-city",
    "oerlikon": "hallenbad-oerlikon",
    "bungertwies": "hallenbad-bungertwies",
    "aemtler": "schulschwimmanlage-aemtler",
    "altstetten": "hallenbad-altstetten",
    "blaesi": "hallenbad-blaesi",
    "leimbach": "hallenbad-leimbach",
    "kaeferberg": "waermebad-kaeferberg",
}


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


@pytest.fixture(scope="module")
def catalog_ids() -> frozenset[str]:
    text = (DATA_DIR / "catalog.json").read_text(encoding="utf-8")
    return frozenset(e.pool_id for e in catalog_json.loads(text))


def test_registry_ids_are_catalog_pool_ids(dataset: Dataset, catalog_ids: frozenset[str]) -> None:
    # Referential integrity: the registry keys on the catalog slug namespace, so every
    # identity joins to its catalog entry by one shared id.
    missing = {str(fid) for fid in dataset.registry.identities} - catalog_ids
    assert missing == set(), f"registry ids not present in catalog.json: {sorted(missing)}"


def test_curated_pool_files_key_on_catalog_ids(
    dataset: Dataset, catalog_ids: frozenset[str]
) -> None:
    # Each curated schedule file's facility_id is a catalog pool_id — /swim ↔ /pools can join.
    missing = {str(f.identity.facility_id) for f in dataset.facilities} - catalog_ids
    assert missing == set(), f"curated pool ids not present in catalog.json: {sorted(missing)}"


def test_canonical_ids_are_the_name_slug(dataset: Dataset) -> None:
    # The canonical id is exactly slug(name) — the same minting the catalog uses.
    for identity in dataset.registry.identities.values():
        assert str(identity.facility_id) == slug(identity.name)


def test_legacy_short_ids_still_resolve_by_lookup(dataset: Dataset) -> None:
    # Lossless: every pre-unification short id resolves to its canonical slug.
    for legacy, canonical in LEGACY_IDS.items():
        resolved = dataset.registry.resolve_name(legacy)
        assert resolved == FacilityId(canonical), (legacy, resolved, canonical)


def test_legacy_ids_map_onto_registered_identities(dataset: Dataset) -> None:
    # Each legacy target is itself a real registry key (the alias points at a live pool).
    registered = {str(fid) for fid in dataset.registry.identities}
    assert set(LEGACY_IDS.values()) <= registered
