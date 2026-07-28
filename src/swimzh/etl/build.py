"""Build the gold DB: fold a provider-sourced roster + curated authoring into one store.

`build_store` takes the ~57-pool **roster** (`PoolCatalogEntry`s) as an argument — since S3 it
is sourced LIVE from the WFS by `etl.roster.fetch_roster`, no longer read from a committed
`data/catalog.json` (the caller — the CLI `build` command — fetches it and aborts the whole
build non-zero if the WFS is unreachable). From `data_dir` it still reads the curated dataset
(facilities + calendar + the registry **crosswalk**: aliases, external xref keys,
`baditicker_poiid`) via `load_dataset`; the registry is no longer the roster's identity/geo
authority (that is now the WFS), only the irreducible crosswalk. It writes the DB-enforced
identity spine (one `pool` table = the roster, plus its `pool_alias`/`pool_xref` crosswalk) with
the curated schedule payload carried as a typed blob on the `pool` row (`facility_doc`), and the
calendar to its singleton row. The network scrape commands layer onto the store this produces.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from swimzh.build.seed import build_spine
from swimzh.core.errors import ProviderError
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.closure import is_unmapped
from swimzh.domain.models import Facility, PoolId
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec
from swimzh.storage.rows import PoolSpine
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    open_db,
    write_calendar,
    write_pools,
    write_schedules,
)


def build_store(
    data_dir: Path,
    db_path: str | Path,
    roster: tuple[PoolCatalogEntry, ...],
) -> Result[GoldRepository, ProviderError]:
    """Assemble a self-contained gold store from a provider-sourced roster + curated authoring.

    `roster` is the WFS-sourced pool roster (identity + geo + WFS kind); curated facilities +
    calendar + the registry crosswalk come from `load_dataset(data_dir)`. The identity spine
    (`pool` + `pool_alias` + `pool_xref`) and the calendar are written into one gold DB. A
    curated-input failure short-circuits to a typed `ProviderError`. (The roster's own
    fail-fast — an unreachable WFS — happens BEFORE this call, in the CLI `build` command.)
    """
    dataset_result = load_dataset(data_dir)
    if isinstance(dataset_result, Err):
        return dataset_result
    dataset = dataset_result.value

    spine = build_spine(roster, dataset.facilities, dataset.registry)

    conn = open_db(db_path)
    write_pools(conn, spine)
    # The single write door for the schedule blob: `pool.facility_doc` is populated by
    # `write_schedules` (from the geo-stamped curated facilities `build_spine` serialized),
    # never by `write_pools`.
    write_schedules(conn, _keyed_schedules(spine))
    write_calendar(conn, dataset.calendar)

    # Report unclassified curated closure prose (S4). Not an error: the store is complete
    # and the UI degrades honestly — but a new phrase must not pass unnoticed.
    for pool, phrase in unmapped_closures(dataset.facilities):
        print(f"unmapped closure reason: {pool}: {phrase!r}", file=sys.stderr)

    return Ok(GoldRepository(conn))


def unmapped_closures(facilities: Sequence[Facility]) -> tuple[tuple[str, str], ...]:
    """Curated closure phrases the classifier did not recognise, as `(pool, phrase)`.

    The audit the plan requires: a NEW German phrase upstream must surface as a build-time
    line, never as a silently blank label. `classify_closure` already fails safe (the text
    rides through as `params.text`, so the UI stays truthful); this is what makes the gap
    VISIBLE, in the same spirit as `scrape-lanes`' unbound/unavailable report.
    """
    found: list[tuple[str, str]] = []
    for facility in facilities:
        name = facility.identity.name
        for closure in facility.closures:
            if is_unmapped(closure.code):
                found.append((name, closure.reason))
        for basin in facility.basins:
            for exception in basin.exceptions:
                if is_unmapped(exception.code):
                    found.append((name, exception.reason))
    return tuple(found)


def _keyed_schedules(spine: PoolSpine) -> tuple[tuple[PoolId, Facility], ...]:
    """The curated ``(PoolId, Facility)`` pairs `write_schedules` writes to ``pool.facility_doc``.

    Rehydrated from the spine rows `build_spine` already produced, so the geo authoritatively
    stamped there (committed-catalog coords, B1) is exactly what reaches the read path — one
    stamping site, no divergence.
    """
    return tuple(
        (p.id, codec.loads(p.facility_doc)) for p in spine.pools if p.facility_doc is not None
    )
