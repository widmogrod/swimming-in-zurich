"""The standardised, closed `ProviderError` union.

Every provider fails with one of these variants. The union is **closed**: consumers can
`match` it and end with `assert_never`, and pyright `--strict` will flag any unhandled
case. Provider-specific detail rides inside `ProviderSpecific` (an escape hatch that
keeps the union closed) rather than widening the type per provider — `A | B` widening
would break `assert_never` at shared call sites.

Deliberately **not** modelled as errors:
  * seasonal-off / expected-absence  -> a domain state returned as `Ok(...)`.
  * empty-but-valid 200 response      -> a domain state returned as `Ok(...)`.
  * 304 Not Modified                  -> a cache-hit success, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

# The JSON value space — the only shapes that survive a lossless persist through the boundary
# DTO. `ProviderSpecific.detail` is narrowed to this (from `object`) so the whole closed union
# round-trips through the gold codec with no variant special-cased and no lossy `repr`.
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class Timeout:
    """The request exceeded its time budget (connect/read/write/pool)."""

    url: str
    after_s: float


@dataclass(frozen=True, slots=True)
class ConnectionFailed:
    """DNS failure, connection refused/reset — could not establish a usable connection."""

    url: str
    detail: str


@dataclass(frozen=True, slots=True)
class HttpStatus:
    """A non-2xx response that is not a more specific variant below."""

    url: str
    status: int
    body_snippet: str


@dataclass(frozen=True, slots=True)
class RateLimited:
    """HTTP 429 (or an equivalent signal). Retry after `retry_after_s` if present."""

    url: str
    retry_after_s: float | None


@dataclass(frozen=True, slots=True)
class DecodeError:
    """Transport-level decode failure: charset/gzip/content-encoding — distinct from
    `ParseError`, which is about well-decoded text that we could not structure."""

    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class ParseError:
    """Bytes/text could not be turned into a structured tree (invalid JSON, unreadable
    PDF, malformed HTML)."""

    source: str
    detail: str
    raw_snippet: str


@dataclass(frozen=True, slots=True)
class SchemaMismatch:
    """A tree parsed fine, but it did not satisfy the expected schema/contract
    (e.g. pydantic validation failed). The upstream shape likely changed."""

    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class TooLarge:
    """The response exceeded a configured size limit before/while reading."""

    url: str
    limit_bytes: int


@dataclass(frozen=True, slots=True)
class Redirect:
    """Redirect loop or too many redirects."""

    url: str
    location: str
    count: int


@dataclass(frozen=True, slots=True)
class ProviderSpecific:
    """Closed escape hatch for a failure that does not fit the shared variants.

    `provider` identifies the source; `detail` carries provider-defined data. Generic
    consumers can handle it uniformly (log/surface `detail`); a provider's own code may
    narrow `detail` via its own guard. This keeps the shared union closed and every
    `assert_never` valid.
    """

    provider: str
    detail: JsonValue


type ProviderError = (
    Timeout
    | ConnectionFailed
    | HttpStatus
    | RateLimited
    | DecodeError
    | ParseError
    | SchemaMismatch
    | TooLarge
    | Redirect
    | ProviderSpecific
)


def retriable(error: ProviderError) -> bool:
    """Whether retrying the same request could plausibly succeed.

    Retriability is decided here, once, by exhaustive match — never inferred ad hoc at
    call sites. Adding a new variant without classifying it fails `pyright --strict`.
    """
    match error:
        case Timeout() | ConnectionFailed() | RateLimited() | Redirect():
            return True
        case (
            HttpStatus()
            | DecodeError()
            | ParseError()
            | SchemaMismatch()
            | TooLarge()
            | ProviderSpecific()
        ):
            return False
        case _ as unreachable:
            assert_never(unreachable)


def describe(error: ProviderError) -> str:
    """A short, human-readable, non-sensitive description for logs and UI."""
    match error:
        case Timeout(url, after_s):
            return f"timeout after {after_s:.1f}s: {url}"
        case ConnectionFailed(url, detail):
            return f"connection failed ({detail}): {url}"
        case HttpStatus(url, status, _snippet):
            return f"HTTP {status}: {url}"
        case RateLimited(url, retry_after_s):
            hint = f", retry after {retry_after_s:.0f}s" if retry_after_s is not None else ""
            return f"rate limited: {url}{hint}"
        case DecodeError(source, detail):
            return f"decode error from {source}: {detail}"
        case ParseError(source, detail, _raw):
            return f"parse error from {source}: {detail}"
        case SchemaMismatch(source, detail):
            return f"schema mismatch from {source}: {detail}"
        case TooLarge(url, limit_bytes):
            return f"response too large (> {limit_bytes} bytes): {url}"
        case Redirect(url, location, count):
            return f"redirect loop ({count}) at {url} -> {location}"
        case ProviderSpecific(provider, detail):
            return f"{provider} error: {detail!r}"
        case _ as unreachable:
            assert_never(unreachable)
