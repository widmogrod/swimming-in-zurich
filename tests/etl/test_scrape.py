"""scrape_declared_sources emits identity-free ``(SourceRef, ScrapedAspects)`` extracts for the
pools that own their page, tagging each with a ``Name`` ref — never a canonical id.
S4 fail-fast: a page it cannot fetch/parse is NOT skipped — its typed ``ProviderError`` is
preserved in ``ScrapeReport.failures`` so ``scrape-gold`` aborts the whole run."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from swimzh.build.reconcile import Name
from swimzh.core.errors import ConnectionFailed, ParseError
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.domain.access import WomenOnly
from swimzh.domain.admission import Free, Tariff, Unknown
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.schedule import DatePrecision, TimeRange, Weather, Weekday
from swimzh.etl.scrape import (
    admission_for,
    declared_sources,
    scrape_declared_sources,
    scrape_shared_sources,
    shared_sources,
)
from swimzh.providers.price_scraper import (
    PRICES_URL,
    CityTariffs,
    states_city_tariff,
    states_free_admission,
)
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


def _table(adult: str, youth: str, child: str) -> PriceTable:
    return PriceTable(
        entries=(
            PriceEntry(PriceCategory.ADULT, Decimal(adult), f"Erwachsene Fr. {adult}", 20),
            PriceEntry(PriceCategory.YOUTH, Decimal(youth), f"Jugendliche Fr. {youth}", 16),
            PriceEntry(PriceCategory.CHILD, Decimal(child), f"Kinder Fr. {child}", 6),
        ),
        valid_as_of=FETCHED.date(),
        source_url="https://example.test/prices",
    )


#: What the city actually prints: the general rate, and the separate Schulschwimmanlage one.
_TARIFFS = CityTariffs(
    general=_table("8.00", "6.00", "4.00"), school=_table("5.00", "5.00", "2.50")
)


def test_builds_indoor_extracts_with_real_rules() -> None:
    body = FIXTURE.read_bytes()
    catalog = (
        _entry("hallenbad-city", "Hallenbad City", PoolKind.INDOOR, "https://x/city.html"),
        # A `PADDLING` pool: 13 of them share one month-granular overview page, so the kind is
        # still outside the gate even after outdoor/lake/river joined it.
        _entry("planschbecken-x", "Planschbecken X", PoolKind.PADDLING, "https://x/paddling.html"),
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
    )

    assert len(report.extracts) == 1  # only the scrapeable-kind pool
    ref, aspects = report.extracts[0]
    # The provider emits a Name SourceRef (the WFS display name) — never a canonical id.
    assert ref == Name("Hallenbad City")
    assert aspects.name == "Hallenbad City"
    rules = aspects.basins[0].rules
    # The one row the City page publishes as POOL hours: "Montag–Sonntag | 6–22 Uhr". Its
    # women-only slots sit in the table headed "Öffnungszeiten Sauna" and are not pool hours.
    assert [(sorted(d.name for d in r.weekdays), r.time) for r in rules] == [
        (sorted(d.name for d in Weekday), TimeRange(time(6), time(22)))
    ]
    assert not any(isinstance(r.access, WomenOnly) for r in rules)


def test_extracts_carry_notices_closures_and_prices() -> None:
    body = FIXTURE.read_bytes()  # City page: has a Revision closure notice, and links the tariff
    catalog = (
        _entry(
            "hallenbad-city",
            "Hallenbad City",
            PoolKind.INDOOR,
            "https://www.stadt-zuerich.ch/.../city.html",
        ),
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
    )
    _ref, aspects = report.extracts[0]
    assert aspects.notices and "Revision" in aspects.notices[0].text
    assert aspects.closures  # derived from the closure notice
    # Its page links the tariff → the shared tariff applied, as the `Tariff` arm of the union.
    assert isinstance(aspects.admission, Tariff)


def test_unparseable_page_is_a_typed_failure_not_a_skip() -> None:
    # S4: an unparseable declared source is NOT silently skipped — it is recorded as a typed
    # `ScrapeFailure` carrying the real `ProviderError` (here a ParseError, since the page fetched
    # 200 but has no timetable), so `scrape-gold` can abort the whole run and surface the cause.
    catalog = (_entry("hallenbad-x", "Hallenbad X", PoolKind.INDOOR, "https://x/x.html"),)
    client = _client(lambda _r: httpx.Response(200, content=b"<html>no table</html>"))
    report = scrape_declared_sources(client, catalog, FETCHED, tariffs=_TARIFFS)
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

    report = scrape_declared_sources(_client(boom), catalog, FETCHED, tariffs=_TARIFFS)
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

    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
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

    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
    )

    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    assert aspects.closures == ()


# --- which roster entries are DECLARED SOURCES ------------------------------------------
#
# `scrape_declared_sources` gates on `etl.scrape.declared_sources`, a CONJUNCTION:
# `kind in {INDOOR, THERMAL, SCHOOL, OUTDOOR, LAKE, RIVER}` AND not one of the two unparseable
# operator pages AND a url AND that url shared with no other roster entry. These assert what the
# PRODUCTION predicate selects on the committed WFS snapshot, so the blast radius is a number in a
# test rather than a surprise in a network build — which for these is the difference between a
# green build and a fail-fast abort.

_CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalog.json"


def _declared_ids(entries: tuple[PoolCatalogEntry, ...]) -> set[str]:
    return {source.entry.pool_id for source in declared_sources(entries)}


def test_a_school_pool_with_its_own_page_is_scraped() -> None:
    # The S2 behaviour change: a SCHOOL entry owning its URL is now fetched like an indoor pool.
    catalog = (
        _entry("schulschwimmanlage-x", "Schule X", PoolKind.SCHOOL, "https://x/school.html"),
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=FIXTURE.read_bytes())),
        catalog,
        FETCHED,
        tariffs=_TARIFFS,
    )
    assert report.failures == ()
    assert [ref for ref, _ in report.extracts] == [Name("Schule X")]


def test_pools_sharing_one_overview_url_are_neither_scraped_nor_failures() -> None:
    # The 14 hallenbaeder.html sharers: excluded by the predicate, so an unparseable overview
    # page can never become 14 build-aborting failures under fail-fast.
    overview = "https://x/hallenbaeder.html"
    catalog = (
        _entry("schulschwimmanlage-a", "Schule A", PoolKind.SCHOOL, overview),
        _entry("schulschwimmanlage-b", "Schule B", PoolKind.SCHOOL, overview),
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=b"<html>no table</html>")),
        catalog,
        FETCHED,
        tariffs=_TARIFFS,
    )
    assert report.extracts == ()
    assert report.failures == ()


def test_an_indoor_pool_sharing_its_url_is_also_excluded() -> None:
    # The URL test is not school-specific: it is about owning the page, whatever the kind.
    shared = "https://x/hallenbaeder.html"
    catalog = (
        _entry("hallenbad-a", "Hallenbad A", PoolKind.INDOOR, shared),
        _entry("schulschwimmanlage-b", "Schule B", PoolKind.SCHOOL, shared),
    )
    assert declared_sources(catalog) == ()


def test_an_entry_without_a_url_is_not_a_declared_source() -> None:
    catalog = (_entry("hallenbad-a", "Hallenbad A", PoolKind.INDOOR, None),)
    assert declared_sources(catalog) == ()


def test_the_declared_sources_are_exactly_twenty_six_pools() -> None:
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    declared = _declared_ids(entries)
    # 7 indoor/thermal + the 4 school pools with their own page + the 15 outdoor/lake/river pools
    # admitted in seasonal-hours S3. Pinned OFFLINE against the committed snapshot: the same
    # number a live `swimzh build` fetches, one page at a time, aborting on the first miss.
    assert len(declared) == 26, sorted(declared)
    assert {p for p in declared if p.startswith("schulschwimmanlage-")} == {
        "schulschwimmanlage-aemtler",
        "schulschwimmanlage-altweg",
        "schulschwimmanlage-riedtli",
        "schulschwimmanlage-tannenrauch",
    }
    by_kind = {e.pool_id: e.kind for e in entries}
    seasonal = {PoolKind.OUTDOOR, PoolKind.LAKE, PoolKind.RIVER}
    assert {p for p in declared if by_kind[p] in seasonal} == {
        "freibad-allenmoos",
        "freibad-auhof",
        "freibad-heuried",
        "freibad-letzigraben",
        "freibad-seebach",
        "freibad-zwischen-den-hoelzern",
        "seebad-katzensee",
        "seebad-utoquai",
        "strandbad-mythenquai",
        "strandbad-tiefenbrunnen",
        "strandbad-wollishofen",
        "flussbad-au-hoengg",
        "flussbad-oberer-letten",
        "frauenbad-stadthausquai",
        "maennerbad-schanzengraben",
    }


def test_the_two_unparseable_operator_pages_are_excluded_by_id() -> None:
    """`seebad-enge` (tonttu.ch) and `freibad-dolder` (doldersports.com) are `LAKE`/`OUTDOOR` and
    hold UNSHARED urls, so neither the kind test nor the url test excludes them — only the
    explicit id list does. Both `ParseError('no HTML schedule table')`, and under fail-fast that
    aborts the whole build, so this is the one test standing between a green build and an abort."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    excluded = {e for e in entries if e.pool_id in {"seebad-enge", "freibad-dolder"}}
    assert len(excluded) == 2
    # They pass every OTHER conjunct — that is why the id list has to exist.
    for entry in excluded:
        assert entry.kind in (PoolKind.LAKE, PoolKind.OUTDOOR), entry
        assert entry.url is not None and "stadt-zuerich" not in entry.url, entry
        assert sum(1 for o in entries if o.url == entry.url) == 1, entry
    assert not _declared_ids(entries) & {"seebad-enge", "freibad-dolder"}


