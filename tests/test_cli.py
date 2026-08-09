"""The CLI commands build a gold store (roster sourced from the WFS via recorded HTTP) and
enrich it via scrape (all HTTP through MockTransport / recorded snapshots — never live)."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.build.compose import ScrapedAspects, compose
from swimzh.cli import (
    CACHE_ENV_VAR,
    CacheModeError,
    ProviderClients,
    build,
    build_catalog_file,
    cache_mode,
    cache_transport,
    live_timeout,
    live_transport,
    main,
    scrape_gold,
    scrape_lanes,
)
from swimzh.core.errors import SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.httpcache import (
    DEFAULT_CACHE_ROOT,
    CacheMode,
    DiskCacheTransport,
    request_tier,
    request_ttl_s,
)
from swimzh.core.result import Err, Ok
from swimzh.domain.admission import Tariff, Unknown
from swimzh.domain.catalog import PoolCatalogEntry, ScheduleFreshness
from swimzh.domain.closure import ClosureCode
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import BasinId, Facility, PoolKind, reconstruct_pool_id
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.resolver import resolve_basin
from swimzh.domain.schedule import ClosedDay, OpenDay, Weather
from swimzh.etl.build import build_store
from swimzh.etl.scrape import ScrapeReport, declared_sources, shared_sources
from swimzh.providers.geo_sport import POOL_LAYERS
from swimzh.providers.price_scraper import PRICES_URL
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_roster,
    open_db,
    write_schedules,
)
from tests.pipeline_clients import (
    clients_over,
    recorded_build_clients,
    unreachable_wfs_clients,
)
from tests.providers.wfs_snapshot import recorded_build_transport


def _build_clients() -> ProviderClients:
    """The per-source clients the ONE-command atomic `build` needs: since S2 `build` runs the whole
    pipeline (WFS roster → schedule scrape → lane scrape → compose), a single `MockTransport` routes
    WFS layers, pool pages, Belegungsplan PDFs, and the price page from committed fixtures — so a
    `build(...)` reproduces the full store offline, with real scraped schedules. Since S4 the five
    sources get five clients over that one transport (each stamping its own cache tier)."""
    return recorded_build_clients()


def _db_content_digest(path: Path) -> tuple[str, ...]:
    """A CONTENT digest of the gold DB: its logical schema+data as an `iterdump()` statement stream.

    Deliberately not a file-byte hash — a temp-swapped/rolled-back SQLite file can differ byte-wise
    while logically identical, so S4's "prior gold content-unchanged" is asserted on the dumped rows
    (schema + `INSERT`s), not on the bytes."""
    conn = sqlite3.connect(path)
    try:
        return tuple(conn.iterdump())
    finally:
        conn.close()


def _facility_from_read_path(db: Path, facility_id: str) -> Facility:
    """Read one facility from the flipped read path — ``pool.facility_doc`` via the
    ``GoldRepository`` the app serves from. B4 routes ``scrape-gold``/``scrape-lanes`` through
    ``write_schedules``, so their enrichment (scraped schedules, lane plans) is now visible on
    this read path, not on the retired ``facility`` table.
    """
    facility = GoldRepository(open_db(db)).get(reconstruct_pool_id(facility_id))
    assert facility is not None, facility_id
    return facility


_FIXTURES = Path(__file__).resolve().parent / "providers" / "fixtures"
FIXTURE_HTML = _FIXTURES / "hallenbad_city.html"
FIXTURE_PDF = _FIXTURES / "city-schwimmerbecken.pdf"

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ZURICH = ZoneInfo("Europe/Zurich")
FETCHED_AT = datetime(2026, 7, 18, 9, 0, tzinfo=ZURICH)
# The committed catalog.json IS the WFS snapshot, so it is the recorded roster double for the
# offline `build_store` base some scrape-gold re-layer tests need (a store with schedule-less
# indoor pools, so the thin scrape-gold command demonstrably adds the schedule).
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


def _offline_base(db: Path) -> None:
    """Assemble the pre-scrape base offline via `build_store` (no schedule scrape), so an indoor
    pool like Altstetten starts SCHEDULE-LESS — the precondition the thin `scrape-gold` re-layer
    tests need. (The atomic `build` folds the scrape in, so it would arrive already scheduled.)"""
    result = build_store(DATA_DIR, db, _ROSTER)
    assert isinstance(result, Ok), result


def _layer_handler(request: httpx.Request) -> httpx.Response:
    typename = request.url.params.get("TYPENAME", "")
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"{typename}.1",
                "geometry": {"type": "Point", "coordinates": [8.5, 47.3]},
                "properties": {"name": f"Pool {typename}"},
            }
        ],
    }
    return httpx.Response(200, json=fc)


def test_build_catalog_writes_all_layers(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    inner = httpx.Client(transport=httpx.MockTransport(_layer_handler))
    client = HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))
    code = build_catalog_file(out=out, client=client, generated_at=FETCHED_AT)
    assert code == 0

    entries = catalog_json.loads(out.read_text(encoding="utf-8"))
    assert len(entries) == len(POOL_LAYERS)  # one feature per layer
    assert {e.kind.value for e in entries} == {k.value for k in POOL_LAYERS.values()}


def _city_catalog_file(tmp_path: Path) -> Path:
    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 71",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url="https://example.test/city.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")
    return catalog_file


def _scraped_only_catalog_file(tmp_path: Path) -> Path:
    """A catalog naming an INDOOR pool the curated dataset does NOT cover (Hallenbad Altstetten
    resolves to the scraped-only `hallenbad-altstetten` spine row). Its scraped schedule can
    reach the read path only if scrape-gold writes it to `pool.facility_doc`."""
    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-altstetten",
        name="Hallenbad Altstetten",
        kind=PoolKind.INDOOR,
        address="Flurstrasse 91",
        geo=GeoPoint(lat=47.39, lon=8.49),
        url="https://example.test/altstetten.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")
    return catalog_file


def _with_price_fixture(fallback_body: bytes) -> ProviderClients:
    """Clients serving the committed tariff fixture at the price page, `fallback_body` elsewhere.

    Since admission-union S2 a failed `scrape_prices` is FATAL to the schedule phase (`scrape-gold`
    drives the same `_compose_schedules`), so every scrape double must serve a parseable price
    page — unless the price failure IS the test's subject
    (`test_build_price_scrape_failure_aborts_content_unchanged`)."""
    prices = (_FIXTURES / "preise_abos.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if "preise-abos" in str(request.url):
            return httpx.Response(200, content=prices)
        return httpx.Response(200, content=fallback_body)

    return clients_over(httpx.MockTransport(handler))


def _city_scrape_clients() -> ProviderClients:
    """The city page for every pool URL, plus the parseable price page every scrape now needs."""
    return _with_price_fixture(FIXTURE_HTML.read_bytes())


def test_scrape_gold_composes_onto_built_store(tmp_path: Path) -> None:
    # scrape-gold now layers onto an already-built spine: it resolves the scraped WFS name to a
    # canonical id by lookup and composes, rather than minting a second (long-slug) row.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    code = scrape_gold(
        db_path=db,
        catalog_path=_city_catalog_file(tmp_path),
        clients=_city_scrape_clients(),
        fetched_at=FETCHED_AT,
    )
    assert code == 0
    # No second row for City: the scrape composed onto the curated pool. Since S1 gives EVERY
    # catalog pool a `facility_doc` (universal detail), the read path holds the full roster (57),
    # and there is exactly one City row (no long-slug duplicate).
    facilities = GoldRepository(open_db(db)).load_all()
    assert len(facilities) == 57
    assert sum(1 for f in facilities if str(f.identity.facility_id) == "hallenbad-city") == 1


def test_scrape_gold_wires_scraped_only_pool_onto_read_path(tmp_path: Path) -> None:
    # B4 wiring proof: scrape-gold MUST write the composed facilities through `write_schedules`
    # (→ `pool.facility_doc`, the read path). A scraped-ONLY pool (curated data lacks it) can
    # appear on that path only if the reroute holds; were scrape-gold to stop writing
    # `pool.facility_doc`, the pool's blob stays NULL and `get` returns None — so this test goes
    # red on that mutation, closing the enrichment gap for good. Base built OFFLINE (no folded
    # scrape) so Altstetten starts schedule-less; the thin scrape-gold then adds its schedule.
    db = tmp_path / "gold.sqlite"
    _offline_base(db)
    altstetten = reconstruct_pool_id("hallenbad-altstetten")
    # Uncurated before the scrape: Slice F gives it a SCHEDULE-LESS prose blob, so it may be
    # present on the read path but carries no schedule rule yet.
    before = GoldRepository(open_db(db)).get(altstetten)
    assert before is None or not any(b.rules for b in before.basins)

    code = scrape_gold(
        db_path=db,
        catalog_path=_scraped_only_catalog_file(tmp_path),
        clients=_city_scrape_clients(),
        fetched_at=FETCHED_AT,
    )
    assert code == 0

    served = GoldRepository(open_db(db)).get(altstetten)
    assert served is not None, "scraped-only pool must reach pool.facility_doc via write_schedules"
    # The scraped schedule (parsed from the fixture) is now on the read path…
    assert any(b.rules for b in served.basins)
    # …carrying scraped (not curated) provenance — proof it came through the scrape, not a seed.
    assert served.provenance.curated is False


def test_scrape_merge_puts_curated_schedule_and_scraped_price_on_read_path(tmp_path: Path) -> None:
    # B4 acceptance: scrape-gold writes the composed facility through `write_schedules`, so the
    # per-aspect merge (curated schedule kept + a scraped price the curated data lacked) is now
    # visible on the read path (`pool.facility_doc` via `GoldRepository`), where `/swim` reads.
    # The live scrape-gold mock yields no scraped price for City (its own curated price already
    # wins), so this drives the same compose→`write_schedules` seam scrape-gold runs internally,
    # over the real curated City with its price stripped so the scraped price is the one that
    # fills the gap.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    conn = open_db(db)

    curated_city = GoldRepository(conn).get(reconstruct_pool_id("hallenbad-city"))
    assert curated_city is not None
    assert isinstance(curated_city.admission, Tariff)  # real built City carries a tariff
    assert any(b.rules for b in curated_city.basins)  # ...and a curated schedule
    priceless_city = replace(curated_city, admission=Unknown())

    scraped_price = PriceTable(
        entries=(PriceEntry(PriceCategory.ADULT, Decimal("8.00"), "Erwachsene CHF 8.00"),),
        valid_as_of=FETCHED_AT.date(),
        source_url="https://example.test/prices",
    )
    scraped = ScrapedAspects(
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address=curated_city.address,
        geo=curated_city.geo,
        basins=(),
        closures=(),
        notices=(),
        admission=Tariff(scraped_price),
        fetched_at=FETCHED_AT,
    )
    composition = compose((priceless_city,), ((reconstruct_pool_id("hallenbad-city"), scraped),))
    write_schedules(conn, tuple((f.identity.facility_id, f) for f in composition.facilities))

    served = GoldRepository(open_db(db)).get(reconstruct_pool_id("hallenbad-city"))
    assert served is not None
    assert served.basins == curated_city.basins  # curated schedule preserved through the seam
    # Scraped tariff gained, now on `pool.facility_doc`.
    assert served.admission == Tariff(scraped_price)


def test_scrape_gold_requires_a_built_store(tmp_path: Path) -> None:
    # Without a prior `build` the spine is absent, so there is no id namespace to resolve into —
    # scrape-gold refuses rather than opening a second door to a gold row.
    code = scrape_gold(
        db_path=tmp_path / "absent.sqlite",
        catalog_path=_city_catalog_file(tmp_path),
        clients=_city_scrape_clients(),
        fetched_at=FETCHED_AT,
    )
    assert code == 1


def test_scrape_gold_unreconcilable_name_is_reported_not_silently_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # D2 partial success: a lone scraped name in no alias is a benign miss — never a silent
    # wrong-pool write. Nothing is composed (no resolved refs), the miss is reported to stderr,
    # and the exit code is non-zero so the miss stays visible.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}

    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-nonexistent",
        name="Hallenbad Nonexistent",  # in no pool_alias row
        kind=PoolKind.INDOOR,
        address="",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url="https://example.test/city.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")

    code = scrape_gold(
        db_path=db, catalog_path=catalog_file, clients=_city_scrape_clients(), fetched_at=FETCHED_AT
    )
    assert code == 1  # the unmatched name is signalled by a non-zero exit
    # The miss is named on stderr, not swallowed.
    assert "Hallenbad Nonexistent" in capsys.readouterr().err
    # The store's facility set is unchanged — nothing was attached to a guessed pool.
    after = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}
    assert after == before


def _partial_catalog_file(tmp_path: Path) -> Path:
    """A catalog mixing pools that reconcile (curated `Hallenbad City`, scraped-only
    `Hallenbad Altstetten`) with one benign miss (`Hallenbad Nonexistent`, in no alias). Every
    entry is INDOOR with a URL, so all three are scraped; only the matched two are written."""
    catalog_file = tmp_path / "catalog.json"
    entries = (
        PoolCatalogEntry(
            pool_id="hallenbad-city",
            name="Hallenbad City",
            kind=PoolKind.INDOOR,
            address="Sihlstrasse 71",
            geo=GeoPoint(lat=47.37, lon=8.53),
            url="https://example.test/city.html",
            description=None,
            phone=None,
        ),
        PoolCatalogEntry(
            pool_id="hallenbad-altstetten",
            name="Hallenbad Altstetten",
            kind=PoolKind.INDOOR,
            address="Flurstrasse 91",
            geo=GeoPoint(lat=47.39, lon=8.49),
            url="https://example.test/altstetten.html",
            description=None,
            phone=None,
        ),
        PoolCatalogEntry(
            pool_id="hallenbad-nonexistent",
            name="Hallenbad Nonexistent",  # in no pool_alias row -> benign miss
            kind=PoolKind.INDOOR,
            address="",
            geo=GeoPoint(lat=47.37, lon=8.53),
            url="https://example.test/nonexistent.html",
            description=None,
            phone=None,
        ),
    )
    catalog_file.write_text(catalog_json.dumps(entries, FETCHED_AT), encoding="utf-8")
    return catalog_file


def test_scrape_gold_partial_success_writes_matched_reports_unmatched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # D2 acceptance: one unmatched name among several matched. The matched pools ARE written to
    # `pool.facility_doc` (partial success — the good scrapes are not discarded), the unmatched
    # name is reported to stderr, and the exit code is non-zero so the miss stays visible. Base
    # built OFFLINE (no folded scrape) so Altstetten starts schedule-less.
    db = tmp_path / "gold.sqlite"
    _offline_base(db)
    altstetten = reconstruct_pool_id("hallenbad-altstetten")
    # Scraped-only pool: before the scrape it carries at most a SCHEDULE-LESS Slice-F prose blob
    # (no rule), so no scraped schedule is on the read path yet.
    before = GoldRepository(open_db(db)).get(altstetten)
    assert before is None or not any(b.rules for b in before.basins)

    code = scrape_gold(
        db_path=db,
        catalog_path=_partial_catalog_file(tmp_path),
        clients=_city_scrape_clients(),
        fetched_at=FETCHED_AT,
    )
    assert code == 1  # non-zero because one name stayed unmatched

    # The matched scraped-only pool reached the read path (`pool.facility_doc`) — partial success.
    served = GoldRepository(open_db(db)).get(altstetten)
    assert served is not None, "matched pools must be written even when some are unresolved"
    assert any(b.rules for b in served.basins)  # the scraped schedule is on the read path
    assert served.provenance.curated is False  # it came through the scrape, not a seed
    # The matched curated pool is still present too.
    assert GoldRepository(open_db(db)).get(reconstruct_pool_id("hallenbad-city")) is not None
    # The unmatched name is named on stderr, not swallowed.
    assert "Hallenbad Nonexistent" in capsys.readouterr().err


def test_scrape_gold_ambiguous_reconcile_aborts_writing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Ambiguous stays structurally fatal. Scrape extracts are `Name`-only, so they can NEVER be
    # ambiguous by construction (D1's discovery) — a faithful CLI-level ambiguous scrape cannot
    # exist. So we drive scrape_gold's `case Err` branch directly: a `resolve_all` that returns
    # the typed ambiguous `Err` a seeded ambiguous crosswalk would produce (see
    # `test_resolve_all_is_fatal_on_ambiguous_ref_naming_the_offender`). The store must be left
    # untouched — never a silent wrong-pool write.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}

    ambiguous = SchemaMismatch(source="reconcile", detail="ambiguous basin hint: 'Twin Bad'")
    monkeypatch.setattr("swimzh.cli.resolve_all", lambda _extracts, _crosswalk: Err(ambiguous))

    code = scrape_gold(
        db_path=db,
        catalog_path=_city_catalog_file(tmp_path),
        clients=_city_scrape_clients(),
        fetched_at=FETCHED_AT,
    )
    assert code == 1
    assert "ambiguous" in capsys.readouterr().err.lower()
    # Nothing written: the ambiguous batch aborts whole, leaving the store as `build` left it.
    after = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}
    assert after == before


def test_scrape_gold_declared_source_parse_failure_aborts_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance (scrape-gold): a declared source (an INDOOR catalog pool) whose page cannot be
    # parsed is NOT skipped-and-green — the whole run ABORTS non-zero carrying the typed cause, and
    # the prior gold DB is CONTENT-unchanged (content digest, not byte hash).
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    # The city page fetches 200 but has no timetable, so `parse_schedule` fails -> a declared
    # source failure with a typed ParseError cause. The price page is served its REAL fixture
    # (`_with_price_fixture`) so the abort under test stays the pool page's, not the tariff
    # page's own fatal case.
    clients = _with_price_fixture(b"<html>no table</html>")
    code = scrape_gold(
        db_path=db,
        catalog_path=_city_catalog_file(tmp_path),
        clients=clients,
        fetched_at=FETCHED_AT,
    )
    assert code == 1
    assert _db_content_digest(db) == before  # nothing written — the live store is unchanged
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "parse error" in err.lower()  # the typed ProviderError cause is surfaced


def test_build_and_scrape_gold_share_one_id_namespace(tmp_path: Path) -> None:
    # The acceptance: build and scrape-gold write into the SAME id namespace. Every facility row
    # id (the /swim read path) is a real pool PK — no long-vs-short split-brain.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    assert (
        scrape_gold(
            db_path=db,
            catalog_path=_city_catalog_file(tmp_path),
            clients=_city_scrape_clients(),
            fetched_at=FETCHED_AT,
        )
        == 0
    )

    conn = open_db(db)
    pool_ids = {row[0] for row in conn.execute("SELECT id FROM pool").fetchall()}
    facility_ids = {str(f.identity.facility_id) for f in GoldRepository(conn).load_all()}
    assert facility_ids  # non-empty
    assert facility_ids <= pool_ids  # every scheduled facility id is a canonical pool PK


def _pdf_clients(handler: Callable[[httpx.Request], httpx.Response]) -> ProviderClients:
    return clients_over(httpx.MockTransport(handler))


# Each curated pool page (its roster `url` ends `<name>.html`) -> the saved page fixture whose
# Belegungsplan links `scrape-lanes` now DISCOVERS before fetching the PDFs.
_PAGE_BY_FILENAME: dict[str, str] = {
    "city.html": "hallenbad_city.html",
    "oerlikon.html": "hallenbad_oerlikon.html",
    "bungertwies.html": "hallenbad_bungertwies.html",
    "blaesi.html": "hallenbad_blaesi.html",
    "leimbach.html": "hallenbad_leimbach.html",
    "kaeferberg.html": "waermebad_kaeferberg.html",
    "aemtler.html": "schulschwimmanlage_aemtler.html",
}


def _lane_clients(pdf_handler: Callable[[httpx.Request], httpx.Response]) -> ProviderClients:
    """Clients for the two-round `scrape-lanes` flow: a pool-page GET is served the matching HTML
    fixture (so its Belegungsplan links are discovered), a `.pdf` GET is delegated to `pdf_handler`,
    and any other roster page (a location-only pool) is served an empty page (no links)."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith(".pdf"):
            return pdf_handler(request)
        fixture = _PAGE_BY_FILENAME.get(url.rsplit("/", 1)[-1])
        if fixture is not None:
            return httpx.Response(200, content=(_FIXTURES / fixture).read_bytes())
        return httpx.Response(200, content=b"<html></html>")

    return _pdf_clients(handler)


