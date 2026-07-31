"""On-disk HTTP cache for the provider pipeline — the pure store plus its transport.

`CacheStore` is **pure**: it touches the filesystem and nothing else. It knows how to
turn a request into a cache key + path, how to (de)serialize an `httpx.Response` as one
**human-readable JSON file per entry**, and whether an entry is still fresh. It performs
no network I/O and holds no httpx transport.

`DiskCacheTransport` is the httpx seam that turns the store into actual caching: it wraps
an inner transport, so `HttpClient` and every provider stay byte-unchanged.

Two properties are load-bearing:

* **Inspectability.** The body is stored as inline UTF-8 **text** by default, so a
  developer can `cat`/`jq` exactly what a site returned. Only a *binary* content-type
  (`application/pdf`, `application/octet-stream`, `image/*`, …) — or a body that is not
  valid UTF-8 — falls back to `body_base64`. Exactly one of `body` / `body_base64` is
  ever set.
* **No entry fault ever raises.** A missing, unreadable, hand-corrupted or otherwise
  unusable *entry* is a **miss**, never an exception: the cache is an accelerator, and a
  broken one must degrade to the network rather than break a build. (Caller-contract
  violations are a different matter and do raise — see `_require_aware`: a naive `now` is
  a programming error in our own code, not a damaged cache file.)

**Bodies are stored decoded, so transfer headers are dropped.** `httpx` decodes
`content-encoding` above the transport, so `response.content` is already gunzipped while
the header still says `gzip`. Replaying that header over decoded bytes makes
`httpx.Response.__init__` try to gunzip plain text and raise `httpx.DecodingError`. The
store therefore strips `content-encoding`/`content-length`/`transfer-encoding` on write:
the stored bytes describe themselves, and the on-disk file stays honest about what it
holds.

On-disk layout: ``<root>/<tier>/<host>/<key16>.json``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, assert_never

import httpx

#: Where the cache lives unless a composition root says otherwise. Relative to the working
#: directory on purpose: it is a per-checkout dev/build accelerator, git-ignored, never a
#: runtime source of truth. Both composition roots (`swimzh.cli`, `apps.web.main`) name it.
DEFAULT_CACHE_ROOT: Final = Path(".cache/swimzh")

#: Tier used when a request carries no `cache_tier` extension.
DEFAULT_TIER: Final = "default"

#: TTL used when a request carries no (or an unusable) `cache_ttl_s` extension.
DEFAULT_TTL_S: Final = 3600

#: Request extension keys the transport reads (written by `HttpClient` in a later slice).
TIER_EXTENSION: Final = "cache_tier"
TTL_EXTENSION: Final = "cache_ttl_s"

_KEY_LEN: Final = 16

# Content types whose bodies stay readable on disk. Everything else is treated as binary.
_TEXT_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/x-www-form-urlencoded",
        "application/yaml",
        "application/x-yaml",
        "application/graphql",
    }
)
_TEXT_SUFFIXES: Final = ("+json", "+xml")

# Headers that describe the *wire* framing of a body we store already-decoded. Replaying
# them would make httpx re-decode (or mis-size) bytes that are no longer encoded.
_STRIPPED_HEADERS: Final[frozenset[str]] = frozenset(
    {"content-encoding", "content-length", "transfer-encoding"}
)


def cache_key(request: httpx.Request) -> str:
    """Derive the entry key from method + full URL (the query lives in the URL)."""
    raw = f"{request.method} {request.url}".encode()
    return hashlib.sha256(raw).hexdigest()[:_KEY_LEN]


def request_tier(request: httpx.Request) -> str:
    """The tier stamped on the request, or `DEFAULT_TIER` when none/ill-typed."""
    tier = request.extensions.get(TIER_EXTENSION)
    return tier if isinstance(tier, str) and tier else DEFAULT_TIER


def request_ttl_s(request: httpx.Request) -> int:
    """The TTL stamped on the request, or `DEFAULT_TTL_S` when none/ill-typed.

    `bool` is excluded explicitly: it is an `int` subclass, and `True` as a TTL is a
    one-second cache — silently useless rather than loudly wrong.

    **A `0` (or negative) stamp is not a per-request bypass.** It is treated as "no usable
    TTL given" and falls back to `DEFAULT_TTL_S`, so reaching for `cache_ttl_s=0` to mean
    "don't cache this one" gets an hour of caching, the opposite of the intent. Skipping
    the cache is a *mode*, not a TTL: use `CacheMode.OFF`.
    """
    ttl = request.extensions.get(TTL_EXTENSION)
    if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl > 0:
        return ttl
    return DEFAULT_TTL_S


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _is_text_media_type(media_type: str) -> bool:
    """Text by default: unknown/absent content types are stored readable, not base64."""
    if not media_type:
        return True
    if media_type.startswith("text/"):
        return True
    if media_type.endswith(_TEXT_SUFFIXES):
        return True
    return media_type in _TEXT_MEDIA_TYPES


def _encode_body(body: bytes, media_type: str) -> tuple[str | None, str | None]:
    """Return `(body, body_base64)` — exactly one of them is non-None."""
    if _is_text_media_type(media_type):
        try:
            return body.decode("utf-8"), None
        except UnicodeDecodeError:
            # Safety fallback: a text-ish content type lying about its bytes.
            pass
    return None, base64.b64encode(body).decode("ascii")


def _decode_body(payload: Mapping[str, Any]) -> bytes:
    encoded = payload["body_base64"]
    if encoded is not None:
        if not isinstance(encoded, str):
            raise TypeError("body_base64 must be a string")
        return base64.b64decode(encoded, validate=True)
    body = payload["body"]
    if not isinstance(body, str):
        raise TypeError("cache entry carries neither body nor body_base64")
    return body.encode("utf-8")


def _parse_expiry(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise TypeError("expires_at must be an ISO-8601 string")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    return parsed


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("cache timestamps must be timezone-aware (Europe/Zurich)")


@dataclass(frozen=True, slots=True)
class CacheStore:
    """A filesystem-backed store of one pretty-JSON file per cached response."""

    root: Path

    def path_for(self, request: httpx.Request, tier: str) -> Path:
        host = request.url.host or "unknown-host"
        return self.root / tier / host / f"{cache_key(request)}.json"

    def fresh(self, request: httpx.Request, now: datetime) -> httpx.Response | None:
        """The cached response iff an entry exists and `now` is before its expiry.

        The tier is re-derived from `request.extensions` (see `request_tier`), which is
        the asymmetry with `put`'s explicit `tier=` — see the note there.

        Any missing, unreadable, or malformed entry is a **miss** (`None`). The
        `httpx.HTTPError` arm is defence in depth: `_serialize` already strips the
        transfer headers that could make `httpx.Response` reject a stored body, so an
        entry that still trips it is a hand-written or legacy file, and a damaged entry
        must degrade to a miss rather than raise into a provider.
        """
        _require_aware(now)
        path = self.path_for(request, request_tier(request))
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if now >= _parse_expiry(document["cache"]["expires_at"]):
                return None
            return _rebuild(document["response"])
        except (OSError, ValueError, TypeError, KeyError, httpx.HTTPError):
            return None

    def put(
        self,
        request: httpx.Request,
        response: httpx.Response,
        *,
        tier: str,
        ttl_s: int,
        now: datetime,
    ) -> None:
        """Write (or overwrite) the entry. Disk faults are swallowed — never raise.

        **The caller owns tier consistency.** `put` takes `tier` explicitly, but `fresh`
        re-derives it from `request.extensions["cache_tier"]`. Writing under a `tier` that
        does not match the stamp the same request carries at read time silently produces a
        permanent miss (the entry lands in a directory nothing ever looks in). A caller
        driving both sides — the transport in S2 — must take both from the same source.
        """
        _require_aware(now)
        document = _serialize(request, response, tier=tier, ttl_s=ttl_s, now=now)
        _write_atomic(self.path_for(request, tier), document)


def _storable_headers(headers: httpx.Headers | Mapping[str, str]) -> dict[str, str]:
    """Headers minus the wire-framing ones, which no longer describe the stored body."""
    return {k: v for k, v in dict(headers).items() if k.lower() not in _STRIPPED_HEADERS}


def _rebuild(payload: Mapping[str, Any]) -> httpx.Response:
    # Filtered on read too, so a hand-written or pre-normalization entry still replays.
    return httpx.Response(
        status_code=int(payload["status"]),
        headers=httpx.Headers(_storable_headers(payload["headers"])),
        content=_decode_body(payload),
    )


def _serialize(
    request: httpx.Request,
    response: httpx.Response,
    *,
    tier: str,
    ttl_s: int,
    now: datetime,
) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    body, body_base64 = _encode_body(response.content, _media_type(content_type))
    return {
        "cache": {
            "key": cache_key(request),
            "tier": tier,
            "fetched_at": now.isoformat(),
            "ttl_s": ttl_s,
            "expires_at": (now + timedelta(seconds=ttl_s)).isoformat(),
        },
        "request": {
            "method": request.method,
            "url": str(request.url),
            "headers": _storable_headers(request.headers),
        },
        "response": {
            "status": response.status_code,
            "content_type": content_type,
            "headers": _storable_headers(response.headers),
            "body": body,
            "body_base64": body_base64,
        },
    }


def _write_atomic(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(tmp_name, path)
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except OSError:
        # A cache that cannot be written is a cache miss, not a build failure.
        return


class CacheMode(StrEnum):
    """How `DiskCacheTransport` treats the store on each request.

    * `USE` — read a fresh entry if there is one, otherwise fetch once and write through.
    * `REFRESH` — never read; always fetch once and overwrite the entry.
    * `OFF` — never read, never write; behaviourally identical to no cache at all.
    """

    USE = "use"
    REFRESH = "refresh"
    OFF = "off"


class DiskCacheTransport(httpx.BaseTransport):
    """An `httpx` transport that serves fresh entries from a `CacheStore`.

    Being a transport is the whole point: `HttpClient` and all five providers are
    untouched, and a cache hit returns a perfectly ordinary `httpx.Response`, so
    `HttpClient._classify` keeps mapping statuses to the `ProviderError` union exactly as
    it does live (a cached 500 is still `HttpStatus`). Nothing new is raised here: a miss
    delegates to `inner`, whose `TransportError`/`TimeoutException` propagate untouched
    into `HttpClient`'s existing `try/except`, and every store fault is already a miss.

    **The clock is injected** (`now`), so freshness is deterministic under test. It must
    return tz-aware datetimes (`Europe/Zurich`); a naive one is a programming error and
    the store raises, as it does for any other caller.

    **Buffer-only.** `handle_request` reads the inner response to completion before
    returning. `client.stream(...)` still *works* — it yields the whole body in the
    requested chunk sizes, cold and warm alike — but it is **defeated**: every byte is in
    memory before the caller sees the first chunk, so there is no incremental delivery and
    no bounded memory. The pipeline uses `.get()` only, and `HttpClient(max_bytes=…)`
    bounds the payloads.

    **Tier consistency.** Reads and writes both take the tier from
    `request.extensions["cache_tier"]` via `request_tier`, so a write can never land in a
    directory the matching read does not visit (see `CacheStore.put`).
    """

    def __init__(
        self,
        inner: httpx.BaseTransport,
        store: CacheStore,
        mode: CacheMode,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._store = store
        self._mode = mode
        self._now = now

    @property
    def mode(self) -> CacheMode:
        """The mode this transport was wired with — public so a composition-root test can
        assert what a wiring function actually built (the web runtime must be `OFF`)."""
        return self._mode

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        match self._mode:
            case CacheMode.OFF:
                return self._inner.handle_request(request)
            case CacheMode.USE:
                hit = self._store.fresh(request, self._now())
                if hit is not None:
                    return hit
            case CacheMode.REFRESH:
                pass
            case _:  # pragma: no cover - exhaustive over CacheMode
                assert_never(self._mode)
        return self._fetch_and_store(request)

    def close(self) -> None:
        self._inner.close()

    def _fetch_and_store(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        response.request = request
        # `read()` yields **decoded** bytes (httpx applies `content-encoding` here, above
        # the transport), which is exactly what the store's contract expects.
        body = response.read()
        self._store.put(
            request,
            response,
            tier=request_tier(request),
            ttl_s=request_ttl_s(request),
            now=self._now(),
        )
        return _replay(response.status_code, response.headers, body, response.extensions)


def _replay(
    status_code: int,
    headers: httpx.Headers,
    body: bytes,
    extensions: Mapping[str, Any],
) -> httpx.Response:
    """Rebuild a fresh, unread response over already-buffered bytes.

    A miss returns a *rebuilt* response rather than the consumed inner one, for two
    reasons. The consumed response is already closed and its stream exhausted, and — more
    importantly — it still carries the wire-framing headers (`content-encoding`,
    `content-length`) that no longer describe its decoded body. Stripping them here, with
    the same rule the store applies on write, gives cold/warm parity over exactly what the
    store persists: **status, headers and body**.

    That parity stops at the stored fields, and deliberately so. Only those three are on
    disk, so a warm replay (`_rebuild`) carries no `extensions` and no custom
    `reason_phrase`, while the cold response here forwards the inner transport's
    `extensions` (`http_version` and friends — worth keeping for live diagnostics). Every
    consumer in this repo reads status, headers and body only; a future caller that starts
    reading `reason_phrase` or an extension would have to persist it first.
    """
    return httpx.Response(
        status_code=status_code,
        headers=httpx.Headers(_storable_headers(headers)),
        content=body,
        extensions=dict(extensions),
    )