def test_an_excluded_operator_page_is_not_even_fetched_so_it_cannot_fail() -> None:
    """Excluded means excluded, not "fetched and tolerated": no extract AND no `ScrapeFailure`.
    A tolerated failure would still abort the build (`cli._compose_schedules` aborts on the first
    entry in `failures`), so a test that only asserted "no extract" would assert nothing."""
    catalog = (
        _entry("seebad-enge", "Seebad Enge", PoolKind.LAKE, "https://www.tonttu.ch/"),
        _entry("freibad-dolder", "Freibad Dolder", PoolKind.OUTDOOR, "https://x/dolder/"),
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=b"<html>no table</html>")),
        catalog,
        FETCHED,
        tariffs=_TARIFFS,
    )
    assert report.extracts == ()
    assert report.failures == ()


def test_the_unshared_url_test_alone_would_select_more_than_the_predicate_does() -> None:
    """Why the kind gate stays in the conjunction even after the widening: it still excludes the
    13 paddling pools, and the 28 it leaves include the 2 unparseable operator pages that the
    explicit id list — not the kind gate — has to remove."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    shared = {e.url for e in entries if e.url and sum(1 for o in entries if o.url == e.url) > 1}
    unshared = {e.pool_id for e in entries if e.url and e.url not in shared}
    assert len(unshared) == 28
    assert unshared - _declared_ids(entries) == {"seebad-enge", "freibad-dolder"}


def test_the_school_pools_without_public_swimming_share_one_overview_url() -> None:
    """The thirteen "ohne öffentliches Schwimmen" (plus borrweg) all carry the generic
    hallenbaeder.html, so the unshared-url test excludes them and they can never become
    build-aborting failures."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    overview = "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder.html"
    sharing = [e.pool_id for e in entries if e.url == overview]
    assert len(sharing) == 14
    assert "schulschwimmanlage-borrweg" in sharing
    assert not _declared_ids(entries) & set(sharing)


