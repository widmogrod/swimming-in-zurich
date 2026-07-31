"""The whole per-source HTTP cache policy, in one table.

Each provider is fetched at the cadence its *source* actually changes, not at some
global rate. That volatility is a property of the site behind the provider, so the policy
is keyed off `HttpClient.source` — the one place that already names which source a
request belongs to — and is stamped onto every request as httpx extensions. Providers
therefore stay byte-unchanged: they never mention the cache at all.

Three volatility tiers, which also name the on-disk directory (`<root>/<tier>/…`):

* **static** — geo/roster/tariff facts that move a few times a year.
* **snapshot** — timetables and lane plans, re-cut per season or per week.
* **live** — the Baditicker feed, which is the point only if it is minutes old.

The tier is part of the cache *path*, so two sources in different tiers that fetch the
same URL keep independent entries (deliberate: each expires on its own clock).

An unrecognised source is not an error — it gets `DEFAULT_TIER` / `DEFAULT_TTL_S` (one
hour), the same conservative fallback the transport applies to an unstamped request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from swimzh.core.httpcache import (
    DEFAULT_TIER,
    DEFAULT_TTL_S,
    TIER_EXTENSION,
    TTL_EXTENSION,
)

_HOUR_S: Final = 3600
_DAY_S: Final = 24 * _HOUR_S
_MINUTE_S: Final = 60

#: Tier names. They are directory names on disk, so they are part of the layout contract.
STATIC: Final = "static"
SNAPSHOT: Final = "snapshot"
LIVE: Final = "live"

#: The closed set of tiers. A typo'd tier is a **mypy error**, not a new cache directory
#: that writes land in and reads never visit ("the caller owns tier consistency", S1).
#: A `Literal` rather than a `StrEnum` (which `CacheMode` next door is) because the
#: fourth member is `httpcache.DEFAULT_TIER` — a plain `Final = "default"`, which mypy
#: already types as `Literal["default"]`, so it composes here with nothing re-declared.
#: An enum would have had to introduce a member duplicating that constant's value, and
#: the tier is a *path segment and a JSON field* — it wants to stay an ordinary `str` at
#: runtime, which keeps `request_tier`'s `str` contract and S1/S2's tests untouched.
CacheTier = Literal["static", "snapshot", "live", "default"]


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """How long one source's responses stay usable, and which tier holds them."""

    tier: CacheTier
    ttl_s: int


#: The fallback for a source with no entry in the table (and for an unstamped request).
DEFAULT_POLICY: Final = CachePolicy(tier=DEFAULT_TIER, ttl_s=DEFAULT_TTL_S)

#: The per-source policy table — the single place these TTLs are decided.
CACHE_POLICIES: Final[dict[str, CachePolicy]] = {
    # static: the WFS roster, the discovered page set, the tariff page.
    "geo_sport": CachePolicy(STATIC, 14 * _DAY_S),
    "page_provider": CachePolicy(STATIC, 7 * _DAY_S),
    "price_scraper": CachePolicy(STATIC, 7 * _DAY_S),
    # snapshot: lane plans (Belegungsplan PDFs) and the scraped timetables.
    "belegungsplan": CachePolicy(SNAPSHOT, 3 * _DAY_S),
    "schedule_scraper": CachePolicy(SNAPSHOT, 12 * _HOUR_S),
    # live: water temperatures / open-closed, worth having only while fresh.
    "baditicker": CachePolicy(LIVE, 2 * _MINUTE_S),
}


def policy_for(source: str) -> CachePolicy:
    """The policy for `source`, or `DEFAULT_POLICY` when the source is unknown."""
    return CACHE_POLICIES.get(source, DEFAULT_POLICY)


def cache_extensions(source: str) -> dict[str, object]:
    """The httpx request extensions that stamp `source`'s policy onto a request.

    Both keys are stamped **together**: `CacheStore.put` takes the tier explicitly while
    `CacheStore.fresh` re-derives it from the request, so a request carrying only one of
    the two would be written and read under different assumptions.
    """
    policy = policy_for(source)
    return {TIER_EXTENSION: policy.tier, TTL_EXTENSION: policy.ttl_s}
