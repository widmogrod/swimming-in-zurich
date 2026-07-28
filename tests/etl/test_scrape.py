"""scrape_indoor_facilities emits identity-free ``(SourceRef, ScrapedAspects)`` extracts
(indoor only), tagging each with a ``Name`` ref — never a canonical id. S4 fail-fast: a page it
cannot fetch/parse is NOT skipped — its typed ``ProviderError`` is preserved in
``ScrapeReport.failures`` so ``scrape-gold`` aborts the whole run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from swimzh.build.reconcile import Name
from swimzh.core.errors import ConnectionFailed, ParseError
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.domain.access import WomenOnly
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.etl.scrape import scrape_indoor_facilities

FIXTURE = Path(__file__).resolve().parents[1] / "providers" / "fixtures" / "hallenbad_city.html"
FETCHED = datetime(2026, 7, 19, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))


def _entry(pool_id: str, name: str, kind: PoolKind, url: str | None) -> PoolCatalogEntry:
    return PoolCatalogEntry(
        pool_id=pool_id,
        name=name,
        kind=kind,
        address="",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url=url,
        description=None,
        phone=None,
    )


def test_builds_indoor_extracts_with_real_rules() -> None:
    body = FIXTURE.read_bytes()
    catalog = (
        _entry("hallenbad-city", "Hallenbad City", PoolKind.INDOOR, "https://x/city.html"),
        _entry("strandbad-x", "Strandbad X", PoolKind.LAKE, "https://x/lake.html"),  # not indoor
    )
    report = scrape_indoor_facilities(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED
    )

    assert len(report.extracts) == 1  # only the indoor pool
    ref, aspects = report.extracts[0]
    # The provider emits a Name SourceRef (the WFS display name) — never a canonical id.
    assert ref == Name("Hallenbad City")
    assert aspects.name == "Hallenbad City"
    rules = aspects.basins[0].rules
    assert any(isinstance(r.access, WomenOnly) for r in rules)


def test_extracts_carry_notices_closures_and_prices() -> None:
    body = FIXTURE.read_bytes()  # City page: has a Revision closure notice
    # A stadt-zuerich.ch URL so the shared price table is applied.
    catalog = (
        _entry(
            "hallenbad-city",
            "Hallenbad City",
            PoolKind.INDOOR,
            "https://www.stadt-zuerich.ch/.../city.html",
        ),
    )
    prices = PriceTable(
        entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Erwachsene Fr. 8.00"),),
        valid_as_of=FETCHED.date(),
        source_url="https://example.test/prices",
    )
    report = scrape_indoor_facilities(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, prices=prices
    )
    _ref, aspects = report.extracts[0]
    assert aspects.notices and "Revision" in aspects.notices[0].text
    assert aspects.closures  # derived from the closure notice
    assert aspects.prices is not None  # stadt-zuerich host → shared tariff applied


def test_unparseable_page_is_a_typed_failure_not_a_skip() -> None:
    # S4: an unparseable declared source is NOT silently skipped — it is recorded as a typed
    # `ScrapeFailure` carrying the real `ProviderError` (here a ParseError, since the page fetched
    # 200 but has no timetable), so `scrape-gold` can abort the whole run and surface the cause.
    catalog = (_entry("hallenbad-x", "Hallenbad X", PoolKind.INDOOR, "https://x/x.html"),)
    client = _client(lambda _r: httpx.Response(200, content=b"<html>no table</html>"))
    report = scrape_indoor_facilities(client, catalog, FETCHED)
    assert report.extracts == ()
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.name == "Hallenbad X"
    assert failure.url == "https://x/x.html"
    assert isinstance(failure.cause, ParseError)


def test_unreachable_page_failure_preserves_the_transport_cause() -> None:
    # A transport failure (connection error) is likewise preserved as a typed cause, not swallowed.
    catalog = (_entry("hallenbad-x", "Hallenbad X", PoolKind.INDOOR, "https://x/x.html"),)

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    report = scrape_indoor_facilities(_client(boom), catalog, FETCHED)
    assert report.extracts == ()
    assert len(report.failures) == 1
    assert isinstance(report.failures[0].cause, ConnectionFailed)