def test_a_school_pool_is_served_the_school_tariff_not_the_hallenbad_one() -> None:
    """The city prints `Eintritte Schulschwimmanlagen` Fr. 5.–/5.–/2.50 separately.

    Serving the general row to all four overcharged every school-pool visitor by Fr. 3.00 (and a
    child by Fr. 1.50) — the amounts were right and the pool they were attached to was wrong.
    """
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    by_id = {e.pool_id: e for e in entries}
    school = next(
        s for s in declared_sources(entries) if s.entry.pool_id == "schulschwimmanlage-aemtler"
    )
    indoor = next(s for s in declared_sources(entries) if s.entry.pool_id == "hallenbad-city")

    assert by_id["schulschwimmanlage-aemtler"].kind is PoolKind.SCHOOL
    school_admission = admission_for(school, _page_of("schulschwimmanlage-aemtler"), _TARIFFS)
    assert isinstance(school_admission, Tariff)
    assert [e.amount_chf for e in school_admission.table.entries] == [
        Decimal("5.00"),
        Decimal("5.00"),
        Decimal("2.50"),
    ]
    general_admission = admission_for(indoor, _page_of("hallenbad-city"), _TARIFFS)
    assert isinstance(general_admission, Tariff)
    assert [e.amount_chf for e in general_admission.table.entries] == [
        Decimal("8.00"),
        Decimal("6.00"),
        Decimal("4.00"),
    ]


