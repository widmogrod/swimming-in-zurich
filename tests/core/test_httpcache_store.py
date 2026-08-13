"""Tests for the pure `CacheStore` half of the provider disk cache.

No network and no httpx transport is involved: every test drives the store with a
hand-built `httpx.Request`/`httpx.Response` pair and an explicit, tz-aware clock.
"""

from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.core.httpcache import DEFAULT_TIER, CacheStore, cache_key

ZURICH = ZoneInfo("Europe/Zurich")
NOW = datetime(2026, 7, 31, 9, 0, tzinfo=ZURICH)
URL = "https://www.stadt-zuerich.ch/pools?kind=indoor"
TTL_S = 7 * 24 * 3600


def _request(url: str = URL, *, tier: str | None = None) -> httpx.Request:
    extensions: dict[str, Any] = {} if tier is None else {"cache_tier": tier}
    return httpx.Request("GET", url, extensions=extensions)


def _read_document(store: CacheStore, request: httpx.Request, tier: str) -> dict[str, Any]:
    raw = store.path_for(request, tier).read_text(encoding="utf-8")
    document: dict[str, Any] = json.loads(raw)
    return document


def test_put_then_fresh_round_trips_status_headers_and_body(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request(tier="snapshot")
    response = httpx.Response(
        200,
        headers={"content-type": "application/json", "x-origin": "wfs"},
        content=b'{"pools": 57}',
    )

    store.put(request, response, tier="snapshot", ttl_s=TTL_S, now=NOW)
    hit = store.fresh(request, NOW + timedelta(hours=1))

    assert hit is not None
    assert hit.status_code == 200
    assert hit.content == b'{"pools": 57}'
    assert hit.headers["content-type"] == "application/json"
    assert hit.headers["x-origin"] == "wfs"


def test_text_content_type_is_stored_as_inline_readable_text(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request(tier="snapshot")
    body = b'{"a": 1}'
    response = httpx.Response(200, headers={"content-type": "application/json"}, content=body)

    store.put(request, response, tier="snapshot", ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, "snapshot")
    assert document["response"]["body"] == '{"a": 1}'
    assert document["response"]["body_base64"] is None


@pytest.mark.parametrize(
    "content_type",
    ["text/html; charset=utf-8", "application/xml", "application/ld+json", ""],
)
def test_every_text_ish_content_type_stays_readable(tmp_path: Path, content_type: str) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    headers = {"content-type": content_type} if content_type else {}
    response = httpx.Response(200, headers=headers, content=b"<html>Hallenbad</html>")

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, DEFAULT_TIER)
    assert document["response"]["body"] == "<html>Hallenbad</html>"
    assert document["response"]["body_base64"] is None


def test_binary_content_type_is_stored_base64_and_round_trips_byte_exact(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request("https://example.test/belegungsplan.pdf", tier="belegungsplan")
    pdf = b"%PDF-1.4\n\x00\x80\xffbytes"
    response = httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)

    store.put(request, response, tier="belegungsplan", ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, "belegungsplan")
    assert document["response"]["body"] is None
    assert base64.b64decode(document["response"]["body_base64"]) == pdf

    hit = store.fresh(request, NOW)
    assert hit is not None
    assert hit.content == pdf


@pytest.mark.parametrize("content_type", ["image/png", "application/octet-stream"])
def test_other_binary_content_types_are_base64(tmp_path: Path, content_type: str) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    response = httpx.Response(200, headers={"content-type": content_type}, content=b"\x89PNG")

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, DEFAULT_TIER)
    assert document["response"]["body"] is None
    assert document["response"]["body_base64"] is not None


def test_non_utf8_body_under_a_text_content_type_falls_back_to_base64(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    latin1 = "Höngg".encode("latin-1")
    response = httpx.Response(200, headers={"content-type": "text/html"}, content=latin1)

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, DEFAULT_TIER)
    assert document["response"]["body"] is None
    assert base64.b64decode(document["response"]["body_base64"]) == latin1

    hit = store.fresh(request, NOW)
    assert hit is not None
    assert hit.content == latin1


