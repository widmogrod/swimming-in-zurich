"""Bridge the native-ES-module unit tests into the Python QA gate.

The UI's pure JS modules ship no build step, so their unit tests run on Node's
zero-dependency built-in runner (`node --test`). This test shells out to it, so
`uv run pytest` — and therefore the mechanical QA gate — fails if any JS unit test
regresses. It is skipped (not silently passed) only where Node is genuinely
unavailable, so the modules are never shipped un-run.

`node --test` (run with cwd at the js dir) discovers `*.test.js` RECURSIVELY, so it
covers both the top-level modules (`timescale`, `filterstate`) and the S1 component
suites under `static/js/components/*.test.js` (SegmentedControl, ChipGroup,
Combobox, PlaceTypeahead, Toggle, DateStepper, the badges, and the registry sweep)
with no per-file wiring.

Discovery is pinned to the `**/*.test.js` glob: Node 26's default test glob ALSO
matches `*.test.ts`, but the migrated TypeScript suites (e.g. `urlstate.test.ts`)
run on vitest in the SEPARATE TS chain — they import `./x.js` specifiers that only
resolve from the compiled `dist/`, so running them under this source-tree bridge is
wrong. The `.js` glob keeps each chain to its own suites as modules migrate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_JS_DIR = Path(__file__).resolve().parents[1] / "static" / "js"
_NODE = shutil.which("node")


@pytest.mark.skipif(
    _NODE is None,
    reason="node not installed; the UI JS unit tests need the `node --test` runner",
)
def test_static_js_unit_tests_pass() -> None:
    assert _NODE is not None  # narrowed for the type checker (skipif guarantees it)
    # Run from the js dir so Node's built-in runner discovers every *.test.js. The
    # explicit `.js` glob scopes the bridge to the JS suites (Node 26's default glob
    # also matches `*.test.ts`, which belongs to the vitest chain — see the module
    # docstring). A glob positional is accepted; a bare directory positional is not.
    result = subprocess.run(
        [_NODE, "--test", "**/*.test.js"],
        cwd=_JS_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"node --test failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
