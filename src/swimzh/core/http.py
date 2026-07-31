"""An httpx wrapper that returns `Result[Response, ProviderError]` and never raises
for transport/HTTP failures.

The client is **injected**, so tests drive it with `httpx.MockTransport` (for the
timeout / connection-error seams that have no recorded HTTP interaction) or with
vcrpy cassettes (for real 200/500/429/malformed responses).

Retries are value-based: we retry while the mapped error is `retriable()` and attempts
remain, using an injectable `sleep` so tests stay fast and deterministic.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from swimzh.core.cache_tiers import cache_extensions
from swimzh.core.errors import (
    ConnectionFailed,
    DecodeError,
    HttpStatus,
    ProviderError,
    RateLimited,
    Redirect,
    Timeout,
    TooLarge,
    retriable,
)
from swimzh.core.result import Err, Ok, Result

_DEFAULT_MAX_BYTES = 10_000_000
_SNIPPET_BYTES = 200


def _snippet(resp: httpx.Response) -> str:
    return resp.content[:_SNIPPET_BYTES].decode("utf-8", "replace")


def _parse_retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        # HTTP-date form is not handled yet; treat as "unknown".
        return None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base_s: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")


class HttpClient:
    """Thin, value-returning wrapper over an `httpx.Client`."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        source: str = "http",
        timeout_s: float = 10.0,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = lambda _s: None,
    ) -> None:
        self._client = client
        self._source = source
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._retry = retry or RetryPolicy()
        self._sleep = sleep

    def get(self, url: str, **kwargs: object) -> Result[httpx.Response, ProviderError]:
        stamped = self._stamp_cache_policy(kwargs)
        last: ProviderError | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            result = self._get_once(url, **stamped)
            if isinstance(result, Ok):
                return result
            last = result.error
            if attempt < self._retry.max_attempts and retriable(last):
                self._sleep(self._retry.backoff_base_s * (2 ** (attempt - 1)))
                continue
            return result
        # RetryPolicy guarantees max_attempts >= 1, so the loop always ran and returned.
        if last is None:  # pragma: no cover - unreachable
            raise RuntimeError("retry loop did not execute")
        return Err(last)

    def _stamp_cache_policy(self, kwargs: dict[str, object]) -> dict[str, object]:
        """Add this client's cache tier + TTL to the request extensions.

        This is the *only* behavioural change the disk cache asks of `HttpClient`: the
        per-source policy travels as httpx request extensions, which only
        `DiskCacheTransport` ever reads. Without that transport installed the stamp is
        inert — httpx carries unknown extensions untouched — so every provider and every
        existing caller behaves exactly as before.

        The stamp **merges with, never overwrites** a caller-supplied `extensions`: an
        explicit `cache_tier`/`cache_ttl_s` from the call site wins over the table. A
        caller passing a non-mapping `extensions` (an httpx error in its own right) is
        left untouched rather than silently rewritten.
        """
        caller = kwargs.get("extensions")
        if caller is not None and not isinstance(caller, Mapping):
            return kwargs
        extensions = cache_extensions(self._source)
        if isinstance(caller, Mapping):
            extensions.update(caller)
        return {**kwargs, "extensions": extensions}

    def _get_once(self, url: str, **kwargs: object) -> Result[httpx.Response, ProviderError]:
        try:
            resp = self._client.get(url, **kwargs)  # type: ignore[arg-type]
        except httpx.TooManyRedirects as exc:
            location = str(getattr(getattr(exc, "request", None), "url", url))
            return Err(Redirect(url=url, location=location, count=-1))
        except httpx.TimeoutException:
            return Err(Timeout(url=url, after_s=self._timeout_s))
        except httpx.DecodingError as exc:
            return Err(DecodeError(source=self._source, detail=str(exc)))
        except httpx.TransportError as exc:
            # ConnectError, ReadError, ProtocolError, ProxyError, ...
            return Err(ConnectionFailed(url=url, detail=str(exc)))
        except httpx.RequestError as exc:
            # Any remaining request-side error.
            return Err(ConnectionFailed(url=url, detail=str(exc)))
        return self._classify(url, resp)

    def _classify(self, url: str, resp: httpx.Response) -> Result[httpx.Response, ProviderError]:
        if len(resp.content) > self._max_bytes:
            return Err(TooLarge(url=url, limit_bytes=self._max_bytes))
        status = resp.status_code
        if 200 <= status < 300:
            return Ok(resp)
        if status == 429:
            return Err(RateLimited(url=url, retry_after_s=_parse_retry_after(resp)))
        return Err(HttpStatus(url=url, status=status, body_snippet=_snippet(resp)))
