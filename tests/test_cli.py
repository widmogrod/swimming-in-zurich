"""The CLI commands build a gold store (roster sourced from the WFS via recorded HTTP) and
enrich it via scrape (all HTTP through MockTransport / recorded snapshots — never live)."""

from __future__ import annotations

import shutil
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.build.compose import ScrapedAspects, compose
from swimzh.build.reconcile import resolve_all
from swimzh.cli import (
    CACHE_ENV_VAR,
    EXIT_BUILT_STALE,
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
from swimzh.etl.scrape import ScrapeReport, declared_sources, shared_sources
from swimzh.etl.silver_codec import decode_roster, encode_roster
from swimzh.providers.geo_sport import POOL_LAYERS
from swimzh.providers.price_scraper import PRICES_URL
from swimzh.storage import catalog_json
from swimzh.storage.lake import Lake, SilverStatus
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_calendar,
    load_roster,
    load_source_freshness,
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


def _with_price_fixture(fallback_body: bytes) -> ProviderClients:
    """Clients serving the committed tariff fixture at the price page, `fallback_body` elsewhere.

    Since admission-union S2 a failed `scrape_prices` is FATAL to the schedule phase (`scrape-gold`
    is `build` with that phase forced), so every scrape double must serve a parseable price
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


# ── The re-layer is `build` on one cadence (one-pipeline) ───────────────────────────────────────
#
# `scrape-gold`/`scrape-lanes` used to be a SECOND pipeline: they seeded a temp copy of the live
# store, read `data/catalog.json` as their roster and composed onto the previous gold — and, once,
# onto their own output, so a re-layer refreshed nothing and still exited 0
# (`docs/2026-08-10-scrape-gold-recompose-defect.md`). Now each is `build` with its own sources
# FORCED through the refresh policy (`force_sources`) and every other source reused from the lake.
# The tests below drive the wrappers over ONE lake: a build at `_T0`, the re-layer at `_T1` — one
# hour later, inside every silver TTL, so the only network a re-layer may touch is what it forces.

_T0 = FETCHED_AT
_T1 = FETCHED_AT + timedelta(hours=1)


def _lake_build(tmp_path: Path) -> tuple[Path, Lake]:
    """A store built from the recorded transport at `_T0`, and the lake that build filled."""
    db = tmp_path / "gold.sqlite"
    lake = Lake(tmp_path / "lake")
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients(), lake=lake, now=_T0) == 0
    return db, lake


def _freshness(db: Path) -> dict[str, tuple[str, datetime]]:
    """Per source: (`status`, `fetched_at`) as the store's `source_freshness` rows record them."""
    conn = open_db(db)
    try:
        return {
            row.header.source: (row.header.status.value, row.header.fetched_at)
            for row in load_source_freshness(conn)
        }
    finally:
        conn.close()


def _seed_roster(lake: Lake, entries: tuple[PoolCatalogEntry, ...]) -> None:
    """Overwrite the lake's roster silver at `_T0` — the one way to hand a re-layer a roster the
    WFS never published, now that no command reads a catalog file."""
    lake.write("roster", encode_roster(entries, _T0), fetched_at=_T0)


def _mutated_override() -> Callable[[httpx.Request], httpx.Response | None]:
    """The recorded transport with TWO sources mutated: City's page hours (`6–22 Uhr` → `7–21 Uhr`)
    and the shared tariff's adult rate (`Fr. 8.–` → `Fr. 13.–`).

    Re-serving the SAME fixture would prove nothing — an unchanged store is also what correct
    idempotence looks like (that case is `test_a_relayer_is_idempotent_over_unchanged_sources`).
    The mutation is what makes "did the refresh reach the store?" assertable, and it is deliberately
    one BASIN aspect plus one NON-basin aspect: the defect report's option 4 warns that a
    basins-only guard passes while prices stay frozen.
    """
    city = FIXTURE_HTML.read_bytes().replace("6–22 Uhr".encode(), "7–21 Uhr".encode())
    assert "7–21 Uhr".encode() in city, "the hours mutation must actually apply to the fixture"
    tariff = (_FIXTURES / "preise_abos.html").read_bytes()
    tariff = tariff.replace("Fr. 8.–".encode(), "Fr. 13.–".encode(), 1)
    assert "Fr. 13.–".encode() in tariff, "the price mutation must actually apply to the fixture"

    def override(request: httpx.Request) -> httpx.Response | None:
        url = str(request.url)
        if url.endswith("city.html"):
            return httpx.Response(200, content=city)
        if "preise-abos" in url:
            return httpx.Response(200, content=tariff)
        return None  # every other source keeps its unmutated fixture

    return override


def _mutated_relayer_clients() -> ProviderClients:
    return recorded_build_clients(_mutated_override())


def _city_hours(db: Path) -> set[tuple[time, time]]:
    """Every opening window City's stored schedule states, across all its basins."""
    facility = _facility_from_read_path(db, "hallenbad-city")
    return {(rule.time.start, rule.time.end) for b in facility.basins for rule in b.rules}


def _city_adult_price(db: Path) -> Decimal:
    """City's stored adult admission — a NON-basin aspect, folded through `_ASPECTS`."""
    admission = _facility_from_read_path(db, "hallenbad-city").admission
    assert isinstance(admission, Tariff), admission
    return next(e.amount_chf for e in admission.table.entries if e.category is PriceCategory.ADULT)


def _attached_lane_plans(db: Path) -> dict[tuple[str, str], LanePlan]:
    """Every stored `(facility_id, basin_id)` → the lane PLAN it carries.

    The plan itself, not just the key: a carry that put the WRONG plan on the right basin — the
    mis-attach the URL-keyed join exists to prevent — passes a set-of-keys assertion.
    """
    return {
        (str(f.identity.facility_id), str(b.basin_id)): b.lane_plan
        for f in GoldRepository(open_db(db)).load_all()
        for b in f.basins
        if isinstance(b.lane_plan, LanePlan)
    }


def _facility_blobs(db: Path) -> dict[str, str]:
    """The raw stored `pool.facility_doc` per pool — byte equality, so "was this row rewritten?"
    cannot be answered by a field-by-field comparison that happens to miss the field that moved."""
    return {
        str(row[0]): str(row[1])
        for row in open_db(db).execute("SELECT id, facility_doc FROM pool").fetchall()
    }


_EPOCH = date(2000, 1, 1)


def _timeless(facility: Facility) -> Facility:
    """`facility` with every timestamp a re-layer legitimately advances flattened away.

    A re-run against unchanged sources SHOULD restamp when it fetched; it must not change anything
    else. Flattening the timestamps is what turns "did it converge?" into an equality.
    """
    admission = facility.admission
    if isinstance(admission, Tariff):
        admission = replace(admission, table=replace(admission.table, valid_as_of=_EPOCH))
    return replace(
        facility,
        provenance=replace(facility.provenance, valid_as_of=_EPOCH, fetched_at=None),
        admission=admission,
    )


def test_a_relayer_refreshes_the_stored_schedule(tmp_path: Path) -> None:
    """S1 AC1 — the defect's own reproduction, inverted: a re-layer against an already-built store
    whose page now states different hours CHANGES the stored rules. The forced `schedules` silver
    is refetched inside its TTL, where a plain `build` would have reused it."""
    db, lake = _lake_build(tmp_path)
    assert _city_hours(db) == {(time(6), time(22))}  # what the unmutated fixture states

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=_mutated_relayer_clients(), lake=lake, now=_T1
    )
    assert code == 0
    assert _city_hours(db) == {(time(7), time(21))}  # pre-fix: still 06:00–22:00