# --- the tariff follows the LINK the page publishes (S2) --------------------------------------
#
# The fan-out gated on the literal host `stadt-zuerich.ch` and so dropped the 15 declared sources
# the city publishes on sportamt.ch. Widening the host set was the obvious fix and the wrong one:
# 4 of those pools state "Der Eintritt … ist gratis" and one "wird privat betrieben", so a host
# rule would have invented a Fr. 8.00 charge at five pools that charge nothing. The page's own
# tariff LINK is the discriminator, and these pin it against the committed page fixtures.

_FIXTURES = Path(__file__).resolve().parents[1] / "providers" / "fixtures"

#: `pool_id` → its committed page fixture. Two fixtures are named for the pool's short name rather
#: than its roster id (`maennerbad.html`, `frauenbad.html`), so the mapping cannot be derived.
_PAGE_FIXTURES = {
    "hallenbad-city": "hallenbad_city.html",
    "hallenbad-oerlikon": "hallenbad_oerlikon.html",
    "hallenbad-bungertwies": "hallenbad_bungertwies.html",
    "hallenbad-blaesi": "hallenbad_blaesi.html",
    "hallenbad-leimbach": "hallenbad_leimbach.html",
    "hallenbad-altstetten": "hallenbad_altstetten.html",
    "waermebad-kaeferberg": "waermebad_kaeferberg.html",
    "schulschwimmanlage-aemtler": "schulschwimmanlage_aemtler.html",
    "schulschwimmanlage-altweg": "schulschwimmanlage_altweg.html",
    "schulschwimmanlage-riedtli": "schulschwimmanlage_riedtli.html",
    "schulschwimmanlage-tannenrauch": "schulschwimmanlage_tannenrauch.html",
    "freibad-allenmoos": "freibad_allenmoos.html",
    "freibad-auhof": "freibad_auhof.html",
    "freibad-heuried": "freibad_heuried.html",
    "freibad-letzigraben": "freibad_letzigraben.html",
    "freibad-seebach": "freibad_seebach.html",
    "freibad-zwischen-den-hoelzern": "freibad_zwischen_den_hoelzern.html",
    "seebad-katzensee": "seebad_katzensee.html",
    "seebad-utoquai": "seebad_utoquai.html",
    "strandbad-mythenquai": "strandbad_mythenquai.html",
    "strandbad-tiefenbrunnen": "strandbad_tiefenbrunnen.html",
    "strandbad-wollishofen": "strandbad_wollishofen.html",
    "flussbad-au-hoengg": "flussbad_au_hoengg.html",
    "flussbad-oberer-letten": "flussbad_oberer_letten.html",
    "frauenbad-stadthausquai": "frauenbad.html",
    "maennerbad-schanzengraben": "maennerbad.html",
}

#: The pools whose page links NO city tariff. Four of them the city publishes as FREE
#: ("Der Eintritt ins … ist gratis"), and the Männerbad "wird privat betrieben … ein Gratisbad";
#: altstetten is a private operator with its own price page. None may be charged a city rate.
_NO_TARIFF = {
    "hallenbad-altstetten",
    "flussbad-au-hoengg",
    "flussbad-oberer-letten",
    "seebad-katzensee",
    "maennerbad-schanzengraben",
}


def _page_of(pool_id: str) -> str:
    return (_FIXTURES / _PAGE_FIXTURES[pool_id]).read_text(encoding="utf-8")


