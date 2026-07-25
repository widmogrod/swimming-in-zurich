"""The CLI commands build an offline gold store and enrich it via scrape (MockTransport)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.build.compose import ScrapedAspects, compose
from swimzh.cli import build, build_catalog_file, main, scrape_gold, scrape_lanes
from swimzh.core.errors import SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import BasinId, Facility, PoolKind, reconstruct_pool_id
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.providers.curated import load_dataset
from swimzh.providers.geo_sport import POOL_LAYERS
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_roster,
    open_db,
    write_schedules,
)


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


def _city_scrape_client() -> HttpClient:
    body = FIXTURE_HTML.read_bytes()
    inner = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body))
    )
    return HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))


def test_scrape_gold_composes_onto_built_store(tmp_path: Path) -> None:
    # scrape-gold now layers onto an already-built spine: it resolves the scraped WFS name to a
    # canonical id by lookup and composes, rather than minting a second (long-slug) row.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0

    code = scrape_gold(
        db_path=db,
        catalog_path=_city_catalog_file(tmp_path),
        client=_city_scrape_client(),
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
    # red on that mutation, closing the enrichment gap for good.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    altstetten = reconstruct_pool_id("hallenbad-altstetten")
    # Uncurated before the scrape: Slice F gives it a SCHEDULE-LESS prose blob, so it may be
    # present on the read path but carries no schedule rule yet.
    before = GoldRepository(open_db(db)).get(altstetten)
    assert before is None or not any(b.rules for b in before.basins)

    code = scrape_gold(
        db_path=db,
        catalog_path=_scraped_only_catalog_file(tmp_path),
        client=_city_scrape_client(),
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
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    conn = open_db(db)

    curated_city = GoldRepository(conn).get(reconstruct_pool_id("hallenbad-city"))
    assert curated_city is not None
    assert curated_city.prices is not None  # real curated City carries a price
    assert any(b.rules for b in curated_city.basins)  # ...and a curated schedule
    priceless_city = replace(curated_city, prices=None)

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
        prices=scraped_price,
        fetched_at=FETCHED_AT,
    )
    composition = compose((priceless_city,), ((reconstruct_pool_id("hallenbad-city"), scraped),))
    write_schedules(conn, tuple((f.identity.facility_id, f) for f in composition.facilities))

    served = GoldRepository(open_db(db)).get(reconstruct_pool_id("hallenbad-city"))
    assert served is not None
    assert served.basins == curated_city.basins  # curated schedule preserved through the seam
    assert served.prices == scraped_price  # scraped price gained, now on `pool.facility_doc`


def test_scrape_gold_requires_a_built_store(tmp_path: Path) -> None:
    # Without a prior `build` the spine is absent, so there is no id namespace to resolve into —
    # scrape-gold refuses rather than opening a second door to a gold row.
    code = scrape_gold(
        db_path=tmp_path / "absent.sqlite",
        catalog_path=_city_catalog_file(tmp_path),
        client=_city_scrape_client(),
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
    assert build(db_path=db, data_dir=DATA_DIR) == 0
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
        db_path=db, catalog_path=catalog_file, client=_city_scrape_client(), fetched_at=FETCHED_AT
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
    # name is reported to stderr, and the exit code is non-zero so the miss stays visible.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    altstetten = reconstruct_pool_id("hallenbad-altstetten")
    # Scraped-only pool: before the scrape it carries at most a SCHEDULE-LESS Slice-F prose blob
    # (no rule), so no scraped schedule is on the read path yet.
    before = GoldRepository(open_db(db)).get(altstetten)
    assert before is None or not any(b.rules for b in before.basins)

    code = scrape_gold(
        db_path=db,
        catalog_path=_partial_catalog_file(tmp_path),
        client=_city_scrape_client(),
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
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    before = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}

    ambiguous = SchemaMismatch(source="reconcile", detail="ambiguous basin hint: 'Twin Bad'")
    monkeypatch.setattr("swimzh.cli.resolve_all", lambda _extracts, _crosswalk: Err(ambiguous))

    code = scrape_gold(
        db_path=db,
        catalog_path=_city_catalog_file(tmp_path),
        client=_city_scrape_client(),
        fetched_at=FETCHED_AT,
    )
    assert code == 1
    assert "ambiguous" in capsys.readouterr().err.lower()
    # Nothing written: the ambiguous batch aborts whole, leaving the store as `build` left it.
    after = {f.identity.facility_id for f in GoldRepository(open_db(db)).load_all()}
    assert after == before


def test_build_and_scrape_gold_share_one_id_namespace(tmp_path: Path) -> None:
    # The acceptance: build and scrape-gold write into the SAME id namespace. Every facility row
    # id (the /swim read path) is a real pool PK — no long-vs-short split-brain.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    assert (
        scrape_gold(
            db_path=db,
            catalog_path=_city_catalog_file(tmp_path),
            client=_city_scrape_client(),
            fetched_at=FETCHED_AT,
        )
        == 0
    )

    conn = open_db(db)
    pool_ids = {row[0] for row in conn.execute("SELECT id FROM pool").fetchall()}
    facility_ids = {str(f.identity.facility_id) for f in GoldRepository(conn).load_all()}
    assert facility_ids  # non-empty
    assert facility_ids <= pool_ids  # every scheduled facility id is a canonical pool PK


def _pdf_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def test_scrape_lanes_attaches_plan_to_curated_basin(tmp_path: Path) -> None:
    # `scrape-lanes` reads the curated facilities (from `pool.facility_doc`), needs the offline
    # `build` spine present, then writes the attached plan back through `write_schedules`.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0

    body = FIXTURE_PDF.read_bytes()
    client = _pdf_client(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(db_path=db, client=client, fetched_at=FETCHED_AT)
    assert code == 0

    # B4 closes the B2→B4 enrichment gap: the lane plan is now on the read path
    # (`pool.facility_doc`), a scraped aspect curated City lacked, visible where `/swim` reads.
    city = _facility_from_read_path(db, "hallenbad-city")
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlan)
    assert lap.lane_plan.lane_count == 6
    assert lap.lane_plan.fetched_at == FETCHED_AT


def test_scrape_lanes_missing_db_is_error(tmp_path: Path) -> None:
    client = _pdf_client(lambda _r: httpx.Response(200, content=b""))
    code = scrape_lanes(db_path=tmp_path / "absent.sqlite", client=client, fetched_at=FETCHED_AT)
    assert code == 1


def test_scrape_lanes_reports_when_no_pdf_parses(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0  # spine present, so the 503 is the cause
    client = _pdf_client(lambda _r: httpx.Response(503, text="down"))
    code = scrape_lanes(db_path=db, client=client, fetched_at=FETCHED_AT)
    assert code == 1


_OERLIKON_COMBINED_PDF = _FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf"


def test_scrape_lanes_prints_unbound_and_unavailable_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S3 acceptance: the honest operational audit. The combined Oerlikon sheet attaches
    # Sprungbecken (its section token) and surfaces the still-uncurated Nichtschwimmer section as
    # a per-URL `unbound` line (source_url + header + reason); every other declared source is
    # 503'd, so each records a per-basin `unavailable` line carrying its typed cause — NOT a bare
    # `unmatched` list.
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    oerlikon = _facility_from_read_path(db, "hallenbad-oerlikon")
    sprung = next(b for b in oerlikon.basins if b.basin_id == BasinId("oerlikon-sprungbecken"))
    assert sprung.lane_plan_source is not None
    combined_url = sprung.lane_plan_source.url
    combined_pdf = _OERLIKON_COMBINED_PDF.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == combined_url:
            return httpx.Response(200, content=combined_pdf)
        return httpx.Response(503, text="down")

    code = scrape_lanes(db_path=db, client=_pdf_client(handler), fetched_at=FETCHED_AT)
    assert code == 0  # Sprungbecken attached, so the run succeeds

    err = capsys.readouterr().err
    # (a) per-URL unbound: the uncurated Nichtschwimmer section — url + header + reason.
    assert "unbound" in err
    assert combined_url in err
    assert "Nichtschwimmer" in err
    # (b) per-basin unavailable: each 503'd declared source with its typed cause (HTTP 503).
    assert "unavailable" in err
    assert "city-50m" in err
    assert "HTTP 503" in err


def test_scrape_lanes_prints_unmatched_section_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S3 audit-completeness: a curated basin declares a `section` token, its stacked sheet parses,
    # but the token matches NO parsed header (here the single-basin Schwimmerbecken sheet is served
    # at the combined URL — "Sprungbecken" never appears). The basin is left None, but the silent
    # drop is surfaced as an `unmatched section` audit line (a parser-header-regression alarm).
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
    oerlikon = _facility_from_read_path(db, "hallenbad-oerlikon")
    combined_url = next(
        b.lane_plan_source.url
        for b in oerlikon.basins
        if b.basin_id == BasinId("oerlikon-sprungbecken") and b.lane_plan_source is not None
    )
    city = _facility_from_read_path(db, "hallenbad-city")
    city_url = next(
        b.lane_plan_source.url
        for b in city.basins
        if b.basin_id == BasinId("city-50m") and b.lane_plan_source is not None
    )
    # The single-basin Schwimmerbecken sheet's header never contains the "Sprungbecken" token.
    wrong_sheet = (_FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes()
    city_sheet = FIXTURE_PDF.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == combined_url:
            return httpx.Response(200, content=wrong_sheet)
        if str(request.url) == city_url:
            return httpx.Response(200, content=city_sheet)
        return httpx.Response(503, text="down")

    code = scrape_lanes(db_path=db, client=_pdf_client(handler), fetched_at=FETCHED_AT)
    assert code == 0  # City attached, so the run succeeds

    err = capsys.readouterr().err
    assert "unmatched section" in err
    assert "oerlikon-sprungbecken" in err
    assert "sprungbecken" in err


def test_scrape_lanes_empty_store_is_error(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # schema only, no facilities
    client = _pdf_client(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    code = scrape_lanes(db_path=db, client=client, fetched_at=FETCHED_AT)
    assert code == 1


def test_build_produces_complete_offline_store(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    code = build(db_path=db, data_dir=DATA_DIR)
    assert code == 0
    assert db.exists()

    conn = open_db(db)
    # The pool spine holds every known pool (committed data/catalog.json).
    assert len(load_roster(conn)) == 57
    # Calendar table covers the current planning horizon.
    assert load_calendar(conn).covers(datetime(2026, 1, 1, tzinfo=ZURICH).date())
    # The curated facilities land on the read path (`pool.facility_doc`) — no network needed.
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    facilities = GoldRepository(conn).load_all()
    # The curated *scheduled* facilities land on the read path — matched against the dataset's
    # scheduled facilities (the lane-plan-only pools in the dataset are schedule-less, so they
    # are excluded from this scheduled-parity check on both sides).
    scheduled = {f.identity.facility_id for f in facilities if any(b.rules for b in f.basins)}
    scheduled_dataset = {
        f.identity.facility_id for f in dataset.value.facilities if any(b.rules for b in f.basins)
    }
    assert scheduled == scheduled_dataset
    # …plus schedule-less pools (Slice-F prose + lane-plan-only) — a superset of the scheduled set.
    stored = {f.identity.facility_id for f in facilities}
    assert stored > scheduled


def test_build_via_main_offline(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    code = main(["build", "--db", str(db), "--data", str(DATA_DIR)])
    assert code == 0
    assert len(load_roster(open_db(db))) == 57


def test_build_missing_catalog_is_error(tmp_path: Path) -> None:
    # A data dir with calendar/registry/pools but no catalog.json.
    data = tmp_path / "data"
    (data / "pools").mkdir(parents=True)
    (data / "calendar").mkdir()
    (data / "registry.yaml").write_bytes((DATA_DIR / "registry.yaml").read_bytes())
    (data / "calendar" / "zurich.yaml").write_bytes(
        (DATA_DIR / "calendar" / "zurich.yaml").read_bytes()
    )
    for pool in (DATA_DIR / "pools").glob("*.yaml"):
        (data / "pools" / pool.name).write_bytes(pool.read_bytes())

    code = build(db_path=tmp_path / "gold.sqlite", data_dir=data)
    assert code == 1


def test_build_then_scrape_gold_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0
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
    body = FIXTURE_HTML.read_bytes()
    inner = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body))
    )
    client = HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))

    scraped = scrape_gold(
        db_path=db, catalog_path=catalog_file, client=client, fetched_at=FETCHED_AT
    )
    assert scraped == 0
    # Enrichment adds/updates facilities on top of the offline build; catalog+calendar survive.
    conn = open_db(db)
    assert GoldRepository(conn).count() >= before
    assert len(load_roster(conn)) == 57
    assert load_calendar(conn).covers(datetime(2026, 6, 1, tzinfo=ZURICH).date())


def test_build_then_scrape_lanes_enriches(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR) == 0

    body = FIXTURE_PDF.read_bytes()
    client = _pdf_client(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(db_path=db, client=client, fetched_at=FETCHED_AT)
    assert code == 0

    conn = open_db(db)
    # B4: the attached plan is on the flipped read path (`pool.facility_doc`, via
    # `write_schedules`) — the enrichment gap is closed, `/swim` sees the lane plan.
    city = _facility_from_read_path(db, "hallenbad-city")
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlan)
    # Roster + calendar assembled by `build` are untouched by lane enrichment.
    assert len(load_roster(conn)) == 57


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])
