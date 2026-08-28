"""The two S3b iOS fixtures must still match the domain that generated them.

Same mechanism, and same reason, as `test_field_coverage_contract.py`: the Swift side asserts
that its committed copy of a Python fact is reproduced exactly, but nothing on that side can
notice when the PYTHON changes. Without these gates, editing `swimzh.domain.access` or
`swimzh.domain.lane_plan` left the Python chain green, the fixture stale, and the Swift test
passing against the stale copy — the two drifting together, which is precisely what
`AccessExplainer.swift` claims this contract prevents.

Regenerate after a deliberate domain change::

    make ios-fixtures

`scripts/` is a tool tree — outside `[tool.coverage.run]` and outside mypy's `files` — so the
generator is loaded by path here, exactly as `test_field_coverage_contract.py` loads its own.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from swimzh.storage.sqlite_repo import GoldRepository, open_db

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "scripts" / "ios_fixtures.py"

_STALE = "the committed iOS fixture is stale; regenerate it with `make ios-fixtures`"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ios_fixtures = _load("ios_fixtures", GENERATOR)


def test_the_committed_access_types_match_the_domain() -> None:
    """No gold DB and no build: `access_types_doc` reads `swimzh.domain.access` alone."""
    committed = json.loads(ios_fixtures.ACCESS.read_text(encoding="utf-8"))
    assert committed == ios_fixtures.access_types_doc(), _STALE


def test_the_access_types_fixture_covers_every_access_class() -> None:
    """Named separately so dropping a class from `REPRESENTATIVE_ACCESS` is loud.

    The equality above would still hold if both sides lost the same entry; the phone's
    explainer would then simply have nothing to say about a kind `session.access_kind` still
    carries.
    """
    from swimzh.domain.access import ACCESS_TYPES

    committed = json.loads(ios_fixtures.ACCESS.read_text(encoding="utf-8"))
    assert len(committed["types"]) == len(ACCESS_TYPES)
    keys = [entry["key"] for entry in committed["types"]]
    assert keys == [info.key for info in ACCESS_TYPES]
    assert len(set(entry["class_name"] for entry in committed["types"])) == len(keys)


def test_the_committed_lane_plans_match_the_domain(gold_db: Path) -> None:
    """The lane fixture, recomputed from the same cassette-replayed build the suite already has.

    This one DOES need a gold store — the six real basins' plans come out of it — which is why
    it lives in `apps/web/tests/`, where the session-scoped `gold_db` fixture is built once for
    the whole suite. It is not a network dependency: `recorded_build_clients` replays committed
    cassettes.

    Note the fixture is generated from a build over the SAME inputs but not necessarily the same
    temp path, so only the derived document is compared, never bytes on disk.
    """
    committed = json.loads(ios_fixtures.LANE_PLANS.read_text(encoding="utf-8"))
    with open_db(gold_db) as conn:
        generated = ios_fixtures.lane_plans_doc(GoldRepository(conn).load_all())
    # Round-tripped through json so tuples/sets in the generated doc compare as the file's lists.
    assert committed == json.loads(json.dumps(generated, sort_keys=True)), _STALE


def test_the_lane_fixture_carries_both_the_real_basins_and_the_synthetic_one() -> None:
    """The synthetic basin is the only source of `partial == true`, so losing it is silent.

    Every real basin on the committed store resolved COMPLETELY, so a fixture drawn from gold
    alone would assert `partial == false` everywhere and prove nothing about a rendered field.
    """
    committed = json.loads(ios_fixtures.LANE_PLANS.read_text(encoding="utf-8"))
    basins = {case["basin_id"] for case in committed["cases"]}
    synthetic = committed["synthetic_basin_id"]
    assert synthetic in basins
    assert len(basins - {synthetic}) >= 6
    partial = [case for case in committed["cases"] if case["confidence"] == "partial"]
    assert {case["basin_id"] for case in partial} == {synthetic}
