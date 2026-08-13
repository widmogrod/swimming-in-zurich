"""Tests for `DiskCacheTransport` — the httpx seam over the pure `CacheStore`.

Every test drives the transport with an `httpx.MockTransport` as `inner` (which records
how many times it was actually called) plus a **controllable clock**, so freshness is a
value we set rather than wall-clock luck. No network, no real filesystem beyond
`tmp_path`.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.core.httpcache import (
    DEFAULT_TIER,
    DEFAULT_TTL_S,
    CacheMode,
    CacheStore,
    DiskCacheTransport,
)

ZURICH = ZoneInfo("Europe/Zurich")
START = datetime(2026, 7, 31, 9, 0, tzinfo=ZURICH)
URL = "https://www.stadt-zuerich.ch/hallenbad-city"
TIER = "snapshot"
TTL_S = 12 * 3600


class Clock:
    """A hand-cranked injectable clock."""

    def __init__(self, at: datetime = START) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, delta: timedelta) -> None:
        self.at += delta


class RecordingInner(httpx.BaseTransport):
    """A `MockTransport` that counts the requests that actually reached it."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._mock = httpx.MockTransport(handler)
        self.requests: list[httpx.Request] = []
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._mock.handle_request(request)

    def close(self) -> None:
        self.closed = True

    @property
    def calls(self) -> int:
        return len(self.requests)


def _ok(body: bytes = b"<html>Hallenbad City</html>") -> Callable[[httpx.Request], httpx.Response]:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body)

    return handler


def _request(
    url: str = URL, *, tier: str | None = TIER, ttl_s: int | None = TTL_S
) -> httpx.Request:
    extensions: dict[str, Any] = {}
    if tier is not None:
        extensions["cache_tier"] = tier
    if ttl_s is not None:
        extensions["cache_ttl_s"] = ttl_s
    return httpx.Request("GET", url, extensions=extensions)


def _transport(
    tmp_path: Path,
    inner: RecordingInner,
    mode: CacheMode,
    clock: Clock,
) -> DiskCacheTransport:
    return DiskCacheTransport(inner, CacheStore(tmp_path), mode, now=clock)


# --- USE ---------------------------------------------------------------------------


def test_use_with_a_fresh_entry_makes_zero_inner_calls(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    transport = _transport(tmp_path, inner, CacheMode.USE, clock)

    first = transport.handle_request(_request())
    assert inner.calls == 1
    assert first.status_code == 200

    clock.advance(timedelta(hours=11))
    hit = transport.handle_request(_request())

    assert inner.calls == 1  # the warm hit never reached the network
    assert hit.status_code == 200
    assert hit.content == b"<html>Hallenbad City</html>"
    assert hit.headers["content-type"] == "text/html"


def test_use_with_a_missing_entry_makes_exactly_one_call_and_writes(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)
    request = _request()

    response = transport.handle_request(request)

    assert inner.calls == 1
    assert response.content == b"<html>Hallenbad City</html>"
    document = json.loads(store.path_for(request, TIER).read_text(encoding="utf-8"))
    assert document["response"]["body"] == "<html>Hallenbad City</html>"
    assert document["cache"]["tier"] == TIER
    assert document["cache"]["ttl_s"] == TTL_S
    assert document["cache"]["fetched_at"] == START.isoformat()


def test_use_with_a_stale_entry_refetches_exactly_once_and_rewrites(tmp_path: Path) -> None:
    clock = Clock()
    bodies = iter([b"first", b"second"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=next(bodies))

    inner = RecordingInner(handler)
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)

    assert transport.handle_request(_request()).content == b"first"
    clock.advance(timedelta(seconds=TTL_S))  # exactly at expiry: already stale

    second = transport.handle_request(_request())

    assert inner.calls == 2
    assert second.content == b"second"
    document = json.loads(store.path_for(_request(), TIER).read_text(encoding="utf-8"))
    assert document["response"]["body"] == "second"
    assert document["cache"]["fetched_at"] == (START + timedelta(seconds=TTL_S)).isoformat()


def test_a_second_url_is_a_separate_entry(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    transport = _transport(tmp_path, inner, CacheMode.USE, clock)

    transport.handle_request(_request())
    transport.handle_request(_request("https://www.stadt-zuerich.ch/bad-altstetten"))
    transport.handle_request(_request())

    assert inner.calls == 2  # two cold fetches, then one warm hit


def test_an_unstamped_request_round_trips_through_the_default_tier_and_ttl(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)
    request = _request(tier=None, ttl_s=None)

    transport.handle_request(request)
    transport.handle_request(_request(tier=None, ttl_s=None))

    assert inner.calls == 1
    document = json.loads(store.path_for(request, DEFAULT_TIER).read_text(encoding="utf-8"))
    assert document["cache"]["tier"] == DEFAULT_TIER
    assert document["cache"]["ttl_s"] == DEFAULT_TTL_S


@pytest.mark.parametrize("ttl", [0, -1, True, "12h", None])
def test_an_unusable_ttl_stamp_degrades_to_the_default(tmp_path: Path, ttl: object) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)
    request = httpx.Request("GET", URL, extensions={"cache_tier": TIER, "cache_ttl_s": ttl})

    transport.handle_request(request)

    document = json.loads(store.path_for(request, TIER).read_text(encoding="utf-8"))
    assert document["cache"]["ttl_s"] == DEFAULT_TTL_S


def test_the_write_tier_is_the_tier_the_read_looks_in(tmp_path: Path) -> None:
    """Regression guard: `put(tier=)` and `fresh()`'s re-derived tier share one source."""
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)
    request = _request(tier="belegungsplan")

    transport.handle_request(request)

    assert store.path_for(request, "belegungsplan").exists()
    assert store.fresh(_request(tier="belegungsplan"), clock.at) is not None


