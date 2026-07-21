"""Belegungsplan scrape stage: best-effort fetch/parse, offline via MockTransport over the
committed City PDF fixture."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.etl.lane_plans import CITY_BELEGUNGSPLAN_URLS, scrape_lane_plans

NEW_SLUGS = ("leimbach", "blaesi", "kaeferberg")

FIXTURES = Path(__file__).resolve().parents[1] / "providers" / "fixtures"
PDF_FIXTURE = FIXTURES / "city-schwimmerbecken.pdf"
CITY_BYTES = PDF_FIXTURE.read_bytes()


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def test_scrape_lane_plans_parses_fixture() -> None:
    client = _client(lambda _r: httpx.Response(200, content=CITY_BYTES))
    report = scrape_lane_plans(client, ("https://example.test/city.pdf",))
    assert len(report.plans) == 1
    assert report.skipped == ()
    parsed = report.plans[0]
    assert "City" in parsed.basin_hint
    assert parsed.plan.lane_count == 6


def test_scrape_lane_plans_skips_failed_pdf_best_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("good.pdf"):
            return httpx.Response(200, content=CITY_BYTES)
        return httpx.Response(503, text="down")

    client = _client(handler)
    report = scrape_lane_plans(
        client, ("https://example.test/good.pdf", "https://example.test/bad.pdf")
    )
    assert len(report.plans) == 1
    assert report.skipped == ("https://example.test/bad.pdf",)


def test_scrape_lane_plans_newly_listed_basins_partial_parse_never_fatal() -> None:
    """Of the three newly-listed basins, Leimbach and Käferberg parse under E1's page-relative
    geometry (Käferberg is a clean 4×7 A3 grid the old A4-pixel clip had hidden); only the
    genuinely ragged Bläsi sheet is a typed skip — never fatal, counted in `skipped`."""
    by_slug = {slug: (FIXTURES / f"{slug}.pdf").read_bytes() for slug in NEW_SLUGS}

    def handler(request: httpx.Request) -> httpx.Response:
        slug = request.url.path.rsplit("/", 1)[-1].removesuffix(".pdf")
        return httpx.Response(200, content=by_slug[slug])

    client = _client(handler)
    urls = tuple(f"https://example.test/{slug}.pdf" for slug in NEW_SLUGS)
    report = scrape_lane_plans(client, urls)

    hints = {p.basin_hint for p in report.plans}
    assert any("Leimbach" in h for h in hints)
    assert any("Käferberg" in h for h in hints)
    assert len(report.plans) == 2  # Leimbach + Käferberg parse under E1's page-relative band
    assert report.skipped == ("https://example.test/blaesi.pdf",)


def test_new_slugs_are_wired_into_the_scrape_url_list() -> None:
    listed = "\n".join(CITY_BELEGUNGSPLAN_URLS)
    for slug in NEW_SLUGS:
        assert f"/{slug}.pdf" in listed
