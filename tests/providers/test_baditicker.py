"""Baditicker adapter: parser pinned against a saved real feed (offline, no network), the fetch
seam + error mapping via `httpx.MockTransport`, and the TTL cache proven deterministic with an
injected clock + a transport call counter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from swimzh.core.errors import (
    ConnectionFailed,
    ParseError,
    ProviderSpecific,
    SchemaMismatch,
    Timeout,
)
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.providers.baditicker import BaditickerProvider, fetch, parse

_ZURICH = ZoneInfo("Europe/Zurich")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "baditicker.xml"


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="baditicker", retry=RetryPolicy(max_attempts=1))


class _CountingHandler:
    """A MockTransport handler that serves fixed bytes and counts how many times it is hit."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.calls = 0

    def __call__(self, _request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, content=self._body)


class _FrozenClock:
    """A settable clock so the TTL window is exercised without wall-clock sleeping."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


# --- parser pinned against the saved real feed -------------------------------------------


def test_parses_saved_feed_fixture() -> None:
    result = parse(FIXTURE.read_bytes())
    assert isinstance(result, Ok), result
    readings = result.value

    # Freibad Heuried (fb012): 23 °C, closed ("geschlossen"), tz-aware Europe/Zurich timestamp.
    heuried = readings["fb012"]
    assert heuried.celsius == Decimal("23")
    assert heuried.is_open is False  # from "geschlossen"
    assert heuried.source == "baditicker"
    assert heuried.measured_at == datetime(2026, 7, 25, 20, 39, tzinfo=_ZURICH)
    assert heuried.measured_at.tzinfo is not None  # tz-aware, per house convention

    # An open outdoor bath ("offen") parses True.
    assert readings["flb6940"].is_open is True

    # An empty <temperatureWater></temperatureWater> cell -> celsius=None (measured nothing yet),
    # NOT an error — the reading still carries open/closed + freshness.
    blaesi = readings["hb005"]
    assert blaesi.celsius is None
    assert blaesi.is_open is False  # empty openClosedTextPlain -> not "offen"
    # Käferberg: empty temp cell but "offen" — celsius None yet still a live open reading.
    assert readings["hb007"].celsius is None
    assert readings["hb007"].is_open is True


def test_fetch_returns_feed_bytes() -> None:
    body = FIXTURE.read_bytes()
    client = _mock_client(lambda _r: httpx.Response(200, content=body))
    result = fetch(client, "https://feed.test/bathdatadownload")
    assert isinstance(result, Ok), result
    assert result.value == body


# --- error mapping (MockTransport / crafted bytes) ---------------------------------------


def test_timeout_is_typed_error() -> None:
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    result = fetch(_mock_client(_timeout), "https://feed.test")
    assert isinstance(result, Err)
    assert isinstance(result.error, Timeout)


def test_connection_error_is_typed_error() -> None:
    def _refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = fetch(_mock_client(_refused), "https://feed.test")
    assert isinstance(result, Err)
    assert isinstance(result.error, ConnectionFailed)


def test_malformed_body_is_parse_error() -> None:
    # Bytes that are not valid UTF-8 text -> ParseError (undecodable).
    result = parse(b"\xff\xfe not decodable as utf-8")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_wrong_shape_is_schema_mismatch() -> None:
    # Valid text, but the feed's <baths> element is absent -> SchemaMismatch.
    result = parse(b"<bathinfos><meta><version>4</version></meta></bathinfos>")
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_bath_missing_poiid_is_schema_mismatch() -> None:
    body = (
        b"<bathinfos><baths><bath>"
        b"<title>No Id</title><temperatureWater>21</temperatureWater>"
        b"<dateModified><![CDATA[Sa., 25.07.2026 21:02]]></dateModified>"
        b"<openClosedTextPlain><![CDATA[offen]]></openClosedTextPlain>"
        b"</bath></baths></bathinfos>"
    )
    result = parse(body)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_unparseable_date_is_parse_error() -> None:
    body = (
        b"<bathinfos><baths><bath>"
        b"<poiid>fb999</poiid><temperatureWater>21</temperatureWater>"
        b"<dateModified><![CDATA[not a date]]></dateModified>"
        b"<openClosedTextPlain><![CDATA[offen]]></openClosedTextPlain>"
        b"</bath></baths></bathinfos>"
    )
    result = parse(body)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


# --- BaditickerProvider port + TTL cache -------------------------------------------------


def test_provider_read_returns_reading() -> None:
    client = _mock_client(lambda _r: httpx.Response(200, content=FIXTURE.read_bytes()))
    provider = BaditickerProvider(client, url="https://feed.test")
    result = provider.read("fb012")
    assert isinstance(result, Ok), result
    assert result.value.celsius == Decimal("23")


def test_provider_unknown_poiid_is_provider_specific() -> None:
    client = _mock_client(lambda _r: httpx.Response(200, content=FIXTURE.read_bytes()))
    provider = BaditickerProvider(client, url="https://feed.test")
    result = provider.read("does-not-exist")
    assert isinstance(result, Err)
    assert isinstance(result.error, ProviderSpecific)


def test_ttl_cache_collapses_bursts_to_one_fetch() -> None:
    handler = _CountingHandler(FIXTURE.read_bytes())
    clock = _FrozenClock(datetime(2026, 7, 26, 12, 0, tzinfo=_ZURICH))
    provider = BaditickerProvider(
        _mock_client(handler), url="https://feed.test", ttl=timedelta(seconds=120), clock=clock
    )

    # Five reads inside the TTL window (many per-request /pools/{id} hits) -> exactly ONE fetch.
    for _ in range(5):
        assert isinstance(provider.read("fb012"), Ok)
    assert handler.calls == 1

    # Past the TTL, the snapshot is refreshed -> one more fetch (the cache is a window, not a lock).
    clock.now = clock.now + timedelta(seconds=121)
    assert isinstance(provider.read("fb012"), Ok)
    assert handler.calls == 2
