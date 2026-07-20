"""S1 — curated identity is re-keyed to the catalog slug namespace, losslessly.

These guard the unblocker slice of pool-identity-unification:

- Referential integrity: every curated `facility_id` (both registry identities and the
  per-pool schedule files) is a `catalog.json` `pool_id`. Before S1 the two id namespaces
  were disjoint (`city` vs `hallenbad-city`); this asserts they now share one key.
- Lossless legacy ids: every pre-unification short id (`city`, `oerlikon`, …) still
  resolves to its canonical `pool.id` via the `pool_alias` crosswalk in a built gold store —
  no lookup path is lost. Asserted off the DB spine, independent of any registry accessor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swimzh.core.normalize import normalize
from swimzh.core.result import Ok
from swimzh.domain.catalog import slug
from swimzh.etl.build import build_store
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import open_db

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


@pytest.fixture(scope="module")
def gold_conn(tmp_path_factory: pytest.TempPathFactory) -> sqlite3.Connection:
    # Build a complete, self-contained gold store from committed inputs, offline (no network),
    # so the lossless-cutover invariant is proved off the DB-enforced identity spine the app
    # runs against — not off any in-memory registry accessor.
    db = tmp_path_factory.mktemp("gold") / "gold.sqlite"
    result = build_store(DATA_DIR, db)
    assert isinstance(result, Ok), result
    return open_db(db)


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


def test_legacy_short_ids_resolve_via_pool_alias(gold_conn: sqlite3.Connection) -> None:
    # Lossless cutover, asserted off the DB: every pre-unification short id resolves through
    # the `pool_alias` crosswalk (keyed on the normalized form) to exactly one canonical
    # `pool.id`. Falsifiable — a dropped alias yields zero rows and this fails.
    live_pool_ids = {row[0] for row in gold_conn.execute("SELECT id FROM pool")}
    for legacy, canonical in LEGACY_IDS.items():
        rows = gold_conn.execute(
            "SELECT pool_id FROM pool_alias WHERE norm = ?", (normalize(legacy),)
        ).fetchall()
        # Exactly one — `pool_alias.norm` is UNIQUE, so a hit is a single canonical pool.
        assert len(rows) == 1, f"legacy id {legacy!r} lost from pool_alias: {rows}"
        (pool_id,) = rows[0]
        assert pool_id == canonical, (legacy, pool_id, canonical)
        # …and that canonical id is a live pool row (the alias points at a real pool).
        assert pool_id in live_pool_ids, (legacy, pool_id)


def test_legacy_ids_map_onto_live_pools(gold_conn: sqlite3.Connection) -> None:
    # Each legacy target is itself a real `pool` row (the alias resolves to a live pool).
    live_pool_ids = {row[0] for row in gold_conn.execute("SELECT id FROM pool")}
    assert set(LEGACY_IDS.values()) <= live_pool_ids
