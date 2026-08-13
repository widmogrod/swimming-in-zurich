"""`atomic_swap`: a temp DB beside the target that atomically replaces it only on `commit()`.

The mechanism behind S4's all-or-nothing-fresh guarantee — any abort (no commit, or an exception)
leaves the prior file content-unchanged and discards the temp."""

from __future__ import annotations

from pathlib import Path

import pytest

from swimzh.storage.atomic import atomic_swap


def test_commit_atomically_replaces_the_target(tmp_path: Path) -> None:
    target = tmp_path / "gold.sqlite"
    target.write_text("OLD", encoding="utf-8")
    with atomic_swap(target) as staging:
        staging.path.write_text("NEW", encoding="utf-8")
        staging.commit()
    assert target.read_text(encoding="utf-8") == "NEW"
    # No temp litter left beside the target.
    assert list(tmp_path.iterdir()) == [target]


def test_no_commit_discards_the_temp_leaving_target_untouched(tmp_path: Path) -> None:
    target = tmp_path / "gold.sqlite"
    target.write_text("OLD", encoding="utf-8")
    with atomic_swap(target) as staging:
        staging.path.write_text("NEW", encoding="utf-8")
        # never commit -> abort
    assert target.read_text(encoding="utf-8") == "OLD"
    assert list(tmp_path.iterdir()) == [target]


def test_exception_discards_the_temp_and_reraises(tmp_path: Path) -> None:
    target = tmp_path / "gold.sqlite"
    target.write_text("OLD", encoding="utf-8")

    def _commit_then_raise() -> None:
        with atomic_swap(target) as staging:
            staging.path.write_text("NEW", encoding="utf-8")
            staging.commit()  # even a committed run must roll back if the body then raises
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _commit_then_raise()
    assert target.read_text(encoding="utf-8") == "OLD"  # unchanged despite the earlier commit
    assert list(tmp_path.iterdir()) == [target]


def test_from_scratch_build_leaves_no_target_on_abort(tmp_path: Path) -> None:
    target = tmp_path / "gold.sqlite"  # does not exist yet
    with atomic_swap(target) as staging:
        staging.path.write_text("NEW", encoding="utf-8")
        # abort: no commit
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_seed_from_byte_copies_the_source_into_the_temp(tmp_path: Path) -> None:
    target = tmp_path / "gold.sqlite"
    target.write_text("LIVE-CONTENT", encoding="utf-8")
    with atomic_swap(target, seed_from=target) as staging:
        # The temp starts as a copy of the live store, so a layering command reads current content.
        assert staging.path.read_text(encoding="utf-8") == "LIVE-CONTENT"
        staging.path.write_text("LIVE-CONTENT+LAYER", encoding="utf-8")
        staging.commit()
    assert target.read_text(encoding="utf-8") == "LIVE-CONTENT+LAYER"