def test_scrape_lanes_attaches_plan_to_curated_basin(tmp_path: Path) -> None:
    # `scrape-lanes` reads the curated facilities (from `pool.facility_doc`), needs the offline
    # `build` spine present, discovers the pool page's Belegungsplan links, then writes the
    # attached plan back through `write_schedules`.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    body = FIXTURE_PDF.read_bytes()
    clients = _lane_clients(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(db_path=db, clients=clients, fetched_at=FETCHED_AT)
    assert code == 0

    # B4 closes the B2→B4 enrichment gap: the lane plan is now on the read path
    # (`pool.facility_doc`), a scraped aspect curated City lacked, visible where `/swim` reads.
    city = _facility_from_read_path(db, "hallenbad-city")
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlan)
    assert lap.lane_plan.lane_count == 6
    assert lap.lane_plan.fetched_at == FETCHED_AT


def test_scrape_lanes_missing_db_is_error(tmp_path: Path) -> None:
    clients = _pdf_clients(lambda _r: httpx.Response(200, content=b""))
    code = scrape_lanes(db_path=tmp_path / "absent.sqlite", clients=clients, fetched_at=FETCHED_AT)
    assert code == 1


def test_scrape_lanes_pdf_fetch_failure_aborts_leaving_store_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance: pages discover their Belegungsplan links, but every discovered PDF 503s. That
    # is a declared/discovered source fetch failure -> the WHOLE run ABORTS non-zero (no persisted
    # LanePlanUnavailable that lets the facility build), and the prior gold DB is CONTENT-unchanged
    # (asserted via a content digest, not a byte hash). The abort message carries the typed cause.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    clients = _lane_clients(lambda _r: httpx.Response(503, text="down"))
    code = scrape_lanes(db_path=db, clients=clients, fetched_at=FETCHED_AT)
    assert code == 1
    assert _db_content_digest(db) == before  # temp discarded — the live store never mutated
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "HTTP 503" in err  # the typed ProviderError cause is surfaced


