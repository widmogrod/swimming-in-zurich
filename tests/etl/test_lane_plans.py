"""Belegungsplan scrape stage: DOMAIN-DRIVEN, best-effort fetch/parse. The fetch-set is derived
from the loaded facilities' `lane_plan_source` declarations (no hardcoded URL list); each parsed
plan is stamped with its source URL and each failure recorded as a typed miss."""

from __future__ import annotations

from collections.abc import Callable
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
from swimzh.etl.lane_plans import declared_source_urls, scrape_lane_plans

FIXTURES = Path(__file__).resolve().parents[1] / "providers" / "fixtures"
CITY_BYTES = (FIXTURES / "city-schwimmerbecken.pdf").read_bytes()

CITY_URL = "https://example.test/city-schwimmerbecken.pdf"
LEIMBACH_URL = "https://example.test/leimbach.pdf"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def _facility(pool_id: str, basins: tuple[Basin, ...]) -> Facility:
    return Facility(
        identity=PoolIdentity(facility_id=PoolId(pool_id), name=pool_id, kind=PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="test", curated=True),
        basins=basins,
    )


def _basin(basin_id: str, url: str | None) -> Basin:
    source = LanePlanSource(url=url) if url is not None else None
    return Basin(
        basin_id=BasinId(basin_id),
        name=basin_id,
        rules=(),
        kind=BasinKind.LAP,
        lane_plan_source=source,
    )


def test_declared_source_urls_derives_the_fetch_set_from_the_domain() -> None:
    # The fetch-set IS a projection of the model — nothing hardcoded. Distinct URLs, first-seen
    # order, deduped; a basin without a source contributes nothing.
    facilities = (
        _facility("a", (_basin("a-1", CITY_URL), _basin("a-2", None))),
        _facility("b", (_basin("b-1", LEIMBACH_URL), _basin("b-2", CITY_URL))),
    )
    assert declared_source_urls(facilities) == (CITY_URL, LEIMBACH_URL)


def test_scrape_parses_declared_source_and_stamps_its_url() -> None:
    client = _client(lambda _r: httpx.Response(200, content=CITY_BYTES))
    facilities = (_facility("city", (_basin("city-50m", CITY_URL),)),)
    report = scrape_lane_plans(client, facilities)
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
    facilities = (
        _facility("city", (_basin("city-50m", CITY_URL),)),
        _facility("leimbach", (_basin("leimbach-25m", LEIMBACH_URL),)),
    )
    report = scrape_lane_plans(client, facilities)
    assert len(report.plans) == 1 and report.plans[0].source_url == CITY_URL
    assert len(report.misses) == 1
    miss = report.misses[0]
    assert miss.source_url == LEIMBACH_URL
    # The real typed cause is preserved (not a status code or a describe() string).
    assert isinstance(miss.cause, HttpStatus)
    assert miss.cause.status == 503


def test_scrape_of_no_declared_sources_is_empty() -> None:
    client = _client(lambda _r: httpx.Response(200, content=CITY_BYTES))
    facilities = (_facility("x", (_basin("x-1", None),)),)
    report = scrape_lane_plans(client, facilities)
    assert report.plans == () and report.misses == ()


def test_hardcoded_url_list_and_fuzzy_matcher_symbols_are_gone() -> None:
    # Acceptance guard: the hardcoded URL list and the fuzzy basin-hint matcher are DELETED —
    # extraction is now a projection of the domain, reconciliation a URL-keyed join. Asserting on
    # module attributes (not a text grep) so a docstring mention of the retired names cannot trip
    # the guard, and a reintroduction of the symbol itself does.
    import importlib

    lane_plans = importlib.import_module("swimzh.etl.lane_plans")
    silver = importlib.import_module("swimzh.etl.silver")
    reconcile = importlib.import_module("swimzh.build.reconcile")

    assert not hasattr(lane_plans, "CITY_BELEGUNGSPLAN_URLS")
    assert not hasattr(lane_plans, "PENDING_BELEGUNGSPLAENE")
    assert not hasattr(silver, "_basin_hint_index")
    assert not hasattr(reconcile, "BasinHint")
    assert not hasattr(reconcile, "build_basin_hint_index")


def test_source_docstrings_do_not_carry_stale_reconciliation_claims() -> None:
    # S3 doc-reversal guard: the module docstrings must not resurrect the retired framing where
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
