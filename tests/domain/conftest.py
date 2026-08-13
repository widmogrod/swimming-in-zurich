"""Shared domain-test fixtures.

The resolver end-to-end tests (`test_query`, `test_facility_detail`) prove "where can I swim?" and
"what does this pool offer?" against a set of KNOWN illustrative schedules. Since
delete-curated-schedule-tier S3 the production `data/pools/*.yaml` are thin crosswalk files carrying
NO schedule (the real timetable is scraped), so those illustrative schedules now live as committed
TEST FIXTURES under `tests/domain/fixtures/illustrative_pools/` (the pre-strip pool YAMLs). The
`illustrative_data_dir` fixture (top-level `tests/conftest.py`) assembles a self-contained curated
data dir from them + the real registry/calendar; this loads it into the `Dataset` those tests use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.providers.curated import Dataset, load_dataset


@pytest.fixture(scope="module")
def dataset(illustrative_data_dir: Path) -> Dataset:
    result = load_dataset(illustrative_data_dir)
    assert isinstance(result, Ok), result
    return result.value
