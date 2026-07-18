"""Tests for the hand-rolled Result type."""

from __future__ import annotations

import pytest

from swimzh.core.result import Err, Ok, Result, ResultError, bind, fmap


def _parse(s: str) -> Result[int, str]:
    try:
        return Ok(int(s))
    except ValueError:
        return Err(f"not an int: {s!r}")


def test_ok_carries_value_and_matches() -> None:
    result = _parse("42")
    match result:
        case Ok(value):
            assert value == 42
        case Err(_):  # pragma: no cover - should not happen
            pytest.fail("expected Ok")


def test_err_carries_error_and_matches() -> None:
    result = _parse("nope")
    match result:
        case Ok(_):  # pragma: no cover - should not happen
            pytest.fail("expected Err")
        case Err(error):
            assert error == "not an int: 'nope'"


def test_is_ok() -> None:
    assert Ok(1).is_ok() is True
    assert Err("x").is_ok() is False


def test_fmap_only_transforms_ok() -> None:
    assert fmap(_parse("2"), lambda x: x + 1) == Ok(3)
    assert fmap(_parse("boom"), lambda x: x + 1) == Err("not an int: 'boom'")


def test_bind_chains_on_ok() -> None:
    assert bind(_parse("10"), lambda n: Ok(n * 2)) == Ok(20)
    assert bind(_parse("bad"), lambda n: Ok(n * 2)) == Err("not an int: 'bad'")


def test_unwrap_or() -> None:
    assert Ok(5).unwrap_or(0) == 5
    assert Err("e").unwrap_or(0) == 0


def test_unwrap_or_raise_returns_value_on_ok() -> None:
    assert Ok("hi").unwrap_or_raise() == "hi"


def test_unwrap_or_raise_raises_with_typed_error() -> None:
    with pytest.raises(ResultError) as excinfo:
        Err("the-error").unwrap_or_raise()
    assert excinfo.value.error == "the-error"


def test_results_are_frozen() -> None:
    ok = Ok(1)
    with pytest.raises(AttributeError):
        ok.value = 2  # type: ignore[misc]
