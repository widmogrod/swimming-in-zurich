"""Tests for the ProviderError union: classification and description.

Exhaustiveness itself is proven at type-check time by `pyright --strict` (the
`assert_never` arms). These runtime tests pin the *behaviour* of every variant, and
`ALL_VARIANTS` doubles as a checklist: add a variant to the union without adding it here
and the totality tests below will not cover it.
"""

from __future__ import annotations

from swimzh.core.errors import (
    ConnectionFailed,
    DecodeError,
    HttpStatus,
    ParseError,
    ProviderError,
    ProviderSpecific,
    RateLimited,
    Redirect,
    SchemaMismatch,
    Timeout,
    TooLarge,
    describe,
    retriable,
)

ALL_VARIANTS: list[ProviderError] = [
    Timeout(url="https://x/", after_s=10.0),
    ConnectionFailed(url="https://x/", detail="refused"),
    HttpStatus(url="https://x/", status=500, body_snippet="oops"),
    RateLimited(url="https://x/", retry_after_s=30.0),
    DecodeError(source="geo", detail="bad gzip"),
    ParseError(source="geo", detail="invalid json", raw_snippet="{"),
    SchemaMismatch(source="geo", detail="missing field 'name'"),
    TooLarge(url="https://x/", limit_bytes=1000),
    Redirect(url="https://x/", location="https://y/", count=-1),
    ProviderSpecific(provider="geo", detail={"code": 7}),
]


def test_retriable_is_total_over_all_variants() -> None:
    for variant in ALL_VARIANTS:
        assert isinstance(retriable(variant), bool)


def test_retriable_transient_variants() -> None:
    assert retriable(Timeout(url="u", after_s=1.0)) is True
    assert retriable(ConnectionFailed(url="u", detail="d")) is True
    assert retriable(RateLimited(url="u", retry_after_s=None)) is True
    assert retriable(Redirect(url="u", location="v", count=-1)) is True


def test_retriable_terminal_variants() -> None:
    assert retriable(HttpStatus(url="u", status=404, body_snippet="")) is False
    assert retriable(DecodeError(source="s", detail="")) is False
    assert retriable(ParseError(source="s", detail="", raw_snippet="")) is False
    assert retriable(SchemaMismatch(source="s", detail="")) is False
    assert retriable(TooLarge(url="u", limit_bytes=1)) is False
    assert retriable(ProviderSpecific(provider="p", detail=None)) is False


def test_describe_is_total_and_nonempty() -> None:
    for variant in ALL_VARIANTS:
        text = describe(variant)
        assert isinstance(text, str) and text