def test_a_relayer_refreshes_a_non_basin_aspect_too(tmp_path: Path) -> None:
    """S1 AC2 — the same re-layer moves a NON-basin aspect: a mutated tariff changes the stored
    price. A basins-only fix passes AC1 while every price, notice and closure stays frozen."""
    db, lake = _lake_build(tmp_path)
    assert _city_adult_price(db) == Decimal("8.00")

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=_mutated_relayer_clients(), lake=lake, now=_T1
    )
    assert code == 0
    assert _city_adult_price(db) == Decimal("13.00")  # pre-fix: still 8.00


def _unmutated_relayer(db: Path, lake: Lake, now: datetime = _T1) -> int:
    """A re-layer over the SAME fixtures the build used — nothing upstream changed."""
    return scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(), lake=lake, now=now
    )


def test_a_relayer_is_idempotent_over_unchanged_sources(tmp_path: Path) -> None:
    """S1 AC3 / invariant S-1 — running the re-layer twice over unchanged sources leaves the store
    content-identical. The store is rebuilt from silver each time, never from its own previous
    output, so a re-layer converges instead of accreting."""
    db, lake = _lake_build(tmp_path)

    assert _unmutated_relayer(db, lake) == 0
    once = _db_content_digest(db)
    assert _unmutated_relayer(db, lake) == 0
    assert _db_content_digest(db) == once


