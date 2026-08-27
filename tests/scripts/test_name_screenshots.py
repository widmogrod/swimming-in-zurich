"""The screenshot renamer's own tests.

`make ios-screenshots` uploads what this script leaves behind, and the App Store shows a
screenshot set in UPLOAD ORDER — so a renamer that half-worked would reorder the story a
reviewer reads before they read anything else. These prove the three things that make the
names usable: the per-run suffix is stripped (so the set is diffable and a re-upload replaces
rather than adds), the manifest is consumed, and an export that produced nothing FAILS instead
of silently leaving a directory of UUIDs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


name_screenshots = _load("name_screenshots", REPO_ROOT / "scripts" / "name_screenshots.py")

# One real pair, copied from an actual export: xcresulttool names the FILE after the
# attachment's UUID and puts the test's chosen name — with a payload index and a second UUID
# glued on — in the manifest beside it.
EXPORTED = "FB4844D7-20B8-4E95-B529-B842BF12D859.png"
SUGGESTED = "01-find_0_41AB3819-51DD-4C08-8088-13836352E9EF.png"


def _export(directory: Path, pairs: list[tuple[str, str]]) -> None:
    for exported, _ in pairs:
        (directory / exported).write_bytes(b"png")
    (directory / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "testIdentifier": "ScreenshotTests/testCaptureTheAppStoreSet()",
                    "attachments": [
                        {"exportedFileName": e, "suggestedHumanReadableName": s} for e, s in pairs
                    ],
                }
            ]
        )
    )


def test_the_run_suffix_is_stripped_so_the_set_is_stable(tmp_path: Path) -> None:
    _export(tmp_path, [(EXPORTED, SUGGESTED)])

    assert name_screenshots.main(tmp_path) == 0

    # The name the test chose, and NOTHING from this particular run. Keeping the suffix would
    # give every capture new filenames, which reads to the App Store as five more screenshots.
    assert (tmp_path / "01-find.png").read_bytes() == b"png"
    assert not (tmp_path / EXPORTED).exists()


def test_the_whole_set_is_named_and_the_manifest_is_consumed(tmp_path: Path) -> None:
    pairs = [
        (f"{i}-uuid.png", f"{name}_0_41AB3819-51DD-4C08-8088-13836352E9EF.png")
        for i, name in enumerate(["01-find", "02-lanes", "03-filters", "04-pool", "05-map"])
    ]
    _export(tmp_path, pairs)

    assert name_screenshots.main(tmp_path) == 0

    # Sorted, because that is the order they are uploaded in and therefore the order a reader
    # meets the app in. The manifest is gone: it is not a screenshot and would be uploaded too.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "01-find.png",
        "02-lanes.png",
        "03-filters.png",
        "04-pool.png",
        "05-map.png",
    ]


def test_an_export_that_produced_nothing_fails(tmp_path: Path) -> None:
    # No manifest at all — what a failed or skipped capture leaves. Returning 0 here would let
    # `make ios-screenshots` finish green over an empty directory.
    assert name_screenshots.main(tmp_path) == 1

    # A manifest naming a file that was never written is the same story with more paperwork.
    _export(tmp_path, [(EXPORTED, SUGGESTED)])
    (tmp_path / EXPORTED).unlink()
    assert name_screenshots.main(tmp_path) == 1
