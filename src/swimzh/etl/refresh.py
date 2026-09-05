"""The per-source refresh policy: what ONE run does with ONE silver source.

This is the whole cadence story, in code rather than in anyone's cron. For each silver source
the run asks, in order:

1. **Is the stored silver younger than the source's TTL?** Then it is not due: reuse it as-is
   (`fresh`, no network). A daily cron and a weekly cron produce the same lake.
2. **Due (or forced): fetch + parse.** On `Ok`, write a new silver document (`fresh`).
3. **The fetch failed transiently** (timeout, connection refused, a 5xx, a rate limit) and a
   previous document exists that is younger than the source's `max_stale`: keep it and mark it
   `stale`. The build goes on and says so (exit 2).
4. **Otherwise abort** — a 200 that will not parse (`SchemaMismatch`, `ParseError`, ...) is
   schema drift, never something to paper over with last week's facts; a first run has nothing
   to keep; a document past `max_stale` is too old to trust. All three are the same hard stop
   the build had before the lake existed.

The policy is generic over the payload type: each phase hands in its fetch closure and its
silver codec pair, and gets back the decoded value plus the header that describes it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, assert_never

from swimzh.core.cache_tiers import CachePolicy, policy_for
from swimzh.core.errors import HttpStatus, ProviderError, describe, retriable
from swimzh.core.result import Err, Ok, Result
from swimzh.storage.lake import Lake, SilverHeader, SilverStatus

#: Silver source → the provider source whose `CachePolicy` (TTL + max_stale) governs it. A
#: phase that fans out to two providers is governed by its more volatile one.
POLICY_SOURCE: Final[dict[str, str]] = {
    "roster": "geo_sport",
    "prices": "price_scraper",
    "schedules": "schedule_scraper",
    "lane_plans": "belegungsplan",
}


def silver_policy(source: str) -> CachePolicy:
    """The cache policy governing one silver source."""
    return policy_for(POLICY_SOURCE[source])


def transient(error: ProviderError) -> bool:
    """Is this the kind of failure a kept silver may stand in for?

    `retriable()` names the network-level causes (timeout, connection, rate limit, redirect
    loop); a server-side 5xx is the other one — the site is *there* but broken, which is what
    Friday's `HTTP 500` from the WFS was. Everything else — a 4xx, an unparseable body, a schema
    mismatch — is a fact about OUR contract with the source and must abort, not degrade.
    """
    if retriable(error):
        return True
    return isinstance(error, HttpStatus) and error.status >= 500


@dataclass(frozen=True, slots=True)
class Refreshed[T]:
    """One silver source after the policy ran: its decoded value and the header describing it.

    `fetched` is True only when THIS run hit the network and wrote a new document.
    """

    value: T
    header: SilverHeader
    fetched: bool

    @property
    def stale(self) -> bool:
        return self.header.status is SilverStatus.STALE


RefreshReason = Literal["not_transient", "first_run", "too_stale"]


@dataclass(frozen=True, slots=True)
class RefreshFailure:
    """Why a source could not be refreshed OR kept — the build's abort cause, typed."""

    source: str
    reason: RefreshReason
    cause: ProviderError
    age: timedelta | None = None

    def describe(self) -> str:
        why = describe(self.cause)
        if self.reason == "not_transient":
            return f"{self.source}: {why}"
        if self.reason == "first_run":
            return f"{self.source}: {why} (no previous silver to keep — first run)"
        days = self.age.total_seconds() / 86400.0 if self.age is not None else 0.0
        return f"{self.source}: {why} (previous silver is {days:.1f} d old, past max_stale)"


def refresh_source[T](
    lake: Lake,
    source: str,
    *,
    now: datetime,
    fetch: Callable[[], Result[T, ProviderError]],
    encode: Callable[[T], dict[str, Any]],
    decode: Callable[[dict[str, Any]], T],
    force: bool = False,
    policy: CachePolicy | None = None,
) -> Result[Refreshed[T], RefreshFailure]:
    """Run the refresh policy for `source` (see the module docstring). Pure in its decisions;
    the only side effects are the lake writes and one stderr line on a stale keep."""
    rule = policy if policy is not None else silver_policy(source)
    previous = lake.read(source)
    if previous is not None and not force:
        age = now - previous.header.fetched_at
        if age < timedelta(seconds=rule.ttl_s):
            return Ok(
                Refreshed(value=decode(previous.payload), header=previous.header, fetched=False)
            )

    match fetch():
        case Ok(value):
            doc = lake.write(source, encode(value), fetched_at=now)
            return Ok(Refreshed(value=value, header=doc.header, fetched=True))
        case Err(error):
            if not transient(error):
                return Err(RefreshFailure(source=source, reason="not_transient", cause=error))
            if previous is None:
                return Err(RefreshFailure(source=source, reason="first_run", cause=error))
            age = now - previous.header.fetched_at
            if age > timedelta(seconds=rule.max_stale_s):
                return Err(RefreshFailure(source=source, reason="too_stale", cause=error, age=age))
            kept = lake.mark_stale(source)
            print(
                f"warning: {source}: source unreachable ({describe(error)}); keeping silver "
                f"fetched {kept.header.fetched_at.isoformat()} "
                f"({age.total_seconds() / 86400.0:.1f} d old) as STALE",
                file=sys.stderr,
            )
            return Ok(Refreshed(value=decode(kept.payload), header=kept.header, fetched=False))
        case _ as unreachable:  # pragma: no cover - exhaustiveness guard
            assert_never(unreachable)
