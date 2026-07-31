"""On-disk HTTP cache for the provider pipeline — the pure store half.

`CacheStore` is **pure**: it touches the filesystem and nothing else. It knows how to
turn a request into a cache key + path, how to (de)serialize an `httpx.Response` as one
**human-readable JSON file per entry**, and whether an entry is still fresh. It performs
no network I/O and holds no httpx transport; the transport that turns this into actual
httpx caching lands in a later slice.

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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx

#: Tier used when a request carries no `cache_tier` extension.
DEFAULT_TIER: Final = "default"

#: Request extension keys the transport stamps (read here, written in a later slice).
TIER_EXTENSION: Final = "cache_tier"

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
