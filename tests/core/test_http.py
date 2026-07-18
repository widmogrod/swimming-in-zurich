"""Tests for the HttpClient wrapper.

These use `httpx.MockTransport`, which is the correct seam for timeouts and connection
errors: those never produce a recorded HTTP interaction, so a vcrpy cassette cannot
represent them. Status-code paths (200/500/429) are also exercised here directly; the
real-network equivalents live in the provider tests as cassettes.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from swimzh.core.errors import (
    ConnectionFailed,
    HttpStatus,
    RateLimited,
    Timeout,
    TooLarge,
)
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok

URL = "https://example.test/data"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> HttpClient:
    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport)
    return HttpClient(inner, source="test", **kwargs)  # type: ignore[arg-type]


def test_2xx_returns_ok() -> None:
    client = _client(lambda _req: httpx.Response(200, json={"ok": True}))
    result = client.get(URL)
    assert isinstance(result, Ok)
    assert result.value.json() == {"ok": True}


def test_500_returns_http_status_terminal() -> None:
    client = _client(lambda _req: httpx.Response(500, text="boom"))
    result = client.get(URL)
    assert isinstance(result, Err)
    error = result.error
    assert isinstance(error, HttpStatus)
    assert error.status == 500
    assert "boom" in error.body_snippet


def test_429_returns_rate_limited_with_retry_after() -> None:
    # Only one attempt so we observe the RateLimited value rather than a retry.
    client = _client(
        lambda _req: httpx.Response(429, headers={"Retry-After": "12"}),
        retry=RetryPolicy(max_attempts=1),
    )
    result = client.get(URL)
    assert isinstance(result, Err)
    assert result.error == RateLimited(url=URL, retry_after_s=12.0)


def test_timeout_is_mapped_and_retried_to_exhaustion() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out", request=request)

    client = _client(handler, timeout_s=7.5, retry=RetryPolicy(max_attempts=3))
    result = client.get(URL)
    assert isinstance(result, Err)
    assert result.error == Timeout(url=URL, after_s=7.5)
    assert calls["n"] == 3  # transient error retried until attempts exhausted


def test_connect_error_is_connection_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler, retry=RetryPolicy(max_attempts=1))
    result = client.get(URL)
    assert isinstance(result, Err)
    assert isinstance(result.error, ConnectionFailed)


def test_retry_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, json={"recovered": True})

    client = _client(handler, retry=RetryPolicy(max_attempts=3))
    result = client.get(URL)
    assert isinstance(result, Ok)
    assert calls["n"] == 2


def test_too_large_is_terminal() -> None:
    big = "x" * 2000
    client = _client(lambda _req: httpx.Response(200, text=big), max_bytes=1000)
    result = client.get(URL)
    assert isinstance(result, Err)
    assert isinstance(result.error, TooLarge)