def test_a_relayer_over_unchanged_sources_changes_nothing_but_provenance(tmp_path: Path) -> None:
    """The property re-layer-vs-re-layer cannot see: compared against the `build` that PRECEDED it,
    a re-layer over unchanged sources restamps when it fetched and changes NOTHING else — the pools
    it scraped come back with the same facts, and no row is added or dropped.

    The whole store is REBUILT here (a re-layer is `build`), so the 31 blobs the schedule phase
    does not reach are byte-identical only because the curated tier is a pure function of the
    reused roster silver + `data/` — which is the property this asserts.
    """
    db, lake = _lake_build(tmp_path)
    before_blobs = _facility_blobs(db)
    before = {str(f.identity.facility_id): f for f in GoldRepository(open_db(db)).load_all()}

    assert _unmutated_relayer(db, lake) == 0

    after_blobs = _facility_blobs(db)
    assert set(after_blobs) == set(before_blobs)  # no row added, none dropped
    rewritten = {
        pool_id for pool_id in before_blobs if before_blobs[pool_id] != after_blobs[pool_id]
    }
    # 26, derived — never a bare number (the habit `etl/scrape.py` sets for its own `== 26`):
    # the phase resolves 39 extracts (26 declared sources + the 13-member Planschbecken fan-out)
    # and writes exactly those 39. The 13 Planschbecken fold WITHOUT a scraped timetable, so
    # `_merge_basins` never reports a scraped win and `_fold` never adopts scraped provenance —
    # their blobs come back byte-identical. 39 − 13 = 26 rows actually change, and every one of
    # them changes only by the scrape's timestamps (asserted below).
    assert len(rewritten) == 26, sorted(rewritten)
    assert not any(pool_id.startswith("planschbecken-") for pool_id in rewritten)
    assert not rewritten & {"freibad-dolder", "seebad-enge", "schulschwimmanlage-hardau"}

    after = {str(f.identity.facility_id): f for f in GoldRepository(open_db(db)).load_all()}
    assert {k: _timeless(v) for k, v in after.items()} == {
        k: _timeless(v) for k, v in before.items()
    }


@pytest.mark.parametrize(
    "pool_id",
    [
        # An operator page no parser understands (`_UNPARSEABLE_OPERATOR_PAGES`).
        "freibad-dolder",
        "seebad-enge",
        # No page of its own: one of the 14 entries on the generic `hallenbaeder.html`.
        "schulschwimmanlage-hardau",
    ],
)
def test_a_relayer_never_rewrites_a_pool_it_did_not_scrape(tmp_path: Path, pool_id: str) -> None:
    """A pool the roster NAMES but the schedule phase does not reach keeps a byte-identical blob
    across a re-layer whose scrape DID change — its blob is the curated tier's, and the curated
    tier is rebuilt from the same reused roster silver + `data/` every time.

    The old test drove this with a catalog FILE that disagreed with the store's roster (a pool
    named but unscrapeable). Under one pipeline the roster the re-layer scrapes IS the roster its
    spine is built from, so that split-brain has no second roster to come from any more; what is
    left to pin is the honest set of pools no scrape reaches — derived from the predicates, never
    hard-coded.
    """
    db, lake = _lake_build(tmp_path)
    roster = lake.read("roster")
    assert roster is not None
    entries = decode_roster(roster.payload)
    reached = {source.entry.pool_id for source in declared_sources(entries)} | {
        member.pool_id for shared in shared_sources(entries) for member in shared.members
    }
    assert pool_id not in reached
    before = _facility_blobs(db)[pool_id]

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=_mutated_relayer_clients(), lake=lake, now=_T1
    )
    assert code == 0
    assert _facility_blobs(db)[pool_id] == before


def test_a_relayer_keeps_the_lane_plans_a_previous_run_attached(tmp_path: Path) -> None:
    """S1 / invariant S-2 — a schedule re-layer must not trade silent staleness for silent
    DELETION of the lane plans a previous run attached. Now: the `lane_plans` silver is REUSED,
    not refetched — proved by serving every Belegungsplan URL a 503: had `scrape-gold` asked for
    one, the run would have kept-stale (exit 2) instead of exiting 0 with fresh lane rows."""
    db, lake = _lake_build(tmp_path)
    before = _attached_lane_plans(db)
    assert before, "the offline build must attach lane plans for this to mean anything"
    mutated = _mutated_override()

    def override(request: httpx.Request) -> httpx.Response | None:
        if str(request.url).endswith(".pdf"):
            return httpx.Response(503, text="down")
        return mutated(request)

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(override), lake=lake, now=_T1
    )
    assert code == 0
    assert _attached_lane_plans(db) == before
    rows = _freshness(db)
    assert rows["lane_plans"] == ("fresh", _T0)  # reused: last time's fetch, still fresh
    assert rows["schedules"] == ("fresh", _T1)  # forced: this run's fetch


