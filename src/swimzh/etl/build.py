"""Offline build: assemble a complete, self-contained gold DB from committed inputs.

`build_store` is the one offline builder: it reads only the curated files already committed
under `data_dir` — the curated dataset (facilities + registry + calendar via `load_dataset`)
and the committed pool catalog (`catalog.json`) — and writes the DB-enforced identity spine
(one `pool` table = the roster, plus its `pool_alias`/`pool_xref` crosswalk) with the curated
schedule payload carried as a typed blob on the `pool` row (`facility_doc`), and the calendar
to its singleton row. No WFS fetch, no scraping; the network commands layer onto the store
this produces.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.build.seed import build_spine
from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility, PoolId
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json, codec
from swimzh.storage.rows import PoolSpine
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    open_db,
    write_calendar,
    write_pools,
    write_schedules,
)

_SOURCE = "catalog"


def build_store(data_dir: Path, db_path: str | Path) -> Result[GoldRepository, ProviderError]:
    """Assemble a self-contained gold store from committed inputs, offline.

    Curated facilities + registry + calendar come from `load_dataset(data_dir)`; the pool
    roster from the committed `data_dir/catalog.json`. The identity spine (`pool` +
    `pool_alias` + `pool_xref`) and the calendar are written into one gold DB. Any input
    failure short-circuits to a typed `ProviderError`.
    """
    dataset_result = load_dataset(data_dir)
    if isinstance(dataset_result, Err):
        return dataset_result
    dataset = dataset_result.value

    catalog_result = _load_catalog(data_dir / "catalog.json")
    if isinstance(catalog_result, Err):
        return catalog_result
    entries = catalog_result.value

    spine = build_spine(entries, dataset.facilities, dataset.registry)

    conn = open_db(db_path)
    write_pools(conn, spine)
    # The single write door for the schedule blob: `pool.facility_doc` is populated by
    # `write_schedules` (from the geo-stamped curated facilities `build_spine` serialized),
    # never by `write_pools`.
    write_schedules(conn, _keyed_schedules(spine))
    write_calendar(conn, dataset.calendar)
    return Ok(GoldRepository(conn))


def _keyed_schedules(spine: PoolSpine) -> tuple[tuple[PoolId, Facility], ...]:
    """The curated ``(PoolId, Facility)`` pairs `write_schedules` writes to ``pool.facility_doc``.

    Rehydrated from the spine rows `build_spine` already produced, so the geo authoritatively
    stamped there (committed-catalog coords, B1) is exactly what reaches the read path — one
    stamping site, no divergence.
    """
    return tuple(
        (p.id, codec.loads(p.facility_doc)) for p in spine.pools if p.facility_doc is not None
    )


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
