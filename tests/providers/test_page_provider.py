"""The discovery hop: `page_provider` extracts Belegungsplan sub-resource links from a pool page,
stamps each with the owning PoolId, and (the S2 acceptance) DISCOVERS a superset of every URL the
curated YAML hand-authored — so a later slice can retire the authored source with no lane-plan
loss. The extra `city-variobecken.pdf` link the city page carries (never authored) is surfaced,
not dropped."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from swimzh.core.errors import HttpStatus
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.models import PoolId
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.providers.page_provider import (
    DiscoveredLink,
    discover_links,
    discover_pages,
    fetch_page_doc,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Each curated pool that carries a Belegungsplan: its saved page fixture + the real stadt-zuerich
# page URL relative hrefs resolve against. (Aemtler is curated but has no lane plan / no link.)
_POOL_PAGE: dict[str, tuple[str, str]] = {
    "hallenbad-city": (
        "hallenbad_city.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/city.html",
    ),
    "hallenbad-oerlikon": (
        "hallenbad_oerlikon.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/oerlikon.html",
    ),
    "hallenbad-bungertwies": (
        "hallenbad_bungertwies.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/bungertwies.html",
    ),
    "hallenbad-blaesi": (
        "hallenbad_blaesi.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/blaesi.html",
    ),
    "hallenbad-leimbach": (
        "hallenbad_leimbach.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/leimbach.html",
    ),
    "waermebad-kaeferberg": (
        "waermebad_kaeferberg.html",
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/kaeferberg.html",
    ),
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="page_provider", retry=RetryPolicy(max_attempts=1))


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def _discover_for(pool_id: str) -> tuple[DiscoveredLink, ...]:
    fixture, page_url = _POOL_PAGE[pool_id]
    return discover_links(_fixture(fixture), PoolId(pool_id), page_url)


# --- unit: link extraction ----------------------------------------------------------


def test_discover_resolves_relative_href_and_stamps_pool_id() -> None:
    page = (
        '<a href="/content/dam/web/de/stadtleben/sport-und-erholung/dokumente/'
        'badeanlagen/belegungsplaene/city-schwimmerbecken.pdf">plan</a>'
    )
    links = discover_links(page, PoolId("hallenbad-city"), "https://www.stadt-zuerich.ch/x.html")
    assert links == (
        DiscoveredLink(
            pool_id=PoolId("hallenbad-city"),
            url="https://www.stadt-zuerich.ch/content/dam/web/de/stadtleben/sport-und-erholung/"
            "dokumente/badeanlagen/belegungsplaene/city-schwimmerbecken.pdf",
        ),
    )


def test_discover_ignores_non_belegungsplan_pdfs_and_dedupes() -> None:
    page = (
        '<a href="/dokumente/badeanlagen/belegungsplaene/city-schwimmerbecken.pdf">a</a>'
        '<a href="/dokumente/badeanlagen/belegungsplaene/city-schwimmerbecken.pdf">dup</a>'
        '<a href="/dokumente/other/preisliste.pdf">price</a>'
        '<a href="/de/some/page.html">page</a>'
    )
    links = discover_links(page, PoolId("p"), "https://host/pool.html")
    # Only the Belegungsplan PDF, once (deduped); the price PDF and the HTML page are not lane
    # sub-resources.
    assert [link.url for link in links] == [
        "https://host/dokumente/badeanlagen/belegungsplaene/city-schwimmerbecken.pdf"
    ]


def test_discover_on_page_without_a_plan_yields_nothing() -> None:
    # Absence is not failure: the Aemtler schulschwimmanlage page carries no Belegungsplan link.
    links = discover_links(
        _fixture("schulschwimmanlage_aemtler.html"),
        PoolId("schulschwimmanlage-aemtler"),
        "https://www.stadt-zuerich.ch/x.html",
    )
    assert links == ()


# --- unit: fetch seam ---------------------------------------------------------------


def test_fetch_page_doc_discovers_from_a_fetched_page() -> None:
    page = _fixture("hallenbad_city.html")
    client = _client(lambda _r: httpx.Response(200, text=page))
    result = fetch_page_doc(client, PoolId("hallenbad-city"), _POOL_PAGE["hallenbad-city"][1])
    assert isinstance(result, Ok)
    urls = {link.url for link in result.value.discovered_links}
    assert any(u.endswith("city-schwimmerbecken.pdf") for u in urls)
    assert all(link.pool_id == PoolId("hallenbad-city") for link in result.value.discovered_links)


def test_fetch_page_doc_returns_typed_error_on_bad_status() -> None:
    client = _client(lambda _r: httpx.Response(503, text="down"))
    result = fetch_page_doc(client, PoolId("p"), "https://host/pool.html")
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)


def test_discover_pages_aggregates_links_and_records_page_misses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("city.html"):
            return httpx.Response(200, text=_fixture("hallenbad_city.html"))
        return httpx.Response(503, text="down")

    client = _client(handler)
    pages = [
        (PoolId("hallenbad-city"), _POOL_PAGE["hallenbad-city"][1]),
        (PoolId("hallenbad-blaesi"), _POOL_PAGE["hallenbad-blaesi"][1]),
    ]
    report = discover_pages(client, pages)
    assert any(link.url.endswith("city-schwimmerbecken.pdf") for link in report.links)
    assert all(link.pool_id == PoolId("hallenbad-city") for link in report.links)
    assert len(report.page_misses) == 1
    miss = report.page_misses[0]
    assert miss.pool_id == PoolId("hallenbad-blaesi")
    assert isinstance(miss.cause, HttpStatus)


# --- acceptance: discovered is a SUPERSET of every authored (basin, url) --------------


def _authored(dataset: Dataset) -> dict[str, set[tuple[str, str]]]:
    """pool_id -> {(basin_id, url)} for every basin that hand-authored a `lane_plan_source`."""
    out: dict[str, set[tuple[str, str]]] = {}
    for facility in dataset.facilities:
        pool_id = str(facility.identity.facility_id)
        for basin in facility.basins:
            if basin.lane_plan_source is not None:
                out.setdefault(pool_id, set()).add(
                    (str(basin.basin_id), basin.lane_plan_source.url)
                )
    return out


def test_every_authored_lane_url_is_discovered(dataset: Dataset) -> None:
    # S2 acceptance: for every pool, discovery is a SUPERSET of the URLs the curated YAML
    # hand-authored — each authored `(basin, url)`'s URL appears among that pool's discovered
    # links. (Not strict equality: discovery may find MORE, asserted below.)
    authored = _authored(dataset)
    # Every pool that authored a lane plan must have a page fixture to discover from.
    assert set(authored) <= set(_POOL_PAGE), set(authored) - set(_POOL_PAGE)
    for pool_id, basin_urls in authored.items():
        discovered = {link.url for link in _discover_for(pool_id)}
        authored_urls = {url for _basin, url in basin_urls}
        assert authored_urls <= discovered, (pool_id, authored_urls - discovered)


def test_discovery_is_a_strict_superset_surfacing_the_variobecken_extra(
    dataset: Dataset,
) -> None:
    # The city page advertises `city-variobecken.pdf`, which NO basin ever authored. It is
    # SURFACED as a discovered link (not dropped, not a failure) — the discovered set is a strict
    # superset of the authored set. A later slice decides what to do with the extra; discovery's
    # job is only to not lose it.
    authored_city = {url for _basin, url in _authored(dataset)["hallenbad-city"]}
    discovered_city = {link.url for link in _discover_for("hallenbad-city")}
    extras = discovered_city - authored_city
    assert any(url.endswith("city-variobecken.pdf") for url in extras), extras
    # And the authored city URL is still discovered (the superset holds).
    assert authored_city <= discovered_city