def _data_dir_with_repointed_city_binding(tmp_path: Path) -> Path:
    """A copy of `data/` in which City's basin points at a DIFFERENT Belegungsplan sheet."""
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR, data_dir)
    city_yaml = data_dir / "pools" / "city.yaml"
    text = city_yaml.read_text(encoding="utf-8")
    assert "city-schwimmerbecken.pdf" in text
    city_yaml.write_text(
        text.replace("city-schwimmerbecken.pdf", "city-schwimmerbecken-2027.pdf"), encoding="utf-8"
    )
    return data_dir


def test_a_relayer_drops_a_lane_plan_whose_binding_was_repointed(tmp_path: Path) -> None:
    """The ONE path on which a re-layer legitimately removes stored content — asserted so it stays
    a decision rather than becoming a surprise.

    The lane join is URL-keyed (`etl/silver.attach_lane_plans`): the reused `lane_plans` silver
    holds the sheet parsed from the OLD url, so a basin whose `data/` binding now names a different
    sheet gets no plan — never a stale plan wearing a fresh binding, the mis-attach
    `docs/concepts/lane-plan-url-binding.md` exists to prevent. It is repaired by the next
    `scrape-lanes`, which refetches discovery and aborts loudly if the page does not advertise the
    new url. Every OTHER pool's plan, whose binding did not move, survives — a targeted drop, never
    a sweep.
    """
    db, lake = _lake_build(tmp_path)
    before = _attached_lane_plans(db)
    city_basins = {key for key in before if key[0] == "hallenbad-city"}
    assert city_basins, "City must start with an attached plan for this to mean anything"

    code = scrape_gold(
        db_path=db,
        data_dir=_data_dir_with_repointed_city_binding(tmp_path),
        clients=recorded_build_clients(),
        lake=lake,
        now=_T1,
    )
    assert code == 0

    after = _attached_lane_plans(db)
    assert not {
        key for key in after if key[0] == "hallenbad-city"
    }  # dropped, awaiting scrape-lanes
    assert after == {key: plan for key, plan in before.items() if key not in city_basins}


def test_a_relayer_aborts_when_the_curated_inputs_are_unusable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The curated tier is an INPUT to the re-layer, so it has its own fail-fast: unreadable
    `data/` aborts before the temp store is even opened, naming the typed cause. This is what makes
    "the live store is untouched by construction" true rather than merely likely."""
    db, lake = _lake_build(tmp_path)
    before = _db_content_digest(db)

    code = scrape_gold(
        db_path=db,
        data_dir=tmp_path / "no-such-data",
        clients=_city_scrape_clients(),
        lake=lake,
        now=_T1,
    )
    assert code == 1
    assert _db_content_digest(db) == before
    assert "build failed" in capsys.readouterr().err


def test_build_aborts_when_the_curated_inputs_are_unusable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same fail-fast on the build side: the curated assemble runs BEFORE the temp DB exists,
    so an unreadable `data/` writes nothing at all."""
    db = tmp_path / "gold.sqlite"
    code = build(db_path=db, data_dir=tmp_path / "no-such-data", clients=_build_clients())
    assert code == 1
    assert not db.exists()  # nothing was opened, let alone swapped in
    assert "build failed" in capsys.readouterr().err


def test_build_rejects_an_unknown_force_source(tmp_path: Path) -> None:
    """A `force_sources` name outside `SILVER_SOURCES` is a caller bug, not a silent no-force."""
    with pytest.raises(ValueError, match="force_sources"):
        build(
            db_path=tmp_path / "gold.sqlite",
            data_dir=DATA_DIR,
            clients=_build_clients(),
            force_sources=frozenset({"schedule"}),
        )


def _urlless_roster() -> tuple[PoolCatalogEntry, ...]:
    """A roster whose single entry carries NO page URL, so `declared_sources` selects nothing and
    the phase scrapes zero extracts."""
    return (
        PoolCatalogEntry(
            pool_id="hallenbad-city",
            name="Hallenbad City",
            kind=PoolKind.INDOOR,
            address="Sihlstrasse 71",
            geo=GeoPoint(lat=47.37, lon=8.53),
            url=None,
            description=None,
            phone=None,
        ),
    )


