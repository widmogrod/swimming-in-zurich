"""The store schema version, pinned across the two languages that must agree on it.

`ios_export.SCHEMA_VERSION` is what the exporter WRITES into `meta`; `appStoreSchemaVersion`
in `Refresh.swift` is what an installed app will ACCEPT. They are the same number in two
languages, and the day they differ is the day either every phone rejects every published store
(and silently keeps last week's, forever) or a binary reads a file whose columns it does not
know.

Nothing else joins them: the Swift constant cannot import Python, and the export cannot import
Swift. So the join is this test — the same shape as `test_ios_budget`'s memory-ceiling check,
which restates the Swift literal for the same reason.

Text-only, so it runs on every runner including the ubuntu `qa` job: it reads two files off
disk and needs neither a toolchain nor a simulator.
"""

from __future__ import annotations

import re
from pathlib import Path

from swimzh.etl.ios_export import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
REFRESH = REPO_ROOT / "apps" / "ios" / "Sources" / "SwimZHKit" / "Refresh.swift"
REFRESH_TESTS = REPO_ROOT / "apps" / "ios" / "Tests" / "SwimZHKitTests" / "RefreshTests.swift"


def _swift_constant() -> int:
    match = re.search(r"public let appStoreSchemaVersion\s*=\s*(\d+)", REFRESH.read_text())
    assert match is not None, "appStoreSchemaVersion is gone from Refresh.swift"
    return int(match.group(1))


def test_the_app_accepts_exactly_the_version_the_export_writes() -> None:
    assert _swift_constant() == SCHEMA_VERSION, (
        f"the exporter writes schema_version={SCHEMA_VERSION} but the app accepts "
        f"{_swift_constant()} — every published store would be rejected"
    )


def test_the_swift_side_pins_the_number_rather_than_only_naming_the_constant() -> None:
    """A Swift test asserting `x == x` would keep this file green while proving nothing.

    So the Swift suite carries the literal too, and this asserts the literal is the same one.
    Bumping the version is therefore a three-file edit — exporter, constant, Swift literal —
    which is the point: it is a wire-format change, not a rename.
    """
    assert f"appStoreSchemaVersion == {SCHEMA_VERSION}" in REFRESH_TESTS.read_text()


def test_the_version_is_documented_where_it_is_bumped() -> None:
    """The bump reason lives beside the constant, so the next bumper reads why the last one
    happened. An undocumented version number is one nobody dares change."""
    source = REFRESH.read_text()
    assert "schema_version" in source
    export = (REPO_ROOT / "src" / "swimzh" / "etl" / "ios_export.py").read_text()
    assert "1 -> 2 (S5)" in export, "the schema bump lost its recorded reason"
