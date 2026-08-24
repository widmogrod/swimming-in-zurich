"""The iOS field-coverage contract must still match the web response models.

This is the staleness gate, and without it the whole mechanism is decorative: the Swift side
asserts that every field in the committed JSON is either rendered or deliberately omitted,
but nothing on that side can notice when `OptionOut` grows a field the JSON never heard of.
This test is what makes adding a field to a model fail — exactly the teeth
`test_eligibility_ui_contract.py` gives its own fixture.

Regenerate after a deliberate model change::

    SWIMZH_REGENERATE_FIELD_COVERAGE=1 uv run pytest \\
        apps/web/tests/test_field_coverage_contract.py

`scripts/` is a tool tree — outside `[tool.coverage.run]` and outside mypy's `files` — so the
generator is loaded by path here, the same way `tests/scripts/test_crap_swift.py` loads the
CRAP gate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "scripts" / "field_coverage.py"
_REGENERATE = os.environ.get("SWIMZH_REGENERATE_FIELD_COVERAGE") == "1"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


field_coverage = _load("field_coverage", GENERATOR)


def test_the_generator_runs_with_no_gold_db_at_all() -> None:
    """`apps.web.main` fails fast without `SWIMZH_GOLD_DB`, so the generator must not reach it.

    Asserted by RUNNING it, in a subprocess with the variable stripped from the environment,
    rather than by grepping for the import: a transitive import through some other
    `apps.web` module would satisfy a grep and still make the generator unrunnable on exactly
    the fresh checkout the committed fixture exists for. `sys.modules` is no use either — the
    web suite's own conftest has already imported the app by the time this runs.
    """
    env = {k: v for k, v in os.environ.items() if k != "SWIMZH_GOLD_DB"}
    done = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter and script
        [sys.executable, str(GENERATOR)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_committed_contract_matches_the_models() -> None:
    generated = field_coverage.contract()
    if _REGENERATE:
        field_coverage.write()
    committed = json.loads(field_coverage.FIXTURE.read_text(encoding="utf-8"))
    assert committed == generated, (
        "the generated iOS field-coverage contract is stale; regenerate with "
        "SWIMZH_REGENERATE_FIELD_COVERAGE=1 uv run pytest "
        "apps/web/tests/test_field_coverage_contract.py"
    )


def test_the_contract_covers_the_four_models_the_phone_must_reproduce() -> None:
    """Named, so silently dropping one from `MODELS` is loud rather than green.

    `FacilityDetailOut` in particular is here for a slice that has not happened yet: the S3b
    detail sheet is governed by this mechanism from S3a on, so its fields start out omitted
    with a reason and the Swift test enforces the move.
    """
    committed = json.loads(field_coverage.FIXTURE.read_text(encoding="utf-8"))
    assert set(committed["models"]) == {
        "OptionOut",
        "StatusOut",
        "PoolOut",
        "FacilityDetailOut",
    }


def test_field_names_are_qualified_so_the_four_models_cannot_collide() -> None:
    """`OptionOut.facility` and `StatusOut.facility` are two different obligations.

    An unqualified union would collapse them into one entry that either side could satisfy by
    covering the wrong model — a hole exactly where the two models overlap most.
    """
    committed = json.loads(field_coverage.FIXTURE.read_text(encoding="utf-8"))
    fields = committed["fields"]
    assert len(fields) == len(set(fields))
    assert fields == sorted(fields)
    assert "OptionOut.facility" in fields
    assert "StatusOut.facility" in fields
    expected = sum(len(fs) for fs in committed["models"].values())
    assert len(fields) == expected
