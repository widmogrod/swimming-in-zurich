"""Load the committed pool catalog (data/catalog.json) at startup. Fail-soft: a missing
catalog yields an empty listing (the app still runs; run `swimzh build-catalog` to populate)."""

from __future__ import annotations

from pathlib import Path

from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.storage import catalog_json


def load_catalog(data_dir: Path) -> tuple[PoolCatalogEntry, ...]:
    path = data_dir / "catalog.json"
    if not path.exists():
        return ()
    return catalog_json.loads(path.read_text(encoding="utf-8"))