def test_states_city_tariff_over_every_declared_sources_committed_page() -> None:
    """21 of the 26 declared sources link the tariff page; exactly 5 do not. Offline, against the
    committed page fixtures — one per declared source, so this is the whole population."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    declared = _declared_ids(entries)
    assert declared == set(_PAGE_FIXTURES), sorted(declared ^ set(_PAGE_FIXTURES))

    stated = {pool_id for pool_id in declared if states_city_tariff(_page_of(pool_id))}
    assert declared - stated == _NO_TARIFF
    assert len(stated) == 21


def test_a_private_operators_own_price_anchors_are_not_the_city_tariff() -> None:
    """`hallenbad-altstetten` carries 9 hrefs containing `preise` across 3 targets of its OWN
    (`/schwimmen-2#preise`, `/schwimmen-2#schwimmpreise`, `/sauna#saunapreise`). A substring test
    on `preise` would price it at the city rate; the match is on the tariff page's PATH."""
    page = _page_of("hallenbad-altstetten")
    hrefs = re.findall(r'href="([^"]*preise[^"]*)"', page)
    assert len(hrefs) == 9, hrefs
    assert len({h.split("://")[-1] for h in hrefs}) == 3, sorted(set(hrefs))
    assert states_city_tariff(page) is False


def test_the_link_is_matched_by_path_not_by_equality_with_the_prices_url() -> None:
    """The pool pages write the link RELATIVE (`/web/de/…`) while the tariff page itself writes it
    ABSOLUTE (`https://www.stadt-zuerich.ch/de/…`) — the two disagree on `web/de/` vs `de/`, so
    equality with `PRICES_URL` recognises neither reliably. Both forms must match."""
    tail = "stadtleben/sport-und-erholung/sport-und-badeanlagen/preise-abos.html"
    relative = f'<a href="/web/de/{tail}">Preise</a>'
    absolute = f'<a href="https://www.stadt-zuerich.ch/de/{tail}">Preise</a>'
    assert states_city_tariff(relative)
    assert states_city_tariff(absolute)
    assert PRICES_URL not in relative  # the literal URL appears in neither form
    # A different page under the same section is not the tariff page.
    assert not states_city_tariff('<a href="/web/de/stadtleben/sport-und-badeanlagen/sauna.html">')


#: The pools whose OWN page states free admission — "Der Eintritt … ist gratis" on the three
#: city-published ones, "ein Gratisbad" on the privately run Männerbad. Exactly `_NO_TARIFF`
#: minus altstetten, whose page states neither (a private operator whose tariff we do not know).
_FREE = _NO_TARIFF - {"hallenbad-altstetten"}


def test_states_free_admission_over_every_declared_sources_committed_page() -> None:
    """The tight sentence matches EXACTLY the 4 free pools and none of the other 22. Offline,
    against the committed page fixtures — one per declared source, so this is the whole
    population, and the whole exposure surface of a too-loose pattern."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    declared = _declared_ids(entries)
    free = {pool_id for pool_id in declared if states_free_admission(_page_of(pool_id))}
    assert free == _FREE
    assert len(declared - free) == 22


def test_the_locker_row_gratis_is_not_a_free_admission_statement() -> None:
    """The trap the loose pattern falls into: `hallenbad_city.html` prints bare `gratis` in its
    Ausstattung/locker rows ("Garderobenkasten … gratis") — as do 21 of the 26 declared pages —
    yet City charges the full Hallenbad rate. The tight sentence must keep it False."""
    page = _page_of("hallenbad-city")
    assert "gratis" in page.lower()  # the bait is really on the page
    assert states_free_admission(page) is False


def test_admission_for_splits_the_declared_sources_four_seventeen_four_one() -> None:
    """The union over the whole population: 4 school-tariff + 17 general-tariff + 4 free +
    1 unknown (altstetten, a private operator), against the committed page fixtures — where
    `prices=None` used to compress the last five into one indistinguishable null."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    school, general, free, unknown = [], [], [], []
    for source in declared_sources(entries):
        admission = admission_for(source, _page_of(source.entry.pool_id), _TARIFFS)
        match admission:
            case Tariff(table) if table is _TARIFFS.school:
                school.append(source.entry.pool_id)
            case Tariff(_):
                general.append(source.entry.pool_id)
            case Free():
                free.append(source.entry.pool_id)
            case Unknown():
                unknown.append(source.entry.pool_id)

    assert sorted(school) == [
        "schulschwimmanlage-aemtler",
        "schulschwimmanlage-altweg",
        "schulschwimmanlage-riedtli",
        "schulschwimmanlage-tannenrauch",
    ]
    assert len(general) == 17, sorted(general)
    assert set(free) == _FREE
    assert unknown == ["hallenbad-altstetten"]
    assert len(school) + len(general) + len(free) + len(unknown) == 26