def test_a_relayer_that_scrapes_nothing_leaves_the_store_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S1 AC4 / invariant S-2 — an EMPTY scrape is a `SchemaMismatch`, which the refresh policy
    never papers over with a kept silver: the build aborts, the temp is discarded and the live
    store keeps everything the previous run wrote. (Its sibling, a FAILED declared source, is
    `test_scrape_gold_declared_source_parse_failure_aborts_content_unchanged`.)"""
    db, lake = _lake_build(tmp_path)
    before = _db_content_digest(db)
    _seed_roster(lake, _urlless_roster())  # reused at `_T1`: nothing on it is scrapeable

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=_city_scrape_clients(), lake=lake, now=_T1
    )
    assert code == 1
    assert _db_content_digest(db) == before  # nothing deleted, nothing rewritten
    assert "no schedules could be scraped" in capsys.readouterr().err


@pytest.mark.parametrize(
    "relayer", [scrape_gold, scrape_lanes], ids=["scrape-gold", "scrape-lanes"]
)
def test_a_relayer_over_an_empty_lake_fetches_the_roster_and_builds(
    tmp_path: Path, relayer: Callable[..., int]
) -> None:
    """No prior store, no prior silver: a re-layer is a first-run `build`. The roster is fetched
    from the WFS (the lake has none to reuse) and the store comes out complete. There is no
    "build it first" any more — the wrapper IS the build."""
    db = tmp_path / "gold.sqlite"
    lake = Lake(tmp_path / "lake")
    code = relayer(db_path=db, data_dir=DATA_DIR, clients=_build_clients(), lake=lake, now=_T0)
    assert code == 0
    roster = lake.read("roster")
    assert roster is not None and roster.header.fetched_at == _T0
    assert all(row == ("fresh", _T0) for row in _freshness(db).values())
    assert GoldRepository(open_db(db)).count() == 57


def test_scrape_gold_reuses_the_lake_roster_without_the_wfs(tmp_path: Path) -> None:
    """The roster comes from the lake's `roster.json`, not from a catalog file and not from the
    WFS: with the WFS answering 500 to everything, scrape-gold still exits 0 — not even a stale
    keep, because the roster was never asked for — and the spine + calendar it built are whole."""
    db, lake = _lake_build(tmp_path)

    def wfs_down(request: httpx.Request) -> httpx.Response | None:
        if request.url.params.get("TYPENAME"):
            return httpx.Response(500, text="<html>Internal Server Error</html>")
        return None

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(wfs_down), lake=lake, now=_T1
    )
    assert code == 0
    rows = _freshness(db)
    assert rows["roster"] == ("fresh", _T0)  # reused
    assert rows["prices"] == ("fresh", _T1)  # forced
    assert rows["schedules"] == ("fresh", _T1)  # forced
    assert rows["lane_plans"] == ("fresh", _T0)  # reused
    conn = open_db(db)
    assert len(load_roster(conn)) == 57
    assert load_calendar(conn).covers(datetime(2026, 6, 1, tzinfo=ZURICH).date())


def test_scrape_merge_puts_curated_schedule_and_scraped_price_on_read_path(tmp_path: Path) -> None:
    # B4 acceptance: the schedule phase writes the composed facility through `write_schedules`, so
    # the per-aspect merge (curated schedule kept + a scraped price the curated data lacked) is
    # visible on the read path (`pool.facility_doc` via `GoldRepository`), where `/swim` reads.
    # The recorded scrape yields no scraped price for City (its own curated price already wins),
    # so this drives the same compose→`write_schedules` seam the phase runs internally, over the
    # real curated City with its price stripped so the scraped price is the one that fills the gap.
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


def test_scrape_gold_unreconcilable_name_is_reported_not_silently_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D2 partial success: a scraped name in no alias is a benign miss — NAMED on stderr and
    signalled by exit 1, the resolved pools still written, nothing attached to a guessed pool.

    Under one pipeline every scraped `Name` is a roster name and every roster name is an alias of
    the spine built from that same roster, so the miss cannot arise from data any more (the old
    test manufactured it with a catalog file the store's spine had never seen). It is reached
    through the `resolve_all` seam — the real resolver plus one extra unresolved label — exactly
    as the ambiguous case always was; the branch stays because `ReconcileOutcome` carries it.
    """
    db, lake = _lake_build(tmp_path)
    before = set(_facility_blobs(db))

    def with_a_miss(extracts: Any, crosswalk: Any) -> Any:
        outcome = resolve_all(extracts, crosswalk)
        assert isinstance(outcome, Ok)
        return Ok(
            replace(outcome.value, unresolved=(*outcome.value.unresolved, "Hallenbad Nonexistent"))
        )

    monkeypatch.setattr("swimzh.cli.resolve_all", with_a_miss)
    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=_mutated_relayer_clients(), lake=lake, now=_T1
    )
    assert code == 1  # the unmatched name is signalled by a non-zero exit
    assert "Hallenbad Nonexistent" in capsys.readouterr().err  # named, not swallowed
    assert _city_hours(db) == {(time(7), time(21))}  # the resolved pools WERE written
    assert set(_facility_blobs(db)) == before  # no row for a guessed pool