def test_gzip_encoded_response_round_trips_decoded_and_never_raises(tmp_path: Path) -> None:
    """httpx sends `Accept-Encoding: gzip` by default, so this is the COMMON warm hit.

    `response.content` is already gunzipped by httpx while `content-encoding: gzip` is
    still on the headers. Replaying that header over decoded bytes would make
    `httpx.Response.__init__` try to gunzip plain text and raise `httpx.DecodingError`
    out of `fresh()`. The response here is shaped exactly as the S2 transport will hand
    it over: built from a compressed stream, then `.read()`.
    """
    store = CacheStore(tmp_path)
    request = _request()
    plain = b"<html>Hallenbad City</html>"
    response = httpx.Response(
        200,
        headers={"content-type": "text/html", "content-encoding": "gzip"},
        content=gzip.compress(plain),
    )
    response.read()
    assert response.content == plain  # httpx decoded it above the transport

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, DEFAULT_TIER)
    assert document["response"]["body"] == "<html>Hallenbad City</html>"
    assert "content-encoding" not in document["response"]["headers"]
    assert "content-length" not in document["response"]["headers"]
    assert document["response"]["headers"]["content-type"] == "text/html"

    hit = store.fresh(request, NOW)
    assert hit is not None
    assert hit.content == plain


def test_a_legacy_entry_carrying_content_encoding_still_replays(tmp_path: Path) -> None:
    """Defence in depth: a hand-written/pre-normalization document must not raise."""
    store = CacheStore(tmp_path)
    request = _request()
    path = store.path_for(request, DEFAULT_TIER)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cache": {"expires_at": "2099-01-01T00:00:00+01:00"},
                "response": {
                    "status": 200,
                    "headers": {"content-type": "text/html", "content-encoding": "gzip"},
                    "body": "<html>plain</html>",
                    "body_base64": None,
                },
            }
        ),
        encoding="utf-8",
    )

    hit = store.fresh(request, NOW)
    assert hit is not None
    assert hit.content == b"<html>plain</html>"


