"""S2 acceptance: the offline build materializes a lossless, deterministic identity spine.

- Cutover is lossless: every legacy id (catalog slug, curated facility id, pre-unification
  short id, crowdmonitor key) lands as a `pool.id` / `pool_alias` / `pool_xref` — asserted
  against the committed source inputs *before* the old `catalog` table is relied on.
- The build is deterministic: building twice yields byte-equal spine rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

from swimzh.core.result import Ok
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.etl.build import build_store
from swimzh.storage import catalog_json, codec

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
# Since S3 the roster is a `build_store` argument sourced from the WFS; the committed catalog.json
# IS that WFS snapshot, so it is the recorded roster double for this offline spine build test.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))

# The pre-unification short ids (S1's crosswalk) — each must still resolve via an alias.
LEGACY_SHORT_IDS: dict[str, str] = {
    "city": "hallenbad-city",
    "oerlikon": "hallenbad-oerlikon",
    "bungertwies": "hallenbad-bungertwies",
    "aemtler": "schulschwimmanlage-aemtler",
    "altstetten": "hallenbad-altstetten",
    "blaesi": "hallenbad-blaesi",
    "leimbach": "hallenbad-leimbach",
    "kaeferberg": "waermebad-kaeferberg",
}


def _build(tmp_path: Path, name: str = "gold.sqlite") -> sqlite3.Connection:
    db = tmp_path / name
    result = build_store(DATA_DIR, db, _ROSTER)
    assert isinstance(result, Ok), result
    return sqlite3.connect(db)


def _catalog_pool_ids() -> set[str]:
    import json

    data = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    return {e["pool_id"] for e in data["entries"]}


def _registry() -> list[dict[str, Any]]:
    data = yaml.safe_load((DATA_DIR / "registry.yaml").read_text(encoding="utf-8"))
    return list(data["facilities"])


def test_build_yields_exactly_57_pool_rows(tmp_path: Path) -> None:
    conn = _build(tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM pool").fetchone()[0] == 57


def test_offline_build_is_schedule_less_freshness_comes_from_the_scrape(tmp_path: Path) -> None:
    conn = _build(tmp_path)
    # Freshness is no longer a stored column: it is derived at read from `facility_doc` by the
    # shared `codec.schedule_freshness` rule (NULL blob → no_source; rules present → scraped).
    # Since delete-curated-schedule-tier S3 curated YAML carries NO schedule, so the OFFLINE
    # `build_store` is uniformly schedule-less — NO pool derives `SCRAPED` here. `SCRAPED` freshness
    # appears only after the atomic build's scrape phase folds the real timetable in (end-to-end in
    # tests/test_cli.py).
    rows = conn.execute("SELECT id, facility_doc FROM pool").fetchall()
    scraped = {
        pool_id
        for pool_id, doc in rows
        if codec.schedule_freshness(doc) is ScheduleFreshness.SCRAPED
    }
    assert scraped == set()
    assert (
        sum(1 for _, doc in rows if codec.schedule_freshness(doc) is not ScheduleFreshness.SCRAPED)
        == 57
    )


def test_cutover_every_catalog_pool_id_is_a_canonical_pool_row(tmp_path: Path) -> None:
    conn = _build(tmp_path)
    ids = {row[0] for row in conn.execute("SELECT id FROM pool")}
    assert _catalog_pool_ids() == ids  # lossless roster: nothing dropped, nothing invented


def test_cutover_legacy_short_ids_resolve_via_alias(tmp_path: Path) -> None:
    conn = _build(tmp_path)
    for legacy, canonical in LEGACY_SHORT_IDS.items():
        norm = " ".join(legacy.strip().casefold().split())
        row = conn.execute("SELECT pool_id FROM pool_alias WHERE norm = ?", (norm,)).fetchone()
        assert row is not None and row[0] == canonical, (legacy, row)


def test_cutover_every_crowdmonitor_key_lands_as_an_xref(tmp_path: Path) -> None:
    conn = _build(tmp_path)
    for identity in _registry():
        for key in identity.get("crowdmonitor_keys") or []:
            row = conn.execute(
                "SELECT pool_id FROM pool_xref WHERE namespace = 'crowdmonitor' AND ext_id = ?",
                (key,),
            ).fetchone()
            assert row is not None and row[0] == identity["facility_id"], (key, row)


def _spine_rows(conn: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        "pool": conn.execute(
            "SELECT id, name, kind, address, lat, lon, url, description, phone, "
            "facility_doc FROM pool ORDER BY id"
        ).fetchall(),
        "pool_alias": conn.execute(
            "SELECT pool_id, alias, norm FROM pool_alias ORDER BY norm"
        ).fetchall(),
        "pool_xref": conn.execute(
            "SELECT pool_id, namespace, ext_id FROM pool_xref ORDER BY namespace, ext_id"
        ).fetchall(),
    }


def test_build_twice_yields_equal_rows(tmp_path: Path) -> None:
    first = _spine_rows(_build(tmp_path, "first.sqlite"))
    second = _spine_rows(_build(tmp_path, "second.sqlite"))
    assert first == second