def test_scrape_gold_ambiguous_reconcile_aborts_writing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Ambiguous stays structurally fatal. Scrape extracts are `Name`-only, so they can NEVER be
    # ambiguous by construction (D1's discovery) — a faithful CLI-level ambiguous scrape cannot
    # exist. So we drive the `case Err` branch directly: a `resolve_all` that returns the typed
    # ambiguous `Err` a seeded ambiguous crosswalk would produce (see
    # `test_resolve_all_is_fatal_on_ambiguous_ref_naming_the_offender`). The store must be left
    # untouched — never a silent wrong-pool write — and so must the schedules silver.
    db, lake = _lake_build(tmp_path)
    before = _db_content_digest(db)

    ambiguous = SchemaMismatch(source="reconcile", detail="ambiguous basin hint: 'Twin Bad'")
    monkeypatch.setattr("swimzh.cli.resolve_all", lambda _extracts, _crosswalk: Err(ambiguous))

    code = scrape_gold(
        db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(), lake=lake, now=_T1
    )
    assert code == 1
    assert "ambiguous" in capsys.readouterr().err.lower()
    assert _db_content_digest(db) == before  # the ambiguous batch aborts whole
    schedules = lake.read("schedules")
    assert schedules is not None and schedules.header.fetched_at == _T0  # silver not rewritten


def test_scrape_gold_declared_source_parse_failure_aborts_content_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance (scrape-gold): a declared source whose page cannot be parsed is NOT
    # skipped-and-green — the whole run ABORTS non-zero carrying the typed cause, and the prior
    # gold DB is CONTENT-unchanged (content digest, not byte hash). A parse error is schema drift,
    # so the refresh policy does NOT let the kept schedules silver stand in (unlike a 503).
    db, lake = _lake_build(tmp_path)
    before = _db_content_digest(db)

    # Every pool page fetches 200 but has no timetable, so `parse_schedule` fails -> a declared
    # source failure with a typed ParseError cause. The price page is served its REAL fixture
    # (`_with_price_fixture`) so the abort under test stays the pool page's, not the tariff
    # page's own fatal case.
    clients = _with_price_fixture(b"<html>no table</html>")
    code = scrape_gold(db_path=db, data_dir=DATA_DIR, clients=clients, lake=lake, now=_T1)
    assert code == 1
    assert _db_content_digest(db) == before  # nothing written — the live store is unchanged
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "parse error" in err.lower()  # the typed ProviderError cause is surfaced


def test_build_and_scrape_gold_share_one_id_namespace(tmp_path: Path) -> None:
    # The acceptance: build and scrape-gold write into the SAME id namespace. Every facility row
    # id (the /swim read path) is a real pool PK — no long-vs-short split-brain.
    db, lake = _lake_build(tmp_path)
    assert _unmutated_relayer(db, lake) == 0

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
    """`scrape-lanes` forces ONLY `lane_plans`: discovery over the stored pool pages, then the
    discovered PDFs, written back through `write_schedules`. `_lane_clients` routes nothing but
    pool pages and PDFs — no WFS layer, no tariff page — so this passing proves every other
    source came out of the lake untouched."""
    db, lake = _lake_build(tmp_path)

    body = FIXTURE_PDF.read_bytes()
    clients = _lane_clients(lambda _r: httpx.Response(200, content=body))
    code = scrape_lanes(db_path=db, data_dir=DATA_DIR, clients=clients, lake=lake, now=_T1)
    assert code == 0

    # B4 closes the B2→B4 enrichment gap: the lane plan is on the read path
    # (`pool.facility_doc`), a scraped aspect curated City lacked, visible where `/swim` reads.
    city = _facility_from_read_path(db, "hallenbad-city")
    lap = next(b for b in city.basins if b.basin_id == BasinId("city-50m"))
    assert isinstance(lap.lane_plan, LanePlan)
    assert lap.lane_plan.lane_count == 6
    assert lap.lane_plan.fetched_at == _T1
    rows = _freshness(db)
    assert rows["lane_plans"] == ("fresh", _T1)  # forced
    assert rows["schedules"] == ("fresh", _T0)  # reused
    assert rows["roster"] == ("fresh", _T0)  # reused


