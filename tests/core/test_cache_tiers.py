"""Tests for the per-source cache policy table and its stamping in `HttpClient.get`.

The table is the whole policy, so it is asserted **entry by entry** — a silent TTL edit
is a change in how stale the pipeline is allowed to be, and it should have to change a
test that spells out the number. The stamping side is driven through a real
`httpx.MockTransport` that records the extensions each request actually carried, so the
tests observe what the transport would see rather than an internal helper's return value.
"""

from __future__ import annotations

import httpx
import pytest

from swimzh.core.cache_tiers import (
    CACHE_POLICIES,
    DEFAULT_POLICY,
    CachePolicy,
    cache_extensions,
    policy_for,
)
from swimzh.core.http import HttpClient
from swimzh.core.httpcache import (
    DEFAULT_TIER,
    DEFAULT_TTL_S,
    TIER_EXTENSION,
    TTL_EXTENSION,
    request_tier,
    request_ttl_s,
)
from swimzh.core.result import Ok

URL = "https://www.stadt-zuerich.ch/hallenbad-city"

HOUR = 3600
DAY = 24 * HOUR


class Recorder:
    """Records every request httpx actually handed to the transport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, text="ok")

    @property
    def only(self) -> httpx.Request:
        assert len(self.requests) == 1, f"expected one request, got {len(self.requests)}"
        return self.requests[0]


def _client(source: str) -> tuple[HttpClient, Recorder]:
    recorder = Recorder()
    return HttpClient(httpx.Client(transport=recorder.transport()), source=source), recorder


# --- the table itself -------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("geo_sport", CachePolicy("static", 14 * DAY)),
        ("page_provider", CachePolicy("static", 7 * DAY)),
        ("price_scraper", CachePolicy("static", 7 * DAY)),
        ("belegungsplan", CachePolicy("snapshot", 3 * DAY)),
        ("schedule_scraper", CachePolicy("snapshot", 12 * HOUR)),
        ("baditicker", CachePolicy("live", 2 * 60)),
    ],
)
def test_policy_table_is_exactly_this(source: str, expected: CachePolicy) -> None:
    assert policy_for(source) == expected


def test_table_holds_no_sources_beyond_the_asserted_six() -> None:
    assert set(CACHE_POLICIES) == {
        "geo_sport",
        "page_provider",
        "price_scraper",
        "belegungsplan",
        "schedule_scraper",
        "baditicker",
    }


def test_unknown_source_falls_back_to_the_documented_default() -> None:
    assert policy_for("no-such-provider") == DEFAULT_POLICY
    assert CachePolicy(DEFAULT_TIER, DEFAULT_TTL_S) == DEFAULT_POLICY


def test_cache_extensions_stamps_both_keys_together() -> None:
    # `put` takes the tier explicitly while `fresh` re-derives it: one key without the
    # other would write and read under different assumptions.
    assert cache_extensions("baditicker") == {TIER_EXTENSION: "live", TTL_EXTENSION: 120}


# --- the stamping in HttpClient.get -----------------------------------------------


@pytest.mark.parametrize(
    ("source", "tier", "ttl_s"),
    [
        ("geo_sport", "static", 14 * DAY),
        ("page_provider", "static", 7 * DAY),
        ("price_scraper", "static", 7 * DAY),
        ("belegungsplan", "snapshot", 3 * DAY),
        ("schedule_scraper", "snapshot", 12 * HOUR),
        ("baditicker", "live", 120),
    ],
)
def test_get_stamps_the_sources_policy_on_the_request(source: str, tier: str, ttl_s: int) -> None:
    client, recorder = _client(source)

    assert isinstance(client.get(URL), Ok)

    # Read them the way the transport does, not by dict lookup.
    assert request_tier(recorder.only) == tier
    assert request_ttl_s(recorder.only) == ttl_s


def test_get_from_an_unknown_source_stamps_the_default_policy() -> None:
    client, recorder = _client("mystery")

    assert isinstance(client.get(URL), Ok)

    # Presence first, and deliberately: the readers return the same defaults for an
    # *unstamped* request, so reading values alone cannot tell "stamped with the default"
    # from "never stamped at all" — this test would survive deleting the stamp entirely.
    assert TIER_EXTENSION in recorder.only.extensions
    assert TTL_EXTENSION in recorder.only.extensions
    assert request_tier(recorder.only) == DEFAULT_TIER
    assert request_ttl_s(recorder.only) == DEFAULT_TTL_S


def test_stamp_merges_with_a_caller_supplied_extensions() -> None:
    client, recorder = _client("geo_sport")

    assert isinstance(client.get(URL, extensions={"trace": "abc"}), Ok)

    assert recorder.only.extensions["trace"] == "abc"
    assert request_tier(recorder.only) == "static"
    assert request_ttl_s(recorder.only) == 14 * DAY


def test_a_caller_supplied_tier_wins_over_the_table() -> None:
    client, recorder = _client("geo_sport")

    overrides = {TIER_EXTENSION: "live", TTL_EXTENSION: 60}
    assert isinstance(client.get(URL, extensions=overrides), Ok)

    assert request_tier(recorder.only) == "live"
    assert request_ttl_s(recorder.only) == 60


def test_a_non_mapping_extensions_is_passed_through_untouched() -> None:
    client, _recorder = _client("geo_sport")

    # httpx rejects it — the point is that the stamp neither swallows nor rewrites it.
    with pytest.raises(TypeError):
        client.get(URL, extensions="not-a-mapping")


def test_the_caller_kwargs_mapping_is_not_mutated() -> None:
    client, _recorder = _client("geo_sport")
    caller_extensions: dict[str, object] = {"trace": "abc"}

    assert isinstance(client.get(URL, extensions=caller_extensions), Ok)

    assert caller_extensions == {"trace": "abc"}


def test_the_stamp_survives_a_retry() -> None:
    # Retries re-issue the request; each attempt must carry the policy, or a retried
    # fetch would silently land in the default tier.
    attempts: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(429, text="slow down")

    client = HttpClient(
        httpx.Client(transport=httpx.MockTransport(handle)), source="schedule_scraper"
    )

    client.get(URL)

    assert len(attempts) > 1
    assert all(request_tier(r) == "snapshot" for r in attempts)
    assert all(request_ttl_s(r) == 12 * HOUR for r in attempts)


# --- providers stay unaware of the cache ------------------------------------------


def test_no_provider_module_mentions_the_cache() -> None:
    """The seam's whole point: providers are byte-unchanged by this plan.

    Only `HttpClient` (via the table) and `DiskCacheTransport` may know the cache exists;
    a provider reaching for a tier, a TTL or request extensions would move policy out of
    the one table that owns it.
    """
    from pathlib import Path

    import swimzh.providers

    forbidden = ("cache_tier", "cache_ttl_s", "cache_tiers", "httpcache", "extensions")
    providers_dir = Path(swimzh.providers.__file__).parent

    offenders = {
        module.name: term
        for module in sorted(providers_dir.glob("*.py"))
        for term in forbidden
        if term in module.read_text(encoding="utf-8")
    }
    assert offenders == {}
