"""Offline build: assemble a complete, self-contained gold DB from committed inputs.

`build_store` is the network-free counterpart to `pipeline.run`: it reads only the curated
files already committed under `data_dir` — the curated dataset (facilities + calendar via
`load_dataset`) and the committed pool catalog (`catalog.json`) — and writes all three into
one gold SQLite store (`facility` + `catalog` + `calendar`). No WFS fetch, no scraping; the
network commands (`scrape-gold`, `scrape-lanes`, geo enrichment) layer onto the store this
produces.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    open_db,
    write_calendar,
    write_catalog,
    write_facilities,
)

_SOURCE = "catalog"


def build_store(data_dir: Path, db_path: str | Path) -> Result[GoldRepository, ProviderError]:
    """Assemble a self-contained gold store from committed inputs, offline.

    Curated facilities + calendar come from `load_dataset(data_dir)`; the pool catalog from
    the committed `data_dir/catalog.json`. All three are written into one gold DB. Any
    input failure short-circuits to a typed `ProviderError`.
    """
    dataset_result = load_dataset(data_dir)
    if isinstance(dataset_result, Err):
        return dataset_result
    dataset = dataset_result.value

    catalog_result = _load_catalog(data_dir / "catalog.json")
    if isinstance(catalog_result, Err):
        return catalog_result
    entries = catalog_result.value

    conn = open_db(db_path)
    write_facilities(conn, dataset.facilities)
    write_catalog(conn, entries)
    write_calendar(conn, dataset.calendar)
    return Ok(GoldRepository(conn))


def _load_catalog(path: Path) -> Result[tuple[PoolCatalogEntry, ...], ProviderError]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Err(
            ParseError(
                source=_SOURCE,
                detail=f"cannot read catalog {path}: {exc}; run build-catalog first",
                raw_snippet="",
            )
        )
    try:
        return Ok(catalog_json.loads(text))
    except ValueError as exc:
        return Err(SchemaMismatch(source=_SOURCE, detail=f"{path.name}: {exc}"))