def test_scrape_lanes_over_a_down_lane_source_keeps_last_times_plans_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pages discover their Belegungsplan links, but every discovered PDF 503s. Before the lake
    that aborted the re-layer; under the refresh policy a 503 is TRANSIENT, so with a `lane_plans`
    silver younger than `max_stale` the run KEEPS it, marks it stale, rebuilds the store on it and
    exits 2 — the same plans as before, and the store says they are stale. (A first run, with no
    silver to keep, still aborts: `test_build_lane_phase_failure_aborts_content_unchanged`.)"""
    db, lake = _lake_build(tmp_path)
    before = _attached_lane_plans(db)

    clients = _lane_clients(lambda _r: httpx.Response(503, text="down"))
    code = scrape_lanes(db_path=db, data_dir=DATA_DIR, clients=clients, lake=lake, now=_T1)
    assert code == EXIT_BUILT_STALE
    assert _attached_lane_plans(db) == before  # last time's plans, unchanged
    assert _freshness(db)["lane_plans"] == ("stale", _T0)
    err = capsys.readouterr().err
    assert "HTTP 503" in err  # the typed ProviderError cause is surfaced
    assert "STALE" in err


_OERLIKON_COMBINED_PDF = _FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf"


def test_scrape_lanes_prints_unbound_audit_for_uncurated_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 audit: with every discovered source fetching fine (no miss -> no abort), the combined
    # Oerlikon sheet attaches Sprungbecken (its section token) and surfaces the still-uncurated
    # Nichtschwimmer section as a per-URL `unbound` line (an undiscovered-basin extra, non-fatal —
    # NOT a missing declared fact). The run succeeds.
    db, lake = _lake_build(tmp_path)
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

    code = scrape_lanes(
        db_path=db, data_dir=DATA_DIR, clients=_lane_clients(handler), lake=lake, now=_T1
    )
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
    db, lake = _lake_build(tmp_path)
    oerlikon = _facility_from_read_path(db, "hallenbad-oerlikon")
    combined_url = next(
        b.lane_plan_source.url
        for b in oerlikon.basins
        if b.basin_id == BasinId("oerlikon-sprungbecken") and b.lane_plan_source is not None
    )
    # The single-basin Schwimmerbecken sheet's header never contains the "Sprungbecken" token.
    wrong_sheet = (_FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes()
    city_sheet = FIXTURE_PDF.read_bytes()

    # Every OTHER discovered source is served a valid single-basin plan (it binds by URL); only
    # the combined URL gets the wrong sheet, whose header lacks the declared "Sprungbecken" token.
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == combined_url:
            return httpx.Response(200, content=wrong_sheet)
        return httpx.Response(200, content=city_sheet)

    code = scrape_lanes(
        db_path=db, data_dir=DATA_DIR, clients=_lane_clients(handler), lake=lake, now=_T1
    )
    assert code == 0  # City attached, so the run succeeds

    err = capsys.readouterr().err
    assert "unmatched section" in err
    assert "oerlikon-sprungbecken" in err
    assert "sprungbecken" in err


def test_scrape_lanes_authored_source_not_advertised_aborts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S4 acceptance (S2-surfaced case): an authored `lane_plan_source.url` its pool page fails to
    # advertise (`authored − discovered` non-empty — here every page returns an EMPTY body, so no
    # link is discovered) is a HARD abort, never a silent drop: a `SchemaMismatch` is not
    # transient, so the kept lane silver may NOT stand in. The prior gold DB is content-unchanged,
    # the lane silver is not even marked stale, and the abort carries the typed cause.
    db, lake = _lake_build(tmp_path)
    before = _db_content_digest(db)

    # Pool pages fetch 200 but advertise NO Belegungsplan links (so no PDF is ever fetched).
    clients = clients_over(
        httpx.MockTransport(lambda _r: httpx.Response(200, content=b"<html></html>"))
    )
    code = scrape_lanes(db_path=db, data_dir=DATA_DIR, clients=clients, lake=lake, now=_T1)
    assert code == 1
    assert _db_content_digest(db) == before  # never mutated — the authored source is stranded loud
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "not advertised" in err  # typed SchemaMismatch: the page no longer lists the URL
    lanes = lake.read("lane_plans")
    assert lanes is not None and lanes.header.status is SilverStatus.FRESH


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
    # phase still finds an owner. Without the carry, `_write_lane_plans` would abort on
    # `attached == 0`.
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
    code = main(
        ["build", "--db", str(db), "--data", str(DATA_DIR), "--lake", str(tmp_path / "lake")],
        clients=_build_clients(),
    )
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
    # own). Build the base first, then drive the two cadence wrappers over the SAME lake (each is
    # `build`, so it takes `build`'s flags — and no longer a `--catalog`), then build-catalog.
    db = tmp_path / "gold.sqlite"
    store = ["--db", str(db), "--data", str(DATA_DIR), "--lake", str(tmp_path / "lake")]
    assert main(["build", *store], clients=_build_clients()) == 0
    assert main(["scrape-gold", *store], clients=recorded_build_clients()) == 0
    lane_clients = _lane_clients(lambda _r: httpx.Response(200, content=FIXTURE_PDF.read_bytes()))
    assert main(["scrape-lanes", *store], clients=lane_clients) == 0
    with pytest.raises(SystemExit):  # the catalog-file roster double is gone
        main(["scrape-gold", *store, "--catalog", str(DATA_DIR / "catalog.json")])

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
    # On the pipeline commands it ALSO forces every silver source, so the two wrappers need the
    # full recorded transport here — `--refresh` on `scrape-lanes` refetches the roster too.
    db = tmp_path / "gold.sqlite"
    store = ["--db", str(db), "--data", str(DATA_DIR), "--lake", str(tmp_path / "lake")]
    assert main(["build", "--refresh", *store], clients=_build_clients()) == 0
    assert main(["scrape-lanes", "--refresh", *store], clients=_build_clients()) == 0
    assert main(["scrape-gold", "--refresh", *store], clients=_build_clients()) == 0
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


def test_the_offline_build_doubles_lane_attachment_is_pinned_as_an_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """board-order-and-defects S4 AC2, the half that pins THE DOUBLE — labelled as such.

    `wfs_snapshot._LANE_PDF` serves ONE sheet (`city-schwimmerbecken.pdf`) for every `.pdf` URL.
    The lane join is URL-keyed, so all five SINGLE-basin sources bind — to City's plan, not their
    own. The one STACKED source does not: `oerlikon-sprungbecken` declares
    `section: "sprungbecken"` and `_bind_stacked` routes by containment against the sheet's
    parsed header, which here reads `Hallenbad City Schwimmerbecken`. So this build attaches SIX
    and reports exactly one unmatched section.

    **None of these numbers describe production.** A build over the real per-pool sheets attaches
    seven with `unmatched_sections` empty — pinned, honestly, in
    `tests/etl/test_lane_attachment_pin.py`. Read that module for what the join really does; this
    one exists so the double cannot drift silently underneath every suite that consumes it. The
    coincidence that both totals are six is exactly that: here Sprungbecken is lost and
    Bungertwies binds a stand-in; there Sprungbecken binds and Bungertwies has no committed sheet.
    """
    db = tmp_path / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=_build_clients()) == 0
    captured = capsys.readouterr()

    # The audit line the CLI prints. A substring match, but over the WHOLE rendered count, so the
    # number cannot drift: "attached 7 lane plan(s)" does not contain this string.
    assert "attached 6 lane plan(s)" in captured.out

    # Exactly one unmatched section, and it is NAMED — never an unasserted range.
    unmatched = [line for line in captured.err.splitlines() if line.startswith("unmatched section")]
    assert len(unmatched) == 1
    assert "oerlikon-sprungbecken" in unmatched[0]
    assert "'sprungbecken' matched no parsed header" in unmatched[0]

    # …and the store agrees with the audit line: six basins carry a plan, and the plan-less one is
    # the basin the unmatched section named. Asserted against the store because the printed count
    # and the persisted store are two different things, and only the store is what `/swim` serves.
    facilities = GoldRepository(open_db(db)).load_all()
    with_plan = {
        (str(f.identity.facility_id), str(b.basin_id))
        for f in facilities
        for b in f.basins
        if isinstance(b.lane_plan, LanePlan)
    }
    assert len(with_plan) == 6
    assert ("hallenbad-oerlikon", "oerlikon-sprungbecken") not in with_plan
    assert ("hallenbad-oerlikon", "oerlikon-50m") in with_plan
