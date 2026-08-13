"""Repo-root pytest fixtures shared across BOTH test trees (`tests/` and `apps/web/tests/`).

`illustrative_data_dir` lives here (not in `tests/conftest.py`) so the app suite can use it too:
pytest only inherits a conftest from an ancestor directory, and `tests/conftest.py` is not an
ancestor of `apps/web/tests/`. This is the single home for the pre-strip illustrative curated data.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_DATA_DIR = Path(__file__).resolve().parent / "data"
_ILLUSTRATIVE_POOLS = (
    Path(__file__).resolve().parent / "tests" / "domain" / "fixtures" / "illustrative_pools"
)


@pytest.fixture(scope="session")
def illustrative_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A curated data dir = the REAL registry + calendar + the committed illustrative pool YAMLs.

    Since delete-curated-schedule-tier S3 the production `data/pools/*.yaml` are thin crosswalk
    files carrying NO schedule (the real timetable is scraped). The resolver / lane-reconciliation /
    lane-panel-projection tests that need KNOWN illustrative schedules (a `valid_as_of`, prices,
    closures, features, per-basin schedules) load these committed pre-strip pool YAMLs instead — so
    no production data carries them, and the real registry+calendar keep the roster from drifting.
    """
    root = tmp_path_factory.mktemp("illustrative")
    shutil.copy(_DATA_DIR / "registry.yaml", root / "registry.yaml")
    shutil.copytree(_DATA_DIR / "calendar", root / "calendar")
    shutil.copytree(_ILLUSTRATIVE_POOLS, root / "pools")
    return root
