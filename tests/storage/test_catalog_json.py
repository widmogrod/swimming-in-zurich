"""Catalog JSON round-trips exactly, and the committed data/catalog.json is valid."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.storage import catalog_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def test_roundtrip_exact() -> None:
    entries = (
        PoolCatalogEntry(
            pool_id="hallenbad-city",
            name="Hallenbad City",
            kind=PoolKind.INDOOR,
            address="Sihlstrasse 71, 8001 Zürich",
            geo=GeoPoint(lat=47.3723, lon=8.5330),
            url="https://example.test/city",
            description="50m pool, sauna",
            phone="+41 44 000 00 00",
        ),
        PoolCatalogEntry(
            pool_id="planschbecken-x",
            name="Planschbecken X",
            kind=PoolKind.PADDLING,
            address="",
            geo=None,
            url=None,
            description=None,
            phone=None,
        ),
    )
    text = catalog_json.dumps(entries, datetime(2026, 7, 19, tzinfo=ZoneInfo("Europe/Zurich")))
    assert catalog_json.loads(text) == entries


def test_committed_catalog_is_valid() -> None:
    entries = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    assert len(entries) >= 50
    assert len({e.pool_id for e in entries}) == len(entries)
    assert {e.kind for e in entries} >= {PoolKind.INDOOR, PoolKind.OUTDOOR, PoolKind.LAKE}