_OERLIKON_COMBINED_PDF = _FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf"


def test_scrape_lanes_prints_unbound_audit_for_uncurated_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 audit: with every discovered source fetching fine (no miss -> no abort), the combined
    # Oerlikon sheet attaches Sprungbecken (its section token) and surfaces the still-uncurated
    # Nichtschwimmer section as a per-URL `unbound` line (an undiscovered-basin extra, non-fatal —
    # NOT a missing declared fact). The run succeeds. (Under S4 a 503 here would ABORT instead, so
    # the audit is exercised on an all-success run.)
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    oerlikon = _facility_from_read_path(db, "hallenbad-oerlikon")
    sprung = next(b for b in oerlikon.basins if b.basin_id == BasinId("oerlikon-sprungbecken"))
    assert sprung.lane_plan_source is not None
    combined_url = sprung.lane_plan_source.url
    combined_pdf = _OERLIKON_COMBINED_PDF.read_bytes()
    # Every OTHER discovered single-basin sheet is served a valid (URL-agnostic) plan so it binds
    # by URL and nothing fails to fetch.
    single_pdf = FIXTURE_PDF.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == combined_url:
            return httpx.Response(200, content=combined_pdf)
        return httpx.Response(200, content=single_pdf)

    code = scrape_lanes(db_path=db, clients=_lane_clients(handler), fetched_at=FETCHED_AT)
    assert code == 0  # every source fetched; Sprungbecken + the single-basin sheets attach

    err = capsys.readouterr().err
    # per-URL unbound: the uncurated Nichtschwimmer section — url + header + reason.
    assert "unbound" in err
    assert combined_url in err
    assert "Nichtschwimmer" in err


