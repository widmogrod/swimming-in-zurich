"""The medallion pipeline: raw -> silver -> gold, composed from the stage functions.

`run(...)` is deterministic given its inputs and the injected `fetched_at` clock, so it is
fully testable offline (drive the geo fetch with an httpx.MockTransport or a cassette).
Any stage failure short-circuits to a typed `ProviderError`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import PoolKind
from swimzh.etl import raw as raw_stage
from swimzh.etl.gold import write_gold
from swimzh.etl.silver import reconcile
from swimzh.providers.curated import load_dataset
from swimzh.providers.geo_sport import parse_pools
from swimzh.storage.sqlite_repo import GoldRepository, open_db


def run(
    *,
    data_dir: Path,
    db_path: str | Path,
    client: HttpClient,
    fetched_at: datetime,
    raw_dir: Path | None = None,
) -> Result[GoldRepository, ProviderError]:
    dataset_result = load_dataset(data_dir)
    if isinstance(dataset_result, Err):
        return dataset_result
    dataset = dataset_result.value

    raw_result = raw_stage.capture_geo(client, fetched_at)
    if isinstance(raw_result, Err):
        return raw_result
    artifact = raw_result.value
    if raw_dir is not None:
        raw_stage.write_raw(raw_dir, artifact)

    pools_result = parse_pools(artifact.content, PoolKind.INDOOR)
    if isinstance(pools_result, Err):
        return pools_result

    silver_result = reconcile(dataset, pools_result.value, fetched_at)
    if isinstance(silver_result, Err):
        return silver_result

    conn = open_db(db_path)
    return Ok(write_gold(conn, silver_result.value))
