"""Build-side guard (delete-curated-schedule-tier S3): every `data/pools/*.yaml` is a THIN
CROSSWALK — a URL→basin lane binding file — carrying NO authoritative fact.

The invariant is a per-level key-set allowlist over the parsed YAML, NOT a denylist grep: a 6-field
grep would pass green while `amenities`/`public_holiday_policy`/`lockers`/basin `kind`/`exceptions`/
`valid_as_of`/… survived in the served blob (they all have DTO defaults, so they load clean). Only
these keys may appear:

* top level ⊆ {`facility_id`, `basins`}
* each basin ⊆ {`basin_id`, `name`, `lane_plan_source`}
* each `lane_plan_source` ⊆ {`url`, `section`}

Every other fact (schedule/rules, prices, closures, physicals, geo, address, source, …) is now
SOURCED (WFS roster / page scrape / price scrape / notices / infrastruktur) or a recorded drop —
never read from curated YAML. This is the guard the S4 reconcile references as the build-side owner
of "no authoritative fact from curated YAML" (distinct from the app-runtime single-source test).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_POOLS_DIR = Path(__file__).resolve().parents[2] / "data" / "pools"

_TOP_LEVEL_ALLOWED = {"facility_id", "basins"}
_BASIN_ALLOWED = {"basin_id", "name", "lane_plan_source"}
_LANE_PLAN_SOURCE_ALLOWED = {"url", "section"}

_POOL_FILES = sorted(_POOLS_DIR.glob("*.yaml"))


def test_there_are_pool_files() -> None:
    assert _POOL_FILES, (
        "no data/pools/*.yaml found — the crosswalk allowlist guard would be vacuous"
    )


@pytest.mark.parametrize("path", _POOL_FILES, ids=lambda p: p.name)
def test_pool_yaml_is_thin_crosswalk_only(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name}: top level is not a mapping"

    extra_top = set(doc) - _TOP_LEVEL_ALLOWED
    assert not extra_top, f"{path.name}: non-crosswalk top-level keys: {sorted(extra_top)}"

    for basin in doc.get("basins") or ():
        assert isinstance(basin, dict), f"{path.name}: a basin is not a mapping"
        extra_basin = set(basin) - _BASIN_ALLOWED
        assert not extra_basin, f"{path.name}: non-crosswalk basin keys: {sorted(extra_basin)}"

        lps = basin.get("lane_plan_source")
        if lps is not None:
            assert isinstance(lps, dict), f"{path.name}: lane_plan_source is not a mapping"
            extra_lps = set(lps) - _LANE_PLAN_SOURCE_ALLOWED
            assert not extra_lps, (
                f"{path.name}: non-crosswalk lane_plan_source keys: {sorted(extra_lps)}"
            )