# --- REFRESH -----------------------------------------------------------------------


def test_refresh_always_refetches_and_overwrites(tmp_path: Path) -> None:
    clock = Clock()
    counter = iter(range(10))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=f"v{next(counter)}".encode()
        )

    inner = RecordingInner(handler)
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.REFRESH, now=clock)

    assert transport.handle_request(_request()).content == b"v0"
    assert transport.handle_request(_request()).content == b"v1"

    assert inner.calls == 2  # a fresh entry existed and was deliberately ignored
    document = json.loads(store.path_for(_request(), TIER).read_text(encoding="utf-8"))
    assert document["response"]["body"] == "v1"


def test_a_refresh_write_is_readable_by_a_later_use_run(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)

    DiskCacheTransport(inner, store, CacheMode.REFRESH, now=clock).handle_request(_request())
    hit = DiskCacheTransport(inner, store, CacheMode.USE, now=clock).handle_request(_request())

    assert inner.calls == 1
    assert hit.content == b"<html>Hallenbad City</html>"


# --- OFF ---------------------------------------------------------------------------


def test_off_passes_through_and_never_touches_the_store(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    transport = _transport(tmp_path, inner, CacheMode.OFF, clock)

    for _ in range(3):
        assert transport.handle_request(_request()).content == b"<html>Hallenbad City</html>"

    assert inner.calls == 3
    assert list(tmp_path.rglob("*")) == []  # nothing written, nothing read


def test_off_does_not_read_a_pre_seeded_entry(tmp_path: Path) -> None:
    clock = Clock()
    store = CacheStore(tmp_path)
    cached = httpx.Response(200, text="stale-cached")
    store.put(_request(), cached, tier=TIER, ttl_s=TTL_S, now=START)
    inner = RecordingInner(_ok(b"live"))

    response = DiskCacheTransport(inner, store, CacheMode.OFF, now=clock).handle_request(_request())

    assert inner.calls == 1
    assert response.content == b"live"


# --- statuses, encodings, failures --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (302, {"location": "https://bad-altstetten.ch/"}),
        (500, {"content-type": "text/html"}),
    ],
)
def test_non_2xx_statuses_are_cached_and_replayed(
    tmp_path: Path, status: int, headers: dict[str, str]
) -> None:
    clock = Clock()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers, content=b"body")

    inner = RecordingInner(handler)
    transport = _transport(tmp_path, inner, CacheMode.USE, clock)

    cold = transport.handle_request(_request())
    warm = transport.handle_request(_request())

    assert inner.calls == 1
    assert (cold.status_code, warm.status_code) == (status, status)
    assert warm.content == b"body"
    for key, value in headers.items():
        assert warm.headers[key] == value


