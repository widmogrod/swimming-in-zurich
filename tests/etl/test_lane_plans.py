"""Belegungsplan scrape stage: DISCOVERY-DRIVEN, best-effort fetch/parse. The fetch-set is a
projection of the links `page_provider` discovers on the pool pages (no hardcoded URL list, no
`lane_plan_source` read); each parsed plan is stamped with its source URL and each failure
recorded as a typed miss."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from swimzh.core.errors import HttpStatus
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    LanePlanSource,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.etl.lane_plans import (
    UndiscoveredSource,
    fetch_set,
    scrape_lane_plans,
    undiscovered_authored,
)
from swimzh.providers.page_provider import DiscoveredLink

FIXTURES = Path(__file__).resolve().parents[1] / "providers" / "fixtures"
CITY_BYTES = (FIXTURES / "city-schwimmerbecken.pdf").read_bytes()

CITY_URL = "https://example.test/city-schwimmerbecken.pdf"
LEIMBACH_URL = "https://example.test/leimbach.pdf"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def _link(pool_id: str, url: str) -> DiscoveredLink:
    return DiscoveredLink(pool_id=PoolId(pool_id), url=url)


def test_fetch_set_is_the_projection_of_discovered_links() -> None:
    # The fetch-set IS a projection of the discovered links — nothing hardcoded, nothing from
    # `lane_plan_source`. Distinct URLs, first-seen order, deduped (two pools may advertise the
    # same sheet).
    links = (
        _link("a", CITY_URL),
        _link("b", LEIMBACH_URL),
        _link("c", CITY_URL),
    )
    assert fetch_set(links) == (CITY_URL, LEIMBACH_URL)


def test_scrape_parses_discovered_source_and_stamps_its_url() -> None:
    client = _client(lambda _r: httpx.Response(200, content=CITY_BYTES))
    report = scrape_lane_plans(client, (_link("hallenbad-city", CITY_URL),))
    assert len(report.plans) == 1
    assert report.misses == ()
    parsed = report.plans[0]
    assert "City" in parsed.basin_hint
    assert parsed.plan.lane_count == 6
    # The parser is URL-agnostic; the fetch loop stamped the real source URL as the join key.
    assert parsed.source_url == CITY_URL


def test_scrape_records_failed_fetch_as_a_typed_miss() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("city-schwimmerbecken.pdf"):
            return httpx.Response(200, content=CITY_BYTES)
        return httpx.Response(503, text="down")

    client = _client(handler)
    links = (_link("city", CITY_URL), _link("leimbach", LEIMBACH_URL))
    report = scrape_lane_plans(client, links)
    assert len(report.plans) == 1 and report.plans[0].source_url == CITY_URL
    assert len(report.misses) == 1
    miss = report.misses[0]
    assert miss.source_url == LEIMBACH_URL
    # The real typed cause is preserved (not a status code or a describe() string).
    assert isinstance(miss.cause, HttpStatus)
    assert miss.cause.status == 503


def test_scrape_of_no_discovered_links_is_empty() -> None:
    client = _client(lambda _r: httpx.Response(200, content=CITY_BYTES))
    report = scrape_lane_plans(client, ())
    assert report.plans == () and report.misses == ()


def _facility_with_sources(pool_id: str, *sources: tuple[str, str]) -> Facility:
    """A facility whose basins each declare a `lane_plan_source` at the given (basin_id, url)."""
    return Facility(
        identity=PoolIdentity(facility_id=PoolId(pool_id), name=pool_id, kind=PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="test", curated=True, valid_as_of=date(2026, 1, 1)),
        basins=tuple(
            Basin(
                basin_id=BasinId(bid),
                name=bid,
                rules=(),
                kind=BasinKind.LAP,
                lane_plan_source=LanePlanSource(url=url),
            )
            for bid, url in sources
        ),
    )


def test_undiscovered_authored_flags_a_source_no_page_advertises() -> None:
    # S4 (S2-surfaced): an authored `lane_plan_source.url` NOT among the discovered links is
    # `authored − discovered` — a declared fact discovery can no longer produce.
    facility = _facility_with_sources("hallenbad-city", ("city-50m", CITY_URL))
    discovered = (_link("hallenbad-city", LEIMBACH_URL),)  # advertises a DIFFERENT url
    assert undiscovered_authored([facility], discovered) == (
        UndiscoveredSource(pool_id=PoolId("hallenbad-city"), url=CITY_URL),
    )


def test_undiscovered_authored_empty_when_every_source_is_discovered() -> None:
    facility = _facility_with_sources("hallenbad-city", ("city-50m", CITY_URL))
    discovered = (_link("hallenbad-city", CITY_URL),)
    assert undiscovered_authored([facility], discovered) == ()


def test_undiscovered_authored_dedupes_two_basins_sharing_one_url() -> None:
    # Two basins declaring the SAME undiscovered url yield ONE UndiscoveredSource, not two.
    facility = _facility_with_sources(
        "hallenbad-city", ("city-50m", CITY_URL), ("city-vario", CITY_URL)
    )
    assert undiscovered_authored([facility], ()) == (
        UndiscoveredSource(pool_id=PoolId("hallenbad-city"), url=CITY_URL),
    )


def test_hardcoded_url_list_and_fuzzy_matcher_symbols_are_gone() -> None:
    # Acceptance guard: the hardcoded URL list and the fuzzy basin-hint matcher are DELETED —
    # extraction is now a projection of the DISCOVERED links, reconciliation a URL-keyed join.
    # Asserting on module attributes (not a text grep) so a docstring mention of the retired names
    # cannot trip the guard, and a reintroduction of the symbol itself does. `declared_source_urls`
    # (the old YAML-projection fetch-set) is likewise gone.
    import importlib

    lane_plans = importlib.import_module("swimzh.etl.lane_plans")
    silver = importlib.import_module("swimzh.etl.silver")
    reconcile = importlib.import_module("swimzh.build.reconcile")

    assert not hasattr(lane_plans, "CITY_BELEGUNGSPLAN_URLS")
    assert not hasattr(lane_plans, "PENDING_BELEGUNGSPLAENE")
    assert not hasattr(lane_plans, "declared_source_urls")
    assert not hasattr(silver, "_basin_hint_index")
    assert not hasattr(reconcile, "BasinHint")
    assert not hasattr(reconcile, "build_basin_hint_index")


def test_source_docstrings_do_not_carry_stale_reconciliation_claims() -> None:
    # Doc-reversal guard: the module docstrings must not resurrect the retired framing where
    # `basin_hint` drove reconciliation / the URL->basin binding was "intentionally NOT made".
    # Binding is now a deterministic URL-keyed join in silver — asserted positively too.
    import importlib
    from pathlib import Path

    lane_plans = importlib.import_module("swimzh.etl.lane_plans")
    silver = importlib.import_module("swimzh.etl.silver")

    for module in (lane_plans, silver):
        assert module.__file__ is not None
        text = Path(module.__file__).read_text(encoding="utf-8").casefold()
        assert "basin_hint drives" not in text
        assert "decision #8" not in text
        assert "intentionally not made" not in text
    assert "url-keyed inner join" in (silver.__doc__ or "").casefold()
    assert "binding is not made here" in (lane_plans.__doc__ or "").casefold()