def test_the_city_host_gate_is_gone_from_the_source_tree() -> None:
    """A hostname is not a fact about pricing — `_CITY_HOST` must exist nowhere in `src/`, so the
    deleted gate cannot quietly come back as a second discriminator."""
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = [p for p in src.rglob("*.py") if "_CITY_HOST" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_a_pool_whose_page_states_neither_tariff_nor_gratis_yields_a_note_not_a_failure() -> None:
    """An `Unknown` pool ships unpriced ON PURPOSE — a note, never a `ScrapeFailure` (which would
    abort the build) and never a silent drop. The subject is a doctored City page (its tariff
    link broken), which states neither fact."""
    catalog = (_entry("hallenbad-x", "Hallenbad X", PoolKind.INDOOR, "https://x/l"),)
    body = _page_of("hallenbad-city").replace(
        "/web/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/preise-abos.html", "/x.html"
    )
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body.encode("utf-8"))),
        catalog,
        FETCHED,
        tariffs=_TARIFFS,
    )
    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    assert aspects.admission == Unknown()
    assert report.notes == ("no city tariff stated: hallenbad-x (https://x/l)",)


def test_a_free_pool_carries_free_as_data_and_needs_no_note() -> None:
    """*"Der Eintritt ins Flussbad Oberer Letten ist gratis."* Before the union that fact
    survived only as a build note; now it is DATA (`Free`), so the note — which existed to keep
    it visible in stderr — has nothing left to carry."""
    catalog = (
        _entry("flussbad-oberer-letten", "Flussbad Oberer Letten", PoolKind.RIVER, "https://x/l"),
    )
    body = _page_of("flussbad-oberer-letten").encode("utf-8")
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
    )
    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    assert aspects.admission == Free()
    assert report.notes == ()


def test_a_page_stating_both_tariff_and_gratis_is_a_tariff_plus_a_contradiction_note() -> None:
    """If a page ever states both facts, the tariff link wins (checked first) and the
    contradiction is surfaced as a note — a page bug to report, never a silent pick and never a
    build failure."""
    body = _page_of("hallenbad-city").replace("</body>", "<p>Der Eintritt ist gratis.</p></body>")
    assert states_city_tariff(body) and states_free_admission(body)  # the premise is real
    catalog = (_entry("hallenbad-city", "Hallenbad City", PoolKind.INDOOR, "https://x/c"),)
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body.encode("utf-8"))),
        catalog,
        FETCHED,
        tariffs=_TARIFFS,
    )
    assert report.failures == ()
    (_ref, aspects) = report.extracts[0]
    assert isinstance(aspects.admission, Tariff)
    assert report.notes == (
        "contradiction: hallenbad-city (https://x/c) links the city tariff "
        "but also states free admission",
    )


def test_a_priced_pool_produces_no_note() -> None:
    catalog = (_entry("hallenbad-city", "Hallenbad City", PoolKind.INDOOR, "https://x/c"),)
    body = _page_of("hallenbad-city").encode("utf-8")
    report = scrape_declared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), catalog, FETCHED, tariffs=_TARIFFS
    )
    (_ref, aspects) = report.extracts[0]
    assert isinstance(aspects.admission, Tariff)
    assert report.notes == ()


# --- SHARED sources: one page's facts fan out to a member set (sharedsource-fanout S3) --------
#
# `shared_sources` is the mirror image of `declared_sources`' unshared-URL test: entries SHARING
# a URL (≥2), admitted back in ONLY when that URL has a registered parser. The two phases
# partition the roster by construction — a URL is either owned (declared) or shared (candidate),
# never both.