def test_stale_content_length_is_not_replayed(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    response = httpx.Response(200, headers={"content-type": "text/html"}, content=b"12345")

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    document = _read_document(store, request, DEFAULT_TIER)
    assert "content-length" not in document["response"]["headers"]
    hit = store.fresh(request, NOW)
    assert hit is not None
    # httpx recomputes framing from the body we actually stored.
    assert hit.headers["content-length"] == "5"


def test_non_2xx_statuses_are_cached_and_replayed(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    response = httpx.Response(302, headers={"location": "https://bad-altstetten.ch/"})

    store.put(request, response, tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    hit = store.fresh(request, NOW)
    assert hit is not None
    assert hit.status_code == 302
    assert hit.headers["location"] == "https://bad-altstetten.ch/"


def test_entry_past_expires_at_is_a_miss(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    store.put(request, httpx.Response(200), tier=DEFAULT_TIER, ttl_s=60, now=NOW)

    assert store.fresh(request, NOW + timedelta(seconds=59)) is not None
    # The boundary itself is already expired (`now < expires_at` is the freshness rule).
    assert store.fresh(request, NOW + timedelta(seconds=60)) is None
    assert store.fresh(request, NOW + timedelta(seconds=61)) is None


def test_missing_entry_is_a_miss(tmp_path: Path) -> None:
    assert CacheStore(tmp_path).fresh(_request(), NOW) is None


def test_corrupt_json_file_is_a_miss_and_never_raises(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    store.put(request, httpx.Response(200, text="ok"), tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    path = store.path_for(request, DEFAULT_TIER)
    path.write_text("{ this is not json", encoding="utf-8")

    assert store.fresh(request, NOW) is None


@pytest.mark.parametrize(
    "document",
    [
        {"cache": {}, "response": {}},
        {"cache": {"expires_at": "not-a-date"}, "response": {}},
        {"cache": {"expires_at": "2026-07-31T10:00:00"}, "response": {}},  # naive
        {"cache": {"expires_at": 12345}, "response": {}},
        {
            "cache": {"expires_at": "2099-01-01T00:00:00+01:00"},
            "response": {"status": 200, "headers": {}, "body": None, "body_base64": None},
        },
        {
            "cache": {"expires_at": "2099-01-01T00:00:00+01:00"},
            "response": {"status": 200, "headers": {}, "body": None, "body_base64": "!!not-b64"},
        },
        {
            "cache": {"expires_at": "2099-01-01T00:00:00+01:00"},
            "response": {"status": 200, "headers": {}, "body": None, "body_base64": 7},
        },
    ],
)
def test_malformed_documents_are_misses(tmp_path: Path, document: dict[str, Any]) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    path = store.path_for(request, DEFAULT_TIER)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    assert store.fresh(request, NOW) is None


def test_unreadable_path_is_a_miss_and_never_raises(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    # A directory where the entry file belongs: reading it raises OSError.
    store.path_for(request, DEFAULT_TIER).mkdir(parents=True)

    assert store.fresh(request, NOW) is None


def test_unwritable_destination_is_swallowed(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    # A plain file where the entry's parent directory belongs: mkdir raises OSError.
    parent = store.path_for(request, DEFAULT_TIER).parent
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.write_text("not a directory", encoding="utf-8")

    store.put(request, httpx.Response(200), tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    assert store.fresh(request, NOW) is None


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request()
    # A directory where the entry file belongs: the atomic rename onto it raises OSError.
    path = store.path_for(request, DEFAULT_TIER)
    path.mkdir(parents=True)

    store.put(request, httpx.Response(200, text="ok"), tier=DEFAULT_TIER, ttl_s=TTL_S, now=NOW)

    assert list(path.parent.glob("*.tmp")) == []
    assert store.fresh(request, NOW) is None


def test_on_disk_file_is_pretty_json_with_the_documented_shape(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request(tier="static")
    response = httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    store.put(request, response, tier="static", ttl_s=TTL_S, now=NOW)

    raw = store.path_for(request, "static").read_text(encoding="utf-8")
    assert raw.startswith("{\n  ")  # indent=2, pretty
    assert raw.endswith("\n")
    document = json.loads(raw)
    assert set(document) == {"cache", "request", "response"}
    assert document["cache"] == {
        "key": cache_key(request),
        "tier": "static",
        "fetched_at": NOW.isoformat(),
        "ttl_s": TTL_S,
        "expires_at": (NOW + timedelta(seconds=TTL_S)).isoformat(),
    }
    assert document["request"]["method"] == "GET"
    assert document["request"]["url"] == URL
    assert isinstance(document["request"]["headers"], dict)
    assert document["response"]["status"] == 200
    assert document["response"]["content_type"] == "application/json"
    assert isinstance(document["response"]["headers"], dict)


def test_key_and_path_scheme(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = _request(tier="static")

    key = cache_key(request)
    assert len(key) == 16
    assert store.path_for(request, "static") == (
        tmp_path / "static" / "www.stadt-zuerich.ch" / f"{key}.json"
    )
    # Method and query both participate in the key.
    assert cache_key(httpx.Request("HEAD", URL)) != key
    assert cache_key(httpx.Request("GET", "https://www.stadt-zuerich.ch/pools?kind=outdoor")) != key


def test_hostless_url_falls_back_to_a_stable_directory(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    request = httpx.Request("GET", "file:///tmp/roster.json")

    assert store.path_for(request, DEFAULT_TIER).parent.name == "unknown-host"


def test_fresh_reads_the_tier_from_the_request_extensions(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    stamped = _request(tier="belegungsplan")
    store.put(stamped, httpx.Response(200, text="ok"), tier="belegungsplan", ttl_s=TTL_S, now=NOW)

    assert store.fresh(stamped, NOW) is not None
    # The same URL without the stamp looks in the default tier — a different entry.
    assert store.fresh(_request(), NOW) is None
    # An ill-typed stamp degrades to the default tier rather than exploding.
    assert store.fresh(httpx.Request("GET", URL, extensions={"cache_tier": 7}), NOW) is None


@pytest.mark.parametrize("tier", ["static", DEFAULT_TIER])
def test_naive_timestamps_are_rejected(tmp_path: Path, tier: str) -> None:
    store = CacheStore(tmp_path)
    naive = datetime(2026, 7, 31, 9, 0)  # deliberately naive

    with pytest.raises(ValueError, match="timezone-aware"):
        store.fresh(_request(), naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.put(_request(), httpx.Response(200), tier=tier, ttl_s=TTL_S, now=naive)
