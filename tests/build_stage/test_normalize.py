"""The one cleaning home: `normalize` is a pure, idempotent match-key producer."""

from __future__ import annotations

import pytest

from swimzh.core.normalize import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hallenbad City", "hallenbad city"),
        ("  Hallenbad   CITY ", "hallenbad city"),
        ("Wärmebad Käferberg", "wärmebad käferberg"),
        ("city", "city"),
    ],
)
def test_normalize_casefolds_and_collapses_whitespace(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", ["Hallenbad City", "  MESSY   name ", "Wärmebad Käferberg", ""])
def test_normalize_is_idempotent(raw: str) -> None:
    once = normalize(raw)
    assert normalize(once) == once


def test_normalize_matches_the_registry_and_silver_helpers() -> None:
    # The whole point of hoisting: the one function is what registry + silver now use, so
    # alias-norm generation and reconcile lookup can never diverge. Loading via import_module
    # (ModuleType) keeps both mypy's private-export check and ruff's getattr lint out of it.
    import importlib

    registry_mod = importlib.import_module("swimzh.domain.registry")
    silver_mod = importlib.import_module("swimzh.etl.silver")

    assert registry_mod._normalise is normalize
    assert silver_mod._normalise is normalize