def test_scrape_lanes_prints_unmatched_section_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S3 audit-completeness: a curated basin declares a `section` token, its stacked sheet parses,
    # but the token matches NO parsed header (here the single-basin Schwimmerbecken sheet is served
    # at the combined URL — "Sprungbecken" never appears). The basin is left None, but the silent
    # drop is surfaced as an `unmatched section` audit line (a parser-header-regression alarm).
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    oerlikon = _facility_from_read_path(db, "hallenbad-oerlikon")
    combined_url = next(
        b.lane_plan_source.url
        for b in oerlikon.basins
        if b.basin_id == BasinId("oerlikon-sprungbecken") and b.lane_plan_source is not None
    )
    # The single-basin Schwimmerbecken sheet's header never contains the "Sprungbecken" token.
    wrong_sheet = (_FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes()
    city_sheet = FIXTURE_PDF.read_bytes()

    # Under S4 any 503 would ABORT before the unmatched-section audit, so every OTHER discovered
    # source is served a valid single-basin plan (it binds by URL); only the combined URL gets the
    # wrong sheet, whose header lacks the declared "Sprungbecken" token.
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == combined_url:
            return httpx.Response(200, content=wrong_sheet)
        return httpx.Response(200, content=city_sheet)

    code = scrape_lanes(db_path=db, clients=_lane_clients(handler), fetched_at=FETCHED_AT)
    assert code == 0  # City attached, so the run succeeds

    err = capsys.readouterr().err
    assert "unmatched section" in err
    assert "oerlikon-sprungbecken" in err
    assert "sprungbecken" in err


def test_scrape_lanes_empty_store_is_error(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # schema only, no facilities
    clients = _pdf_clients(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    code = scrape_lanes(db_path=db, clients=clients, fetched_at=FETCHED_AT)
    assert code == 1


def test_scrape_lanes_authored_source_not_advertised_aborts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance (S2-surfaced case): an authored `lane_plan_source.url` its pool page fails to
    # advertise (`authored − discovered` non-empty — here every page returns an EMPTY body, so no
    # link is discovered) is a HARD abort, never a silent drop. The prior gold DB is
    # content-unchanged and the abort carries the typed cause.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    # Pool pages fetch 200 but advertise NO Belegungsplan links (so no PDF is ever fetched).
    clients = clients_over(
        httpx.MockTransport(lambda _r: httpx.Response(200, content=b"<html></html>"))
    )
    code = scrape_lanes(db_path=db, clients=clients, fetched_at=FETCHED_AT)
    assert code == 1
    assert _db_content_digest(db) == before  # never mutated — the authored source is stranded loud
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "not advertised" in err  # typed SchemaMismatch: the page no longer lists the URL


def test_build_produces_complete_store(tmp_path: Path) -> None:
    # S2: `build` is now the ONE atomic pipeline — roster + curated assemble + schedule scrape +
    # lane scrape + compose. So a single command yields a store whose INDOOR pools carry REAL
    # scraped schedules (curated-wins keeps a curated schedule where present, and the scrape fills
    # the schedule-less indoor pools), on top of the full ~57-pool roster.
    db = tmp_path / "gold.sqlite"
    code = build(db_path=db, data_dir=DATA_DIR, clients=_build_clients())
    assert code == 0
    assert db.exists()

    conn = open_db(db)
    # The pool spine holds every known pool (the ~57-pool WFS roster).
    assert len(load_roster(conn)) == 57
    # Calendar table covers the current planning horizon.
    assert load_calendar(conn).covers(datetime(2026, 1, 1, tzinfo=ZURICH).date())
    facilities = GoldRepository(conn).load_all()
    # Every one of the 7 INDOOR pools now carries a schedule from the folded scrape — the atomic
    # build's scrape is the schedule source (city/oerlikon among them, asserted by the web suite).
    scheduled = {str(f.identity.facility_id) for f in facilities if any(b.rules for b in f.basins)}
    assert {"hallenbad-city", "hallenbad-oerlikon"} <= scheduled
    indoor = {str(e.entry.pool_id) for e in load_roster(conn) if e.entry.kind is PoolKind.INDOOR}
    assert indoor <= scheduled  # every indoor pool got a scraped schedule
    # …plus the schedule-less non-indoor pools (outdoor/lake/school) — a strict superset.
    stored = {str(f.identity.facility_id) for f in facilities}
    assert stored > scheduled


def test_build_reports_the_pools_that_state_no_city_tariff_and_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pool whose page states neither the city tariff nor free admission is `Unknown` ON
    PURPOSE — not a build failure, so the build exits 0; but not silence either, because the
    LIVE build reads `fetch_roster`, not the committed `catalog.json`, so a WFS url drift that
    quietly unprices a pool would leave no other trace. Under the admission union only
    altstetten (a private operator) is left in that state: the four pools that state their own
    gratis sentence now carry `Free` as DATA, so the note — which existed to keep their
    free-ness visible in stderr — no longer fires for them. Gated on the committed fixtures
    rather than a manual build."""
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    noted = {
        line.split(": ", 1)[1].split(" (", 1)[0]
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("no city tariff stated: ")
    }
    assert noted == {"hallenbad-altstetten"}


def test_build_admits_the_seasonal_pools_with_real_hours(tmp_path: Path) -> None:
    """seasonal-hours S3 acceptance, offline: the atomic build exits 0 and 26 pools carry schedule
    rules — the 11 that already did plus the 15 outdoor/lake/river pools whose own page publishes a
    `Zeitraum` table. Every one of them is a page the build FETCHES, so a parse regression on any
    of them is a fail-fast abort, not a quiet hole; this pins the number the live build produced.
    """
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    facilities = GoldRepository(open_db(db)).load_all()
    scheduled = {str(f.identity.facility_id) for f in facilities if any(b.rules for b in f.basins)}
    assert len(scheduled) == 26, sorted(scheduled)
    assert {"freibad-heuried", "seebad-utoquai", "maennerbad-schanzengraben"} <= scheduled
    # The zwischen-hoelzern roster URL repair is load-bearing: without it the entry's page 404s
    # and the whole build aborts, so this pool being SCHEDULED is the repair's proof.
    assert "freibad-zwischen-den-hoelzern" in scheduled
    # The two operator pages no parser understands are excluded, not failed: schedule-less, and
    # `no_source` rather than a promise (`freshness_of` deliberately did not widen its kind test).
    for excluded in ("seebad-enge", "freibad-dolder"):
        assert excluded not in scheduled
    freshness = {str(e.entry.pool_id): e.freshness for e in load_roster(open_db(db))}
    assert freshness["seebad-enge"] is ScheduleFreshness.NO_SOURCE
    assert freshness["freibad-dolder"] is ScheduleFreshness.NO_SOURCE
    assert freshness["freibad-heuried"] is ScheduleFreshness.SCRAPED
    # The two river pools that SHARE one URL can never be declared sources — and must therefore
    # never read `awaiting_scrape`, the state the `freshness_of` widening would have given them.
    for shared in ("flussbad-unterer-letten", "flussbad-unterer-letten-flussteil"):
        assert freshness[shared] is ScheduleFreshness.NO_SOURCE


def test_build_persists_the_season_and_the_last_admission_rule(tmp_path: Path) -> None:
    """The season survives the whole pipeline — scrape → compose → codec → SQLite → read — so a
    lido resolves `OUT_OF_SEASON` in October and open in July FROM THE STORE, not just from the
    saved page. And `last_admission_before`, extracted in S2 with no reader, is now folded onto the
    facility by `compose` and persisted (it was `None` on all 57 pools before this slice).
    """
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    conn = open_db(db)
    repo = GoldRepository(conn)
    calendar = load_calendar(conn)

    heuried = repo.get(reconstruct_pool_id("freibad-heuried"))
    assert heuried is not None
    basin = next(b for b in heuried.basins if b.rules)
    # 1 October is outside every window Heuried publishes → closed FOR THE SEASON, never
    # `NO_SESSIONS` ("No sessions scheduled" is a lie for a lido in autumn).
    assert resolve_basin(heuried, basin, date(2026, 10, 1), calendar) == ClosedDay(
        code=ClosureCode.OUT_OF_SEASON
    )
    # …and in season it is open with BOTH blocks, the guaranteed one and the fair-weather one.
    july = resolve_basin(heuried, basin, date(2026, 7, 15), calendar)
    assert isinstance(july, OpenDay)
    assert [(s.time.start, s.time.end, s.weather) for s in july.sessions] == [
        (time(9), time(14), Weather.ANY),
        (time(14), time(21), Weather.FAIR_ONLY),
    ]

    # `last_admission_before` is persisted for the pools whose page carries the sentence, and
    # stays `None` — never an assumed zero — for a page that does not (au-hoengg's footnote is a
    # daylight caveat with no admission rule at all).
    admissions = {
        str(f.identity.facility_id): f.last_admission_before
        for f in repo.load_all()
        if f.last_admission_before is not None
    }
    carriers = set(admissions)
    # 23 of the 26 declared sources print the sentence; the 3 that do not are `flussbad-au-hoengg`
    # (its footnote is a daylight caveat), `seebad-katzensee`, and the third-party
    # `hallenbad-altstetten` — each `None`, the honest silence, never an assumed zero.
    assert len(carriers) == 23, sorted(carriers)
    assert set(admissions.values()) == {timedelta(minutes=30)}
    assert "freibad-heuried" in carriers  # a newly admitted lido
    assert "hallenbad-city" in carriers  # …and a pool we already scraped, previously None
    assert not carriers & {"flussbad-au-hoengg", "seebad-katzensee", "hallenbad-altstetten"}


def test_atomic_build_carries_lane_bindings_so_lane_plans_still_attach(tmp_path: Path) -> None:
    # delete-curated-schedule-tier S3 crux: with the curated schedule stripped, the scraped
    # timetable wins the `basins` aspect — but `compose` CARRIES each curated basin's
    # `lane_plan_source` (the thin-crosswalk binding) alongside the scraped schedule, so the lane
    # phase still finds an owner. Without the carry, `_attach_lanes` would abort on `attached == 0`.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    repo = GoldRepository(open_db(db))

    for pool_id in ("hallenbad-city", "hallenbad-oerlikon"):
        facility = repo.get(reconstruct_pool_id(pool_id))
        assert facility is not None
        # The scraped schedule is present (a rule-bearing basin)…
        assert any(b.rules for b in facility.basins), pool_id
        # …AND the crosswalk lane binding survived the compose (a basin still declares its source)…
        assert any(b.lane_plan_source is not None for b in facility.basins), pool_id
        # …AND at least one lane plan actually attached (the URL-keyed join found its basin).
        assert any(isinstance(b.lane_plan, LanePlan) for b in facility.basins), pool_id


def test_build_atomic_pipeline_scrapes_then_aborts_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S2 acceptance: ONE `build` yields a store with schedules present (city + oerlikon, from the
    # folded scrape). Then a SINGLE injected provider failure (one pool page 503s → a declared
    # schedule source fails to fetch) aborts the whole build non-zero and leaves the PRIOR gold DB
    # CONTENT-unchanged (iterdump digest, per S4) — the mid-chain failure discards the temp store.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    repo = GoldRepository(open_db(db))
    for pool_id in ("hallenbad-city", "hallenbad-oerlikon"):
        facility = repo.get(reconstruct_pool_id(pool_id))
        assert facility is not None and any(b.rules for b in facility.basins), pool_id
    before = _db_content_digest(db)

    def fail_city_page(request: httpx.Request) -> httpx.Response | None:
        if str(request.url).endswith("city.html"):
            return httpx.Response(503, text="down")
        return None

    code = build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(fail_city_page))
    assert code == 1
    assert _db_content_digest(db) == before  # temp discarded — the live store never mutated
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "HTTP 503" in err  # the typed ProviderError cause is surfaced


def test_build_price_scrape_failure_aborts_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # admission-union S2 acceptance: the shared city tariff page 500s while every pool page still
    # fetches fine. Before this slice the build degraded to `tariffs=None` and exited 0 with all
    # 21 tariffed pools silently unpriced; now the failed price scrape is FATAL — the build exits
    # non-zero naming the typed `ProviderError`, and the prior gold DB is CONTENT-unchanged (the
    # atomic temp-swap discards the mid-chain store, per the S4 digest convention).
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    def fail_price_page(request: httpx.Request) -> httpx.Response | None:
        if "preise-abos" in str(request.url):
            return httpx.Response(500, text="down")
        return None

    code = build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(fail_price_page))
    assert code == 1
    assert _db_content_digest(db) == before  # temp discarded — the live store never mutated
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "city tariff page" in err  # the abort names WHICH declared source was lost
    assert "HTTP 500" in err  # the typed ProviderError cause is surfaced


def test_build_fans_the_shared_planschbecken_facts_out_to_thirteen_pools(tmp_path: Path) -> None:
    """sharedsource-fanout S3 acceptance, by LITERAL SQL over the built store: exactly 13 blobs
    carry `operating_season` — the 13 Planschbecken, whose one shared page states it — and all
    13 carry `admission_state: "free"`, taking the citywide free count to 17 (4 + 13)."""
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    conn = sqlite3.connect(db)
    seasoned = {
        row[0]
        for row in conn.execute(
            "select id from pool where json_extract(facility_doc,'$.operating_season') is not null"
        )
    }
    assert len(seasoned) == 13, sorted(seasoned)
    assert all(pool_id.startswith("planschbecken-") for pool_id in seasoned)
    free = {
        row[0]
        for row in conn.execute(
            "select id from pool where json_extract(facility_doc,'$.admission_state') = 'free'"
        )
    }
    assert seasoned <= free  # every Planschbecken is free — the page states it once for all 13
    assert len(free) == 17  # 4 declared-source free pools + the 13 members


def test_a_shared_page_fetch_failure_aborts_the_build_once_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3 fail-fast: the shared Planschbecken page 503s while every declared page still fetches
    fine → the whole build aborts ONCE (a single abort line — one `ScrapeFailure` for the whole
    13-member set, never thirteen), non-zero, prior gold content-unchanged."""
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    def fail_shared_page(request: httpx.Request) -> httpx.Response | None:
        if str(request.url).endswith("planschbecken.html"):
            return httpx.Response(503, text="down")
        return None

    code = build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(fail_shared_page))
    assert code == 1
    assert _db_content_digest(db) == before  # temp discarded — the live store never mutated
    err = capsys.readouterr().err
    assert err.count("schedule scrape aborted") == 1  # once, not once per member
    assert "planschbecken.html" in err
    assert "HTTP 503" in err  # the typed ProviderError cause is surfaced


def test_the_fanout_enriches_only_the_thirteen_planschbecken_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 acceptance: every pool priced/scheduled before the slice is BYTE-identical after it.
    Two builds under a frozen clock — one real, one with the shared phase stubbed empty (the
    pre-slice world) — must differ in exactly the 13 Planschbecken `facility_doc` blobs and in
    nothing else."""
    monkeypatch.setattr("swimzh.cli._now", lambda: FETCHED_AT)
    with_shared = tmp_path / "with.sqlite"
    without_shared = tmp_path / "without.sqlite"
    assert build(db_path=with_shared, data_dir=DATA_DIR, clients=_build_clients()) == 0

    monkeypatch.setattr(
        "swimzh.cli.scrape_shared_sources",
        lambda _client, _catalog, _fetched_at: ScrapeReport(extracts=(), failures=()),
    )
    assert build(db_path=without_shared, data_dir=DATA_DIR, clients=_build_clients()) == 0

    def blobs(path: Path) -> dict[str, str]:
        conn = sqlite3.connect(path)
        try:
            return dict(conn.execute("select id, facility_doc from pool").fetchall())
        finally:
            conn.close()

    with_docs, without_docs = blobs(with_shared), blobs(without_shared)
    assert set(with_docs) == set(without_docs)  # fan-out MODIFIES existing docs, adds no rows
    changed = {pool_id for pool_id in with_docs if with_docs[pool_id] != without_docs[pool_id]}
    assert len(changed) == 13, sorted(changed)
    assert all(pool_id.startswith("planschbecken-") for pool_id in changed)


def test_build_via_main(tmp_path: Path) -> None:
    # `main` threads an injected client into `build` (live runs create their own); the recorded
    # WFS snapshot lets the CLI-level build run offline.
    db = tmp_path / "gold.sqlite"
    code = main(["build", "--db", str(db), "--data", str(DATA_DIR)], clients=_build_clients())
    assert code == 0
    assert len(load_roster(open_db(db))) == 57


def test_build_unreachable_wfs_aborts_writing_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S3 acceptance: an unreachable WFS makes the build exit non-zero — the LOCAL abort at the
    # roster step. Because the roster is fetched BEFORE any DB is opened, nothing is written (the
    # general atomic-swap abort is S4). The typed ProviderError is surfaced on stderr.
    db = tmp_path / "gold.sqlite"
    code = build(db_path=db, data_dir=DATA_DIR, clients=unreachable_wfs_clients())
    assert code == 1
    assert not db.exists()  # aborted before opening the store — no partial write
    assert "roster unavailable" in capsys.readouterr().err


def test_build_failure_leaves_prior_gold_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance (build): a rebuild whose declared source (the WFS roster) fails exits non-zero
    # and leaves the PRIOR gold DB CONTENT-unchanged — asserted via a content digest, not a byte
    # hash. The atomic temp-swap guarantees no partial/half-written store replaces a good one.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    code = build(db_path=db, data_dir=DATA_DIR, clients=unreachable_wfs_clients())
    assert code == 1
    assert _db_content_digest(db) == before  # the prior store is byte-for-content identical
    assert "roster unavailable" in capsys.readouterr().err


def test_build_atomically_replaces_an_existing_store(tmp_path: Path) -> None:
    # The atomic swap works over an EXISTING target: a second successful build replaces the live
    # file in place (via temp + os.replace), leaving a complete, valid store.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    assert len(load_roster(open_db(db))) == 57


def test_build_then_scrape_gold_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = GoldRepository(open_db(db)).count()

    catalog_file = tmp_path / "catalog.json"
    entry = PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 71",
        geo=GeoPoint(lat=47.37, lon=8.53),
        url="https://example.test/city.html",
        description=None,
        phone=None,
    )
    catalog_file.write_text(catalog_json.dumps((entry,), FETCHED_AT), encoding="utf-8")

    scraped = scrape_gold(
        db_path=db, catalog_path=catalog_file, clients=_city_scrape_clients(), fetched_at=FETCHED_AT
    )
    assert scraped == 0
    # Enrichment adds/updates facilities on top of the offline build; catalog+calendar survive.
    conn = open_db(db)
    assert GoldRepository(conn).count() >= before
    assert len(load_roster(conn)) == 57
    assert load_calendar(conn).covers(datetime(2026, 6, 1, tzinfo=ZURICH).date())


def test_build_then_scrape_lanes_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0

    body = FIXTURE_PDF.read_bytes()
    clients = _lane_clients(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(db_path=db, clients=clients, fetched_at=FETCHED_AT)
    assert code == 0

    conn = open_db(db)
    # B4: the attached plan is on the flipped read path (`pool.facility_doc`, via
    # `write_schedules`) — the enrichment gap is closed, `/swim` sees the lane plan.
    city = _facility_from_read_path(db, "hallenbad-city")
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlan)
    # Roster + calendar assembled by `build` are untouched by lane enrichment.
    assert len(load_roster(conn)) == 57


def test_build_lane_phase_failure_aborts_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S2 acceptance (SECOND phase): the schedule scrape succeeds but every discovered Belegungsplan
    # PDF 503s — a mid-chain LANE-phase provider failure. The whole atomic build aborts non-zero
    # (the good schedule writes discarded too) and the prior gold DB is CONTENT-unchanged.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    before = _db_content_digest(db)

    def fail_pdfs(request: httpx.Request) -> httpx.Response | None:
        if str(request.url).endswith(".pdf"):
            return httpx.Response(503, text="down")
        return None

    code = build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(fail_pdfs))
    assert code == 1
    assert _db_content_digest(db) == before  # temp discarded — the live store never mutated
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "HTTP 503" in err


def test_main_routes_scrape_gold_scrape_lanes_and_build_catalog(tmp_path: Path) -> None:
    # `main` threads an injected client through `_dispatch` to each command (live runs make their
    # own). Build the base first, then drive the two re-layer commands + build-catalog via `main`.
    db = tmp_path / "gold.sqlite"
    assert main(["build", "--db", str(db), "--data", str(DATA_DIR)], clients=_build_clients()) == 0

    catalog = _city_catalog_file(tmp_path)
    assert (
        main(
            ["scrape-gold", "--db", str(db), "--catalog", str(catalog)],
            clients=_city_scrape_clients(),
        )
        == 0
    )
    lane_clients = _lane_clients(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    assert main(["scrape-lanes", "--db", str(db)], clients=lane_clients) == 0

    out = tmp_path / "catalog.json"
    layer_clients = clients_over(httpx.MockTransport(_layer_handler))
    assert main(["build-catalog", "--out", str(out)], clients=layer_clients) == 0
    assert out.exists()


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])


# ── S4: the provider HTTP disk cache at the composition root ────────────────────────────────────

_HOUR_S = 3600
_DAY_S = 24 * _HOUR_S
# The cache's freshness clock is INJECTED, so these tests never depend on wall time.
CACHE_NOW = datetime(2026, 7, 18, 9, 0, tzinfo=ZURICH)


class _CountingTransport(httpx.BaseTransport):
    """Records `(url, cache tier, cache TTL)` for every request that reaches the NETWORK.

    It sits *inside* the cache transport, so a cache hit never arrives here. That single position
    makes it both the tier spy (a cold build passes everything through it) and the warm-cache
    zero-network counter.
    """

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str, int]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((str(request.url), request_tier(request), request_ttl_s(request)))
        return self._inner.handle_request(request)


def _cache_clients(inner: httpx.BaseTransport, cache_dir: Path, mode: CacheMode) -> ProviderClients:
    """The production wiring, offline: ONE cache transport over `inner`, five per-source clients."""
    transport = cache_transport(inner, mode=mode, cache_dir=cache_dir, now=lambda: CACHE_NOW)
    inner_client = httpx.Client(transport=transport, follow_redirects=True)
    return ProviderClients.over(inner_client, retry=RetryPolicy(max_attempts=1))


def _url_class(url: str) -> str:
    """Classify a fetched URL by its SHAPE ALONE — never by the cache stamp it carried.

    This is what keeps the B1 guard falsifiable. A pool page is fetched by two different sources
    (the timetable scrape and the Belegungsplan discovery hop), so the URL cannot name the source
    on its own; pairing a URL-derived class with the stamp the request actually carried can.
    """
    if "TYPENAME=" in url:
        return "wfs_layer"
    if url.endswith(".pdf"):
        return "lane_pdf"
    if "preise-abos" in url:
        return "price_page"
    return "pool_page"


def test_build_stamps_each_provider_call_with_its_own_tier_and_ttl(tmp_path: Path) -> None:
    # The B1 guard. The tier TTL keys off `HttpClient.source`, so ONE client threaded through the
    # pipeline would stamp every request with the roster's 14-day tier and make the whole
    # volatility table inert. A real end-to-end build must therefore exercise all FIVE
    # (source, tier, ttl) triples. Tier alone would not do it — `price_scraper` and
    # `page_provider` share `static`/7d — hence the URL class in each triple.
    #
    # Falsifiability: collapsing to one shared client leaves only ("...", "static", 14d) entries;
    # one client per PHASE collapses price-vs-schedule (both phases are two-source), so either
    # regression changes this set.
    db = tmp_path / "gold.sqlite"
    recorder = _CountingTransport(recorded_build_transport())
    clients = _cache_clients(recorder, tmp_path / "cache", CacheMode.USE)
    assert build(db_path=db, data_dir=DATA_DIR, clients=clients) == 0

    assert {(_url_class(url), tier, ttl) for url, tier, ttl in recorder.calls} == {
        ("wfs_layer", "static", 14 * _DAY_S),  # geo_sport — the WFS roster
        ("pool_page", "snapshot", 12 * _HOUR_S),  # schedule_scraper — the timetables
        ("pool_page", "static", 7 * _DAY_S),  # page_provider — the discovery hop
        ("price_page", "static", 7 * _DAY_S),  # price_scraper — the shared tariff page
        ("lane_pdf", "snapshot", 3 * _DAY_S),  # belegungsplan — the discovered lane sheets
    }

    # …and the two pool-page sources must be stamped on the RIGHT pages. The triples above cannot
    # see a `schedules`↔`pages` swap (both fetch pool pages, so the URL class collapses them) —
    # yet a swap would give timetables a 7-day TTL and the discovery hop 12 hours. So pin the URL
    # SET behind each stamp: the timetable scrape visits exactly the DECLARED SOURCES' pages, the
    # discovery hop every roster page, and the tariff page rides the discovery hop's stamp (same
    # policy). The timetable scrape selects on the FETCHED WFS roster (`_ROSTER`, the snapshot the
    # transport replays) via `declared_sources`; discovery selects on the STORED spine. They are not
    # interchangeable — a registry.yaml kind override moves Käferberg from WFS-`indoor` to
    # stored-`thermal` — so each expectation is derived from the source its own provider reads.
    declared_pages = {url for _entry, url in declared_sources(_ROSTER)}
    # The shared-source fan-out (sharedsource-fanout S3) rides the SAME schedule client, so its
    # one registered page (the Planschbecken overview) carries the same 12h stamp.
    shared_pages = {source.url for source in shared_sources(_ROSTER)}
    all_pages = {e.entry.url for e in load_roster(open_db(db)) if e.entry.url}
    fetched: dict[tuple[str, int], set[str]] = defaultdict(set)
    for url, tier, ttl in recorder.calls:
        fetched[(tier, ttl)].add(url)

    assert fetched[("snapshot", 12 * _HOUR_S)] == declared_pages | shared_pages
    # 7 indoor/thermal + the 4 school pools (school-access-vocabulary S2) + the 15
    # outdoor/lake/river pools admitted in seasonal-hours S3; plus the ONE shared page.
    assert len(declared_pages) == 26
    assert len(shared_pages) == 1
    # NB `price_scraper` and `page_provider` share BOTH tier and TTL (static/7d — the latent
    # overlap the plan records under its S3 decisions), so this one union cannot tell them apart:
    # binding `prices` to the page-provider client would still pass. Harmless while the two
    # policies are identical; the moment their TTLs diverge, split this into two assertions.
    assert fetched[("static", 7 * _DAY_S)] == all_pages | {PRICES_URL}


def test_warm_cache_build_makes_zero_network_calls(tmp_path: Path) -> None:
    # The whole point of the plan: a second build inside every TTL fetches NOTHING. Every URL the
    # cold build touched must replay — one stubborn URL breaks the zero. (These fixtures answer
    # 200 throughout; the cache's handling of 3xx hops and 5xx is pinned by S2's transport tests.)
    cache_dir = tmp_path / "cache"
    db = tmp_path / "gold.sqlite"

    cold = _CountingTransport(recorded_build_transport())
    cold_clients = _cache_clients(cold, cache_dir, CacheMode.USE)
    assert build(db_path=db, data_dir=DATA_DIR, clients=cold_clients) == 0
    assert cold.calls, "a cold build must actually reach the network (else the zero is vacuous)"

    warm = _CountingTransport(recorded_build_transport())
    warm_clients = _cache_clients(warm, cache_dir, CacheMode.USE)
    assert build(db_path=db, data_dir=DATA_DIR, clients=warm_clients) == 0
    assert warm.calls == []


def test_refresh_mode_refetches_every_source_over_a_warm_cache(tmp_path: Path) -> None:
    # The escape hatch: `--refresh` / `SWIMZH_CACHE=refresh` must ignore a perfectly fresh entry.
    cache_dir = tmp_path / "cache"
    db = tmp_path / "gold.sqlite"
    cold = _CountingTransport(recorded_build_transport())
    cold_clients = _cache_clients(cold, cache_dir, CacheMode.USE)
    assert build(db_path=db, data_dir=DATA_DIR, clients=cold_clients) == 0

    refreshed = _CountingTransport(recorded_build_transport())
    clients = _cache_clients(refreshed, cache_dir, CacheMode.REFRESH)
    assert build(db_path=db, data_dir=DATA_DIR, clients=clients) == 0
    assert {url for url, _tier, _ttl in refreshed.calls} == {url for url, _t, _s in cold.calls}


def test_cache_off_returns_the_inner_response_untouched() -> None:
    # `OFF` is guarded against NO CACHE AT ALL, deliberately not against `USE`: on a miss the
    # cache rebuilds the response and drops the wire-framing headers (so cold and warm replay
    # identically), which is an observable — and intended — difference. `OFF` promises the
    # stronger thing: the inner response, unmodified.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, headers={"x-origin": "fixture"})

    def fetch(transport: httpx.BaseTransport) -> tuple[int, dict[str, str], bytes]:
        client = HttpClient(httpx.Client(transport=transport), retry=RetryPolicy(max_attempts=1))
        result = client.get("https://example.test/thing")
        assert isinstance(result, Ok), result
        return result.value.status_code, dict(result.value.headers), result.value.content

    raw = httpx.MockTransport(handler)
    off = cache_transport(
        httpx.MockTransport(handler), mode=CacheMode.OFF, cache_dir=Path("/nonexistent-cache")
    )
    assert fetch(off) == fetch(raw)


def test_cache_off_build_matches_an_uncached_build_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `SWIMZH_CACHE=off` is the safety valve for a live-correctness run: same store, no entries.
    # The pipeline clock is frozen so the two runs' `fetched_at` stamps cannot differ on their own.
    monkeypatch.setattr("swimzh.cli._now", lambda: FETCHED_AT)
    cache_dir = tmp_path / "cache"
    uncached = tmp_path / "uncached.sqlite"
    off_db = tmp_path / "off.sqlite"

    assert build(db_path=uncached, data_dir=DATA_DIR, clients=recorded_build_clients()) == 0
    off_clients = _cache_clients(
        _CountingTransport(recorded_build_transport()), cache_dir, CacheMode.OFF
    )
    assert build(db_path=off_db, data_dir=DATA_DIR, clients=off_clients) == 0

    assert _db_content_digest(off_db) == _db_content_digest(uncached)
    assert not list(cache_dir.rglob("*.json")), "OFF must never write an entry"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, CacheMode.USE),  # unset: the cache is on by default
        ("", CacheMode.USE),
        ("use", CacheMode.USE),
        ("on", CacheMode.USE),
        ("off", CacheMode.OFF),
        (" OFF ", CacheMode.OFF),  # case- and whitespace-insensitive
        ("refresh", CacheMode.REFRESH),
    ],
)
def test_cache_mode_reads_the_env_var(raw: str | None, expected: CacheMode) -> None:
    env = {} if raw is None else {CACHE_ENV_VAR: raw}
    assert cache_mode(env=env) is expected


def test_refresh_flag_wins_over_the_env_var() -> None:
    assert cache_mode(refresh=True, env={CACHE_ENV_VAR: "off"}) is CacheMode.REFRESH


def test_an_unknown_cache_env_value_fails_fast() -> None:
    # A typo must not silently mean "use the cache" — that is how a live-correctness run ends up
    # served from disk without saying so.
    with pytest.raises(CacheModeError, match=CACHE_ENV_VAR):
        cache_mode(env={CACHE_ENV_VAR: "of"})


def test_every_network_command_accepts_the_refresh_flag(tmp_path: Path) -> None:
    # The flag is parsed on each network subcommand (it drives the LIVE client construction, which
    # an injected-clients run bypasses), so `--refresh` must never be an "unrecognized arguments".
    db = tmp_path / "gold.sqlite"
    assert (
        main(
            ["build", "--refresh", "--db", str(db), "--data", str(DATA_DIR)],
            clients=_build_clients(),
        )
        == 0
    )
    lane_clients = _lane_clients(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    assert main(["scrape-lanes", "--refresh", "--db", str(db)], clients=lane_clients) == 0
    catalog = _city_catalog_file(tmp_path)
    assert (
        main(
            ["scrape-gold", "--refresh", "--db", str(db), "--catalog", str(catalog)],
            clients=_city_scrape_clients(),
        )
        == 0
    )
    out = tmp_path / "catalog.json"
    layer_clients = clients_over(httpx.MockTransport(_layer_handler))
    assert main(["build-catalog", "--refresh", "--out", str(out)], clients=layer_clients) == 0


def test_the_cache_directory_is_git_ignored() -> None:
    # The cache is a per-checkout dev accelerator. A committed one would be a second, silent
    # source of truth — and a huge diff.
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert str(DEFAULT_CACHE_ROOT).startswith(".cache/")
    assert "/.cache/" in [line.strip() for line in gitignore.splitlines()]


def test_live_transport_mode_follows_the_refresh_flag_and_the_env(tmp_path: Path) -> None:
    # THE JOIN the escape hatch depends on: flag + env -> CacheMode -> the transport the live run
    # actually uses. Wired inline in `main` it would sit under the live pragma, where a `--refresh`
    # that quietly degraded to `USE` (or a `SWIMZH_CACHE=off` that stopped disabling anything)
    # would keep the whole suite green. `httpx.HTTPTransport()` opens no connection, so building
    # the real transport here costs nothing and needs no cassette.
    def mode_for(**kwargs: object) -> CacheMode:
        transport = live_transport(cache_dir=tmp_path / "cache", **kwargs)  # type: ignore[arg-type]
        assert isinstance(transport, DiskCacheTransport)
        return transport.mode

    assert mode_for(env={}) is CacheMode.USE  # unset: cached by default
    assert mode_for(env={CACHE_ENV_VAR: "off"}) is CacheMode.OFF
    assert mode_for(env={CACHE_ENV_VAR: "refresh"}) is CacheMode.REFRESH
    assert mode_for(refresh=True, env={}) is CacheMode.REFRESH  # the flag, on its own
    assert mode_for(refresh=True, env={CACHE_ENV_VAR: "off"}) is CacheMode.REFRESH  # flag wins


def test_live_timeout_bounds_connect_without_shortening_the_read_budget() -> None:
    # Asserted on the FACTORY's return value, not on the client: the client is built under
    # `# pragma: no cover - live`, so a budget that silently reverted to a flat 30s would be
    # invisible to the suite. connect is short so a host that accepts TCP and then says nothing
    # (retried 3x, both causes being `retriable()`) cannot eat minutes of a build; read/write/pool
    # stay at the existing budget so no currently-passing slow fetch starts failing.
    # Literals on purpose: these are the *budget itself*, so re-deriving them from the module's
    # constants would let a widened budget pass silently. Changing them is a decision, not a typo.
    budget = live_timeout()

    assert isinstance(budget, httpx.Timeout)
    assert budget.connect == 5.0
    assert budget.read == 30.0
    assert budget.write == 30.0
    assert budget.pool == 30.0


def test_main_hands_the_refresh_flag_to_the_live_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # …and `main` must actually forward the parsed flag. The factory is stubbed to record the
    # argument and then abort (a `ValueError` is the one way out of the live path that never
    # touches the network), so this pins the last hop without a cassette.
    seen: list[bool] = []

    def stub(*, refresh: bool) -> DiskCacheTransport:
        seen.append(refresh)
        raise CacheModeError("stopped before the network")

    monkeypatch.setattr("swimzh.cli.live_transport", stub)
    argv = ["build", "--db", str(tmp_path / "gold.sqlite"), "--data", str(DATA_DIR)]
    assert main([*argv, "--refresh"]) == 2
    assert main(argv) == 2
    assert seen == [True, False]


def test_a_typod_cache_env_var_stops_the_run_with_a_one_line_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Fail-fast config, end to end: with no injected clients `main` resolves the live cache mode
    # BEFORE opening a client, so a typo aborts without a traceback and without a request.
    monkeypatch.setenv(CACHE_ENV_VAR, "of")
    argv = ["build", "--db", str(tmp_path / "gold.sqlite"), "--data", str(DATA_DIR)]
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert CACHE_ENV_VAR in err


def test_a_non_cache_failure_in_the_live_wiring_is_not_reported_as_a_cache_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The `except` in `_dispatch_live` is narrowed to `CacheModeError` on purpose: a plain
    # `ValueError` out of the live wiring (e.g. `httpx.HTTPTransport()` rejecting a bad SSL env)
    # is NOT a cache-config problem and must not be dressed up as one. It propagates.
    def stub(*, refresh: bool) -> DiskCacheTransport:
        raise ValueError("bad SSL configuration")

    monkeypatch.setattr("swimzh.cli.live_transport", stub)
    with pytest.raises(ValueError, match="bad SSL configuration"):
        main(["build", "--db", str(tmp_path / "gold.sqlite"), "--data", str(DATA_DIR)])
