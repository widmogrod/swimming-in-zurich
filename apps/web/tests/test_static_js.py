"""Bridge the native-ES-module unit tests into the Python QA gate.

The UI's pure JS modules (`timescale`, `filterstate`) ship no build step, so their
unit tests run on Node's zero-dependency built-in runner (`node --test`). This test
shells out to it, so `uv run pytest` — and therefore the mechanical QA gate — fails
if any JS unit test regresses. It is skipped (not silently passed) only where Node is
genuinely unavailable, so the modules are never shipped un-run.
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
    # Run from the js dir so Node's built-in runner discovers every *.test.js
    # (Node 26 rejects a bare directory positional; cwd-based discovery is stable).
    result = subprocess.run(
        [_NODE, "--test"],
        cwd=_JS_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"node --test failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