_PLANSCHBECKEN_URL = (
    "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/"
    "sommerbaeder/planschbecken.html"
)
_PLANSCHBECKEN_FIXTURE = _FIXTURES / "planschbecken.html"


def test_shared_sources_over_the_committed_catalog_is_exactly_the_planschbecken_page() -> None:
    """ONE shared source: the Planschbecken overview, 13 members, all `PADDLING` — and disjoint
    from the declared sources, so no pool is ever scraped by both phases."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    sources = shared_sources(entries)
    assert len(sources) == 1, [s.url for s in sources]
    (source,) = sources
    assert source.url == _PLANSCHBECKEN_URL
    assert len(source.members) == 13
    assert all(e.kind is PoolKind.PADDLING for e in source.members)
    assert all(e.pool_id.startswith("planschbecken-") for e in source.members)
    assert not {e.pool_id for e in source.members} & _declared_ids(entries)


def test_hallenbaeder_overview_yields_no_shared_source_because_no_parser_reads_it() -> None:
    """The 14-sharer school overview page names ZERO of its sharers (verified 2026-08-07), so no
    parser is registered for it and the registry keeps it out — those pools stay `no_source`."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    overview = (
        "https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/"
        "sport-und-badeanlagen/hallenbaeder.html"
    )
    assert sum(1 for e in entries if e.url == overview) == 14  # genuinely shared — the premise
    assert overview not in {s.url for s in shared_sources(entries)}


def test_unterer_letten_pair_yields_no_shared_source_because_it_is_identity_aliasing() -> None:
    """Two roster entries share one REAL pool page — an identity problem, not a fact fan-out:
    admitting it would fan one pool's facts onto two entries without deciding whether they are
    one pool. No parser is registered, so the pair stays out."""
    entries = catalog_json.loads(_CATALOG.read_text(encoding="utf-8"))
    pair = [e for e in entries if e.pool_id.startswith("flussbad-unterer-letten")]
    assert len(pair) == 2 and len({e.url for e in pair}) == 1  # genuinely shared — the premise
    assert pair[0].url not in {s.url for s in shared_sources(entries)}


def _paddling_catalog() -> tuple[PoolCatalogEntry, ...]:
    """Three of the real members (name + kind + the real shared URL) — enough to prove the
    fan-out shape without carrying all 13 through every double."""
    members = (
        ("planschbecken-althoos", "Planschbecken Althoos"),
        ("planschbecken-artergut", "Planschbecken Artergut"),
        ("planschbecken-josefswiese", "Planschbecken Josefswiese"),
    )
    return tuple(
        _entry(pool_id, name, PoolKind.PADDLING, _PLANSCHBECKEN_URL) for pool_id, name in members
    )


def test_scrape_shared_sources_fetches_once_and_emits_one_extract_per_member() -> None:
    """ONE fetch for the whole set; per member one identity-free extract carrying the SAME
    page-level facts — season (Mai–September, MONTH, fair-only) and `Free()` — and nothing
    per-pool: no basins (the page publishes no timetable), no closures, no notices."""
    body = _PLANSCHBECKEN_FIXTURE.read_bytes()
    fetches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetches.append(str(request.url))
        return httpx.Response(200, content=body)

    report = scrape_shared_sources(_client(handler), _paddling_catalog(), FETCHED)

    assert fetches == [_PLANSCHBECKEN_URL]  # one fetch, not one per member
    assert report.failures == ()
    assert report.notes == ()
    assert [ref for ref, _ in report.extracts] == [
        Name("Planschbecken Althoos"),
        Name("Planschbecken Artergut"),
        Name("Planschbecken Josefswiese"),
    ]
    for _ref, aspects in report.extracts:
        season = aspects.operating_season
        assert season is not None
        assert (season.window.start.month, season.window.end.month) == (5, 9)
        assert season.window.precision is DatePrecision.MONTH
        assert season.weather is Weather.FAIR_ONLY
        assert aspects.admission == Free()
        assert aspects.basins == ()  # no timetable is minted — the schedule stays no_source
        assert aspects.closures == () and aspects.notices == ()


