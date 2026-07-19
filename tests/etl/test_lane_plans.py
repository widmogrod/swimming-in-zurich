"""Belegungsplan scrape stage: best-effort fetch/parse, offline via MockTransport over the
committed City PDF fixture."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.etl.lane_plans import scrape_lane_plans

PDF_FIXTURE = (
    Path(__file__).resolve().parents[1] / "providers" / "fixtures" / "city-schwimmerbecken.pdf"
)
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
