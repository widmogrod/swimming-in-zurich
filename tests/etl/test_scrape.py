"""scrape_indoor_facilities emits identity-free ``(SourceRef, ScrapedAspects)`` extracts
(indoor only), tagging each with a ``Name`` ref — never a canonical id. S4 fail-fast: a page it
cannot fetch/parse is NOT skipped — its typed ``ProviderError`` is preserved in
``ScrapeReport.failures`` so ``scrape-gold`` aborts the whole run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
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
from swimzh.storage import catalog_json

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


# --- private-operator closures (bad-altstetten.ch) ------------------------------------

FIXTURE_ALTSTETTEN = (
    Path(__file__).resolve().parents[1] / "providers" / "fixtures" / "hallenbad_altstetten.html"
)


def test_operator_page_closure_is_attached_to_the_pool() -> None:
    # The regression: altstetten's page is a private operator's (WordPress), so it carries no
    # `stzh-disturber` markup and `parse_notices` finds nothing — the pool shipped with
    # `closures: []` while its operator announced an 18-day Revision. The per-pool dispatch
    # extracts it from the prose instead.
    catalog = (
        _entry(
            "hallenbad-altstetten",
            "Hallenbad Altstetten",
            PoolKind.INDOOR,
            "https://www.bad-altstetten.ch",
        ),
    )
    body = FIXTURE_ALTSTETTEN.read_bytes()

    report = scrape_indoor_facilities(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED
    )

    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    covering = [c for c in aspects.closures if c.contains(date(2026, 8, 2))]
    assert len(covering) == 1, aspects.closures
    assert covering[0].start == date(2026, 7, 30)
    assert covering[0].end == date(2026, 8, 16)


def test_operator_closures_are_keyed_by_pool_id_not_by_page_content() -> None:
    # The dispatch must be pool-keyed: the SAME bytes served for a different pool contribute no
    # closure. A content-sniffing fallback would fire on any page that merely mentions a date
    # range near "Revision", which is exactly the wrong-answer mode this seam exists to avoid.
    catalog = (
        _entry("hallenbad-other", "Hallenbad Other", PoolKind.INDOOR, "https://x/other.html"),
    )
    body = FIXTURE_ALTSTETTEN.read_bytes()

    report = scrape_indoor_facilities(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED
    )

    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    assert aspects.closures == ()


# --- which roster entries are DECLARED SOURCES (pinned before S2 widens the gate) --------
#
# The gate `scrape_indoor_facilities` applies today is `kind is INDOOR and url`. S2 widens it
# to a CONJUNCTION: `kind in {INDOOR, THERMAL, SCHOOL}` AND the url is not shared with another
# roster entry. This asserts what that predicate selects on the committed WFS snapshot, so the
# blast radius is a number in a test rather than a surprise in a network build.

_CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalog.json"
_SCRAPEABLE_KINDS = (PoolKind.INDOOR, PoolKind.THERMAL, PoolKind.SCHOOL)


def _declared_sources(entries: tuple[PoolCatalogEntry, ...]) -> set[str]:
    shared = {e.url for e in entries if e.url and sum(1 for o in entries if o.url == e.url) > 1}
    return {
        e.pool_id for e in entries if e.kind in _SCRAPEABLE_KINDS and e.url and e.url not in shared
    }


def test_the_declared_sources_are_exactly_eleven_pools() -> None:
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    declared = _declared_sources(entries)
    # 7 already scraped + the 4 school pools with their own page.
    assert len(declared) == 11, sorted(declared)
    assert {p for p in declared if p.startswith("schulschwimmanlage-")} == {
        "schulschwimmanlage-aemtler",
        "schulschwimmanlage-altweg",
        "schulschwimmanlage-riedtli",
        "schulschwimmanlage-tannenrauch",
    }


def test_the_unshared_url_test_alone_would_select_far_more_than_eleven() -> None:
    """Why the kind gate stays in the conjunction: dropping it selects outdoor/lake/river
    pages that no parser here understands, and under fail-fast each one aborts the build."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    shared = {e.url for e in entries if e.url and sum(1 for o in entries if o.url == e.url) > 1}
    unshared = {e.pool_id for e in entries if e.url and e.url not in shared}
    assert len(unshared) > 11


def test_the_school_pools_without_public_swimming_share_one_overview_url() -> None:
    """The thirteen "ohne öffentliches Schwimmen" (plus borrweg) all carry the generic
    hallenbaeder.html, so the unshared-url test excludes them and they can never become
    build-aborting failures."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    overview = "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder.html"
    sharing = [e.pool_id for e in entries if e.url == overview]
    assert len(sharing) == 14
    assert "schulschwimmanlage-borrweg" in sharing
    assert not _declared_sources(entries) & set(sharing)