def test_a_shared_page_fetch_failure_is_one_failure_for_the_whole_set() -> None:
    """Fail-fast fails ONCE: 3 members, one 503 → exactly one `ScrapeFailure`, zero extracts —
    never one failure per member."""

    def down(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    report = scrape_shared_sources(_client(down), _paddling_catalog(), FETCHED)
    assert report.extracts == ()
    assert len(report.failures) == 1
    assert report.failures[0].url == _PLANSCHBECKEN_URL


def test_a_shared_page_parse_failure_is_one_typed_failure_for_the_whole_set() -> None:
    """A page whose season sentence is gone is `Err(ParseError)` — one typed failure for the
    set, so the build aborts once carrying the cause."""
    page = _PLANSCHBECKEN_FIXTURE.read_text(encoding="utf-8")
    sentence = "Diese sind je nach Wetter von Mai bis September in Betrieb."
    assert sentence in page  # the premise is real
    body = page.replace(sentence, "").encode("utf-8")

    report = scrape_shared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), _paddling_catalog(), FETCHED
    )
    assert report.extracts == ()
    assert len(report.failures) == 1
    assert isinstance(report.failures[0].cause, ParseError)


def test_a_shared_page_without_the_gratis_sentence_ships_unknown_plus_one_note() -> None:
    """Stated facts only: `kostenlos` gone → `Unknown()` on every member (never inferred free),
    plus ONE audit note for the set — the shared mirror of the declared unpriced-pool note."""
    page = _PLANSCHBECKEN_FIXTURE.read_text(encoding="utf-8")
    assert "kostenlos" in page  # the premise is real
    body = page.replace("kostenlos", "").encode("utf-8")

    report = scrape_shared_sources(
        _client(lambda _r: httpx.Response(200, content=body)), _paddling_catalog(), FETCHED
    )
    assert report.failures == ()
    assert all(aspects.admission == Unknown() for _ref, aspects in report.extracts)
    assert report.notes == (f"no admission stated on shared page: {_PLANSCHBECKEN_URL}",)


def test_a_catalog_without_shared_registered_urls_fetches_nothing() -> None:
    """The phase is inert off the Planschbecken page: an unshared URL (a declared source's own
    page) and a shared-but-unregistered one both yield zero fetches, zero extracts. The
    registered page being ABSENT from the roster entirely (0 sharers) is itself the drift
    note, not silence."""

    def boom(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("no fetch may happen")

    overview = "https://x/hallenbaeder.html"
    catalog = (
        _entry("hallenbad-city", "Hallenbad City", PoolKind.INDOOR, "https://x/city.html"),
        _entry("schulschwimmanlage-a", "Schule A", PoolKind.SCHOOL, overview),
        _entry("schulschwimmanlage-b", "Schule B", PoolKind.SCHOOL, overview),
    )
    report = scrape_shared_sources(_client(boom), catalog, FETCHED)
    assert report == scrape_shared_sources(_client(boom), (), FETCHED)
    assert report.extracts == () and report.failures == ()
    assert report.notes == (
        f"registered shared page has 0 roster sharer(s); fan-out inert: {_PLANSCHBECKEN_URL}",
    )


def test_a_registered_shared_page_with_one_sharer_is_an_audit_note_not_a_silent_drop() -> None:
    """The WFS-drift alarm: if the roster ever collapses the member set to a single entry (a
    rename has drifted this roster before), the registered URL stops being *shared* and would
    exit BOTH phases silently — not shared → no fan-out; `PADDLING` → never a declared source.
    The registered parser is a promise the roster no longer honours: ONE audit note (the
    unpriced-pool posture), zero fetches, zero extracts, and never a failure."""

    def boom(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("a single sharer must not be fetched")

    catalog = (
        _entry(
            "planschbecken-althoos", "Planschbecken Althoos", PoolKind.PADDLING, _PLANSCHBECKEN_URL
        ),
    )
    report = scrape_shared_sources(_client(boom), catalog, FETCHED)
    assert report.extracts == () and report.failures == ()
    assert report.notes == (
        f"registered shared page has 1 roster sharer(s); fan-out inert: {_PLANSCHBECKEN_URL}",
    )
