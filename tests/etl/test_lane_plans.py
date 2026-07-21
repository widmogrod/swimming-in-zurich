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


def test_scrape_lane_plans_newly_listed_basins_all_parse_never_fatal() -> None:
    """Since Slice E2's anchor-derived grid band all three newly-listed basins parse as uniform
    lane grids (the old A4 legend clip had dropped Bläsi's Sunday lane and hidden the sheet).
    None is fatal — a fetch/parse failure would still be counted in `skipped`, never abort."""
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
    assert any("Bläsi" in h for h in hints)
    assert len(report.plans) == 3  # all three parse under E2's per-weekday segmentation
    assert report.skipped == ()


def test_scrape_lane_plans_expands_stacked_oerlikon_sheet_into_two_basins() -> None:
    # The Oerlikon Nichtschwimmer-/Sprungbecken sheet stacks two basins; the sheet parser emits
    # one ParsedPlan per basin, so one URL contributes TWO plans (E3 multi-basin segmentation).
    sheet = (FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf").read_bytes()
    client = _client(lambda _r: httpx.Response(200, content=sheet))
    report = scrape_lane_plans(client, ("https://example.test/oerlikon-sprung.pdf",))
    assert len(report.plans) == 2
    assert report.skipped == ()
    hints = {p.basin_hint for p in report.plans}
    assert any("Nichtschwimmer" in h for h in hints)
    assert any("Sprungbecken" in h for h in hints)


def test_new_slugs_are_wired_into_the_scrape_url_list() -> None:
    listed = "\n".join(CITY_BELEGUNGSPLAN_URLS)
    for slug in NEW_SLUGS:
        assert f"/{slug}.pdf" in listed