def test_a_transport_error_propagates_and_is_not_cached(tmp_path: Path) -> None:
    clock = Clock()

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    inner = RecordingInner(handler)
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)

    with pytest.raises(httpx.TransportError, match="no route to host"):
        transport.handle_request(_request())

    assert not store.path_for(_request(), TIER).exists()
    assert store.fresh(_request(), clock.at) is None


def test_a_timeout_propagates(tmp_path: Path) -> None:
    clock = Clock()

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    transport = _transport(tmp_path, RecordingInner(handler), CacheMode.USE, clock)

    with pytest.raises(httpx.TimeoutException):
        transport.handle_request(_request())


def test_a_gzip_encoded_response_is_stored_and_replayed_decoded(tmp_path: Path) -> None:
    """The bytes we hand the store are the DECODED ones httpx produces above us."""
    clock = Clock()
    plain = b"<html>Hallenbad</html>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "gzip"},
            content=gzip.compress(plain),
        )

    inner = RecordingInner(handler)
    store = CacheStore(tmp_path)
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)

    cold = transport.handle_request(_request())
    warm = transport.handle_request(_request())

    assert inner.calls == 1
    # Cold and warm are indistinguishable: same bytes, same (framing-free) headers.
    assert cold.content == plain
    assert warm.content == plain
    assert "content-encoding" not in cold.headers
    assert "content-encoding" not in warm.headers
    document = json.loads(store.path_for(_request(), TIER).read_text(encoding="utf-8"))
    assert document["response"]["body"] == plain.decode()


def test_an_unwritable_store_degrades_to_the_network(tmp_path: Path) -> None:
    clock = Clock()
    inner = RecordingInner(_ok())
    store = CacheStore(tmp_path)
    # A plain file where the entry's directory belongs: every write fails, silently.
    parent = store.path_for(_request(), TIER).parent
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.write_text("not a directory", encoding="utf-8")
    transport = DiskCacheTransport(inner, store, CacheMode.USE, now=clock)

    assert transport.handle_request(_request()).content == b"<html>Hallenbad City</html>"
    assert transport.handle_request(_request()).content == b"<html>Hallenbad City</html>"
    assert inner.calls == 2  # never cached, never raised


def test_close_closes_the_inner_transport(tmp_path: Path) -> None:
    inner = RecordingInner(_ok())
    _transport(tmp_path, inner, CacheMode.USE, Clock()).close()

    assert inner.closed


def test_a_naive_clock_is_a_programming_error(tmp_path: Path) -> None:
    inner = RecordingInner(_ok())
    naive = DiskCacheTransport(
        inner, CacheStore(tmp_path), CacheMode.USE, now=lambda: datetime(2026, 7, 31, 9, 0)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        naive.handle_request(_request())


# --- through a real httpx.Client ----------------------------------------------------


def test_a_warm_hit_flows_through_a_real_client(tmp_path: Path) -> None:
    """The end-to-end shape `HttpClient` sees: a hit must be a fully usable response."""
    clock = Clock()
    inner = RecordingInner(_ok(b'{"pools": 57}'))
    transport = _transport(tmp_path, inner, CacheMode.USE, clock)

    with httpx.Client(transport=transport) as client:
        cold = client.get(URL, extensions={"cache_tier": TIER, "cache_ttl_s": TTL_S})
        warm = client.get(URL, extensions={"cache_tier": TIER, "cache_ttl_s": TTL_S})

    assert inner.calls == 1
    assert cold.text == warm.text == '{"pools": 57}'
    assert warm.status_code == 200


def test_a_redirect_hop_is_cached_per_hop_through_a_real_client(tmp_path: Path) -> None:
    """`follow_redirects=True` calls the transport once per hop, so BOTH must be cached."""
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://bad-altstetten.ch/new"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"arrived")

    inner = RecordingInner(handler)
    transport = _transport(tmp_path, inner, CacheMode.USE, clock)

    with httpx.Client(transport=transport, follow_redirects=True) as client:
        first = client.get("https://bad-altstetten.ch/old")
        second = client.get("https://bad-altstetten.ch/old")

    assert inner.calls == 2  # two hops cold, zero warm
    assert first.text == second.text == "arrived"
    assert second.status_code == 200
