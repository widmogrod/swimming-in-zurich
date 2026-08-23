"""The iOS export is a PROJECTION of `find_swim_options`, proved date by date — and the file
it writes is one an iOS app bundle can actually read.

Two families of test live here, and both are load-bearing:

* **Parity.** For every pool on every date of the horizon, the baked `session` / `day` /
  `day_notice` / `day_warning` rows must equal what the live domain query returns today. The
  comparison is against the DOMAIN (`SwimOption` / `FacilityStatus` / `QueryResult`), not the
  pydantic DTOs, and the expected rows are rebuilt here from the domain objects rather than by
  calling the export's own row builders — a projection compared against itself proves nothing.
* **Bundle readability.** A WAL-mode SQLite file in a read-only directory *opens* fine and fails
  on the FIRST PREPARE with `SQLITE_CANTOPEN`. So a test that only opens the file would pass
  against a database no device could read: these tests assert the header bytes (not WAL), the
  absence of `-wal`/`-shm` sidecars, `integrity_check`, a populated `sqlite_stat1` — and then
  prepare and STEP a query against the file, `mode=ro`, from a read-only directory.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import shutil
import sqlite3
import stat
from collections import Counter
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from swimzh.cli import build, main
from swimzh.core.errors import ProviderSpecific
from swimzh.core.result import Err, Ok
from swimzh.domain.access import PublicSwim, eligibility
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.lockers import LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    Feature,
    FeatureKind,
    OperatingSeason,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import QueryResult, SwimQuery, find_swim_options
from swimzh.domain.rentals import Priced, RentalItem
from swimzh.domain.schedule import (
    AnnualWindow,
    ClosureRange,
    DatePrecision,
    MonthDay,
    ScheduleRule,
    TimeRange,
    Weather,
    Weekday,
)
from swimzh.etl.ios_export import (
    SCHEMA_VERSION,
    STATUS_FIELD_TO_COLUMN,
    TABLE_COLUMNS_WITH_META,
    ExportReport,
    _finalize,
    _integrity_error,
    _not_wal,
    export_ios,
    horizon,
    render_warning,
)
from swimzh.storage import codec
from swimzh.storage.rows import PoolRow, PoolSpine
from swimzh.storage.sqlite_repo import (
    GoldRepository,
    load_alias_rows,
    load_calendar,
    load_roster,
    open_db,
    write_calendar,
    write_pools,
    write_schedules,
)
from tests.pipeline_clients import recorded_build_clients

_ZURICH = ZoneInfo("Europe/Zurich")
_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _REPO_ROOT / "data"

#: A FIXED build date, so the horizon, the row counts and the golden fixture are deterministic.
TODAY = date(2026, 8, 23)
#: A short horizon for the tests that only care about the file's shape; the parity sweep and the
#: horizon/size assertions use the real 400.
FULL_DAYS = 400

#: The size ceiling from S1 acceptance 6 — asserted, with the actual size printed, so growth is
#: visible at every run instead of surfacing when a bundle stops fitting.
MAX_BYTES = 8 * 1024 * 1024


@pytest.fixture(scope="module")
def gold_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A COMPLETE gold store from one OFFLINE atomic `build` — the same fixture-replayed pipeline
    the web suite serves from, so the export is proved against real scraped schedules."""
    db = tmp_path_factory.mktemp("gold") / "gold.sqlite"
    assert build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients()) == 0
    return db


@dataclasses.dataclass(frozen=True, slots=True)
class _Export:
    path: Path
    report: ExportReport
    facilities: tuple[Facility, ...]
    roster: tuple[RosterEntry, ...]
    calendar: ZurichCalendar
    aliases: tuple[tuple[str, str], ...]


@pytest.fixture(scope="module")
def exported(gold_db: Path, tmp_path_factory: pytest.TempPathFactory) -> _Export:
    out = tmp_path_factory.mktemp("ios") / "ios.sqlite"
    with sqlite3.connect(gold_db) as conn:
        result = export_ios(conn, out, today=TODAY, days=FULL_DAYS)
        assert isinstance(result, Ok), result
        return _Export(
            path=out,
            report=result.value,
            facilities=GoldRepository(conn).load_all(),
            roster=load_roster(conn),
            calendar=load_calendar(conn),
            aliases=load_alias_rows(conn),
        )


@pytest.fixture(scope="module")
def store(exported: _Export) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(exported.path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(conn.execute(sql))


# --- Acceptance 1: the command, offline, writing a STRICT store ---------------------------


def test_the_cli_command_exports_a_strict_store_and_exits_zero(
    gold_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "ios.sqlite"
    assert main(["export-ios", "--db", str(gold_db), "--out", str(out)]) == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "ios export written to" in printed
    # E2's reseed signal is on the line at EVERY build, not only when someone goes looking.
    assert "outside calendar coverage" in printed

    with sqlite3.connect(out) as conn:
        schemas = dict(
            conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
        )
    # `sqlite_stat1` is SQLite's own (never STRICT); every table WE declare must be.
    ours = {name: sql for name, sql in schemas.items() if not name.startswith("sqlite_")}
    assert set(ours) == set(TABLE_COLUMNS_WITH_META)
    assert all(sql.rstrip().endswith("STRICT") for sql in ours.values()), ours


def test_a_missing_gold_store_is_a_one_line_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["export-ios", "--db", str(tmp_path / "nope.sqlite"), "--out", str(tmp_path / "ios.sqlite")]
    )
    assert code == 1
    assert "run `swimzh build` first" in capsys.readouterr().err


def test_a_refused_horizon_is_reported_as_a_failure_by_the_command(
    gold_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--days 0` drives the one path the happy case never does: the export returns an `Err`, and
    the command has to turn that value into exit 1 plus a one-line stderr — never a traceback."""
    out = tmp_path / "ios.sqlite"
    code = main(["export-ios", "--db", str(gold_db), "--out", str(out), "--days", "0"])
    assert code == 1
    assert "ios export failed" in capsys.readouterr().err
    assert not out.exists()


def test_the_declared_columns_match_the_stores_own_schema(store: sqlite3.Connection) -> None:
    """The DDL and the row builders are two lists of columns; this is what keeps them one."""
    for table, columns in TABLE_COLUMNS_WITH_META.items():
        actual = tuple(r[1] for r in store.execute(f"PRAGMA table_info({table})"))
        assert actual == columns, table


def test_the_export_module_imports_nothing_that_could_reach_the_network() -> None:
    """Acceptance 1's "no network", made decidable: gold is the only input, so the module may not
    import httpx, a provider, or the HTTP client at all."""
    source = (_REPO_ROOT / "src" / "swimzh" / "etl" / "ios_export.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    banned = ("httpx", "swimzh.providers", "swimzh.core.http", "urllib", "socket")
    assert not [m for m in imported if m.startswith(banned)], sorted(imported)


# --- Acceptance 1b: the store is bundle-readable -------------------------------------------


def test_the_store_is_not_in_wal_mode(exported: _Export) -> None:
    """Header bytes 18-19: `0101` for delete/truncate/memory/off, `0202` ONLY for wal. The
    pragma's own return value is not evidence — `PRAGMA journal_mode` can fail silently and
    hand back the previous mode."""
    header = exported.path.read_bytes()[18:20]
    assert header != b"\x02\x02", "exported store is WAL — no iOS bundle could read it"
    assert header == b"\x01\x01"


def test_no_wal_or_shm_sidecar_is_shipped_beside_the_store(exported: _Export) -> None:
    for suffix in ("-wal", "-shm"):
        assert not Path(f"{exported.path}{suffix}").exists()


def test_integrity_check_passes_and_analyze_populated_sqlite_stat1(
    store: sqlite3.Connection,
) -> None:
    assert store.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # ANALYZE ran, so the DEVICE's very first query plans against real statistics.
    assert store.execute("SELECT count(*) FROM sqlite_stat1").fetchone()[0] > 0


def test_the_store_prepares_and_steps_a_query_from_a_read_only_directory(
    exported: _Export, tmp_path: Path
) -> None:
    """The finding that would have shipped a broken app: a WAL file OPENS fine here and fails at
    the first prepare. So this test does not stop at `connect` — it prepares and steps."""
    bundle = tmp_path / "Bundle"
    bundle.mkdir()
    copied = bundle / "ios.sqlite"
    shutil.copyfile(exported.path, copied)
    copied.chmod(0o444)
    bundle.chmod(0o555)
    try:
        conn = sqlite3.connect(f"file:{copied}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT count(*) FROM session").fetchone()
        finally:
            conn.close()
        assert row[0] > 0
    finally:
        bundle.chmod(stat.S_IRWXU)
        copied.chmod(0o644)


def test_the_wal_guard_actually_detects_a_wal_file(tmp_path: Path) -> None:
    """Pin the guard itself against a real WAL database — otherwise the byte assertion above
    only proves that the guard never fires."""
    wal = tmp_path / "wal.sqlite"
    conn = sqlite3.connect(wal, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.close()
    assert wal.read_bytes()[18:20] == b"\x02\x02"
    assert isinstance(_not_wal(wal), ProviderSpecific)


def test_a_failed_bundle_check_leaves_the_previous_export_untouched(
    gold_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the export goes through `atomic_swap`: a store that fails its final
    checks must never replace a good one."""
    out = tmp_path / "ios.sqlite"
    with sqlite3.connect(gold_db) as conn:
        assert isinstance(export_ios(conn, out, today=TODAY, days=2), Ok)
        good = out.read_bytes()
        monkeypatch.setattr(
            "swimzh.etl.ios_export._not_wal",
            lambda path: ProviderSpecific(provider="ios_export", detail="forced"),
        )
        assert isinstance(export_ios(conn, out, today=TODAY, days=2), Err)
    assert out.read_bytes() == good
    assert not list(tmp_path.glob(".ios.sqlite.*"))  # the temp is discarded, not left behind


def test_the_finalize_guards_are_not_decoration() -> None:
    """Both halves of the finalize check fire on the case they exist for."""
    assert _integrity_error(("ok",)) is None
    assert isinstance(_integrity_error(None), ProviderSpecific)
    assert isinstance(_integrity_error(("malformed database",)), ProviderSpecific)
    # A store with no tables gives ANALYZE nothing to write: the missing-statistics guard fires.
    empty = sqlite3.connect(":memory:", isolation_level=None)
    try:
        assert isinstance(_finalize(empty), ProviderSpecific)
    finally:
        empty.close()


def test_a_gold_store_without_a_calendar_is_a_typed_error_not_an_exception(
    tmp_path: Path,
) -> None:
    conn = open_db(tmp_path / "empty.sqlite")
    try:
        result = export_ios(conn, tmp_path / "ios.sqlite", today=TODAY, days=1)
    finally:
        conn.close()
    assert isinstance(result, Err)
    assert not (tmp_path / "ios.sqlite").exists()


def test_an_empty_horizon_is_refused_as_a_value(gold_db: Path, tmp_path: Path) -> None:
    with sqlite3.connect(gold_db) as conn:
        result = export_ios(conn, tmp_path / "ios.sqlite", today=TODAY, days=0)
    assert isinstance(result, Err)
    assert not (tmp_path / "ios.sqlite").exists()


# --- Acceptance 2: the parity sweep ---------------------------------------------------------


def _expected_session(option: Any, day: date) -> tuple[Any, ...]:
    """One `SwimOption` as the row the export must carry — rebuilt from the DOMAIN object, not
    from the export's own builders."""
    session = option.session
    return (
        str(option.facility_id),
        day.isoformat(),
        str(option.basin_id),
        option.basin_name,
        float(option.basin_length_m) if option.basin_length_m is not None else None,
        option.lanes,
        session.time.start.strftime("%H:%M"),
        session.time.end.strftime("%H:%M"),
        type(session.access).__name__,
        json.dumps(dataclasses.asdict(session.access), sort_keys=True),
        session.weather.value,
    )


def _expected_day(status: Any, day: date) -> tuple[Any, ...]:
    """One `FacilityStatus` as its `day` row — THROUGH the fixed domain→column mapping, so the
    rename (`code`→`detail_code`, `closure`→`closure_code`, `params`→`detail_params`) is asserted
    rather than assumed."""
    domain = {
        "code": status.code.value,
        "closure": status.closure.value if status.closure is not None else None,
        "params": json.dumps(dict(status.params), sort_keys=True),
    }
    columns = {STATUS_FIELD_TO_COLUMN[field]: value for field, value in domain.items()}
    return (
        str(status.facility_id),
        day.isoformat(),
        status.status,
        columns["detail_code"],
        columns["closure_code"],
        columns["detail_params"],
    )


def _actual_session(row: sqlite3.Row) -> tuple[Any, ...]:
    values = tuple(row)
    # Re-canonicalise the JSON column so the comparison is on VALUES, never on formatting.
    return (*values[:9], json.dumps(json.loads(values[9]), sort_keys=True), values[10])


def _actual_day(row: sqlite3.Row) -> tuple[Any, ...]:
    values = tuple(row)
    return (*values[:5], json.dumps(json.loads(values[5]), sort_keys=True))


def _sweep(exported: _Export) -> Iterator[tuple[date, QueryResult]]:
    """The oracle is `find_swim_options` ITSELF, called exactly as the plan's acceptance 2 words
    it — not the export's own `resolve_day` wrapper. Sharing that wrapper would co-mutate the
    query-construction step with the thing under test, so the sweep would keep passing if the
    export ever asked the domain a different question than the one acceptance 2 names."""
    for day in horizon(TODAY, FULL_DAYS):
        query = SwimQuery(
            person=Person(gender=None, age=None),
            at=datetime.combine(day, time(12, 0), tzinfo=_ZURICH),
            near=None,
            radius_km=None,
        )
        yield day, find_swim_options(query, exported.facilities, exported.calendar, exported.roster)


def test_every_baked_session_and_day_row_equals_the_live_query(
    exported: _Export, store: sqlite3.Connection
) -> None:
    """The whole point of the export: for every pool on every date of the horizon, the baked
    answer IS `find_swim_options`'s answer. Zero diffs, unsampled — the sweep costs under a
    second, so there is no excuse for sampling it."""
    want_sessions: Counter[tuple[Any, ...]] = Counter()
    want_days: Counter[tuple[Any, ...]] = Counter()
    want_notices: Counter[tuple[Any, ...]] = Counter()
    for day, result in _sweep(exported):
        want_sessions.update(_expected_session(o, day) for o in result.options)
        want_days.update(_expected_day(s, day) for s in result.statuses)
        want_notices.update((str(n.facility_id), day.isoformat(), n.text) for n in result.notices)

    # `SELECT *` is column-ORDER-dependent, which is exactly what
    # `test_the_declared_columns_match_the_stores_own_schema` pins.
    got_sessions = Counter(_actual_session(r) for r in _rows(store, "SELECT * FROM session"))
    got_days = Counter(_actual_day(r) for r in _rows(store, "SELECT * FROM day"))
    got_notices = Counter(
        tuple(r) for r in _rows(store, "SELECT pool_id, date, text FROM day_notice")
    )

    assert got_sessions == want_sessions
    assert got_days == want_days
    assert got_notices == want_notices
    # The sweep is only evidence if it actually swept something.
    assert sum(want_sessions.values()) == exported.report.sessions > 0
    assert sum(want_days.values()) == exported.report.day_rows > 0


def test_a_pool_day_with_sessions_carries_no_day_row(store: sqlite3.Connection) -> None:
    """The `day` table is the no-options half of the answer; a pool that is open that day is
    represented by its sessions, never also by a status."""
    overlap = store.execute(
        "SELECT count(*) FROM day JOIN session USING (pool_id, date)"
    ).fetchone()[0]
    assert overlap == 0


def test_every_baked_warning_renders_back_to_the_live_warning(
    exported: _Export, store: sqlite3.Connection
) -> None:
    """`day_warning` stores a CODE + params so the client can say it in its own language;
    rendering it must reproduce `QueryResult.warnings` verbatim, in order."""
    baked: dict[str, list[str]] = {}
    for row in _rows(store, "SELECT date, code, params FROM day_warning ORDER BY rowid"):
        baked.setdefault(row["date"], []).append(
            render_warning(row["code"], json.loads(row["params"]))
        )
    for day, result in _sweep(exported):
        assert tuple(baked.get(day.isoformat(), ())) == result.warnings, day
    seen_codes = {r["code"] for r in _rows(store, "SELECT code FROM day_warning")}
    # Both codes really occur in the horizon — otherwise the renderer's second arm is untested.
    assert seen_codes == {"calendar_coverage", "holiday_hours_unverified"}


# --- Acceptance 3: lane plans, basins, seasons ---------------------------------------------


def test_every_basin_with_a_lane_plan_has_seven_lane_days_carrying_its_coverage(
    exported: _Export, store: sqlite3.Connection
) -> None:
    """`unresolved_lanes` + `confidence` are LOAD-BEARING, not decoration: the client derives
    `partial` from them, and `partial` is a rendered field on both lane badges."""
    planned = {
        str(basin.basin_id): basin.lane_plan
        for facility in exported.facilities
        for basin in facility.basins
        if isinstance(basin.lane_plan, LanePlan)
    }
    assert planned, "the fixture store carries no lane plan at all — nothing is being proved"
    rows = _rows(store, "SELECT * FROM lane_day")
    assert {r["basin_id"] for r in rows} == set(planned)
    for basin_id, plan in planned.items():
        mine = [r for r in rows if r["basin_id"] == basin_id]
        assert sorted(r["weekday"] for r in mine) == [int(w) for w in Weekday]
        for row in mine:
            assert row["confidence"] == plan.coverage.confidence.value
            assert json.loads(row["unresolved_lanes"]) == sorted(plan.coverage.unresolved_lanes)
            assert row["lane_count"] == plan.lane_count
            assert len(json.loads(row["strips"])) == plan.lane_count


def test_pool_basin_carries_all_twelve_basin_fields(store: sqlite3.Connection) -> None:
    """The 12 `BasinOut` fields, including the `physical_source` honesty caveat — a basin that
    lost it would render hand-verified and prose-scraped physicals identically."""
    assert TABLE_COLUMNS_WITH_META["pool_basin"] == (
        "pool_id",
        "basin_id",
        "name",
        "kind",
        "length_m",
        "width_m",
        "lanes",
        "nominal_temp_c",
        "measured_temp_c",
        "diving_platforms_m",
        "physical_source",
        "lane_plan_url",
    )
    sources = {r["physical_source"] for r in _rows(store, "SELECT physical_source FROM pool_basin")}
    assert sources <= {"curated", "parsed_prose"}


def test_operating_season_is_set_for_exactly_the_pools_that_declare_one(
    exported: _Export, store: sqlite3.Connection
) -> None:
    declared = {
        str(f.identity.facility_id) for f in exported.facilities if f.operating_season is not None
    }
    baked = {
        r["pool_id"]
        for r in _rows(store, "SELECT pool_id, operating_season FROM pool")
        if r["operating_season"] is not None
    }
    assert baked == declared
    assert len(declared) > 0
    season = json.loads(
        store.execute(
            "SELECT operating_season FROM pool WHERE operating_season IS NOT NULL"
        ).fetchone()[0]
    )
    assert set(season) == {
        "start_month",
        "end_month",
        "precision",
        "weather",
        "start_day",
        "end_day",
    }


def test_the_pool_table_covers_the_whole_roster_with_its_freshness(
    exported: _Export, store: sqlite3.Connection
) -> None:
    rows = {r["pool_id"]: r for r in _rows(store, "SELECT * FROM pool")}
    assert set(rows) == {r.entry.pool_id for r in exported.roster}
    for entry in exported.roster:
        assert rows[entry.entry.pool_id]["freshness"] == entry.freshness.value
    assert {r["admission_state"] for r in rows.values()} <= {"free", "tariff", "unknown"}


def test_every_alias_reaches_the_export(exported: _Export, store: sqlite3.Connection) -> None:
    """`alias` is what S3's pool search reads; an empty table would break search with the rest of
    the app perfectly healthy, so the whole crosswalk is compared, not merely counted."""
    baked = {(r["pool_id"], r["norm"]) for r in _rows(store, "SELECT pool_id, norm FROM alias")}
    assert baked == {(str(pool_id), norm) for norm, pool_id in exported.aliases}
    assert len(baked) > 0
    # A named pair, so a wholesale re-keying of the crosswalk cannot pass by staying
    # self-consistent with the gold rows it was derived from.
    assert ("hallenbad-city", "city") in baked


def test_locker_and_rental_docs_carry_their_domain_fields(
    exported: _Export, store: sqlite3.Connection
) -> None:
    """The facility-detail sheet reads these two tables; a builder that emitted `[]`, or dropped a
    key, would ship an empty or half-blank sheet. So assert the KEYS against the domain dataclasses
    and the VALUES against the facilities the store was built from."""
    lockers = [
        (r["pool_id"], r["ord"], json.loads(r["doc"]))
        for r in _rows(store, "SELECT * FROM pool_locker")
    ]
    rentals = [
        (r["pool_id"], r["ord"], json.loads(r["doc"]))
        for r in _rows(store, "SELECT * FROM pool_rental")
    ]
    assert lockers and rentals

    locker_fields = {f.name for f in dataclasses.fields(LockerOption)}
    # `fee` is the closed `RentalFee` union projected onto the wire as a state + an amount, so the
    # doc carries one key more than the dataclass — and never fewer.
    rental_fields = {f.name for f in dataclasses.fields(RentalItem)} | {"fee_chf"}
    assert all(set(doc) == locker_fields for _, _, doc in lockers)
    assert all(set(doc) == rental_fields for _, _, doc in rentals)

    by_id = {str(f.identity.facility_id): f for f in exported.facilities}
    assert sum(len(f.lockers) for f in exported.facilities) == len(lockers)
    assert sum(len(f.rentals) for f in exported.facilities) == len(rentals)
    for pool_id, ordinal, doc in lockers:
        locker = by_id[pool_id].lockers[ordinal]
        assert doc["category"] == locker.category.value
        assert doc["raw"] == locker.raw
        assert doc["deposit_chf"] == (
            float(locker.deposit_chf) if locker.deposit_chf is not None else None
        )
    for pool_id, ordinal, doc in rentals:
        rental = by_id[pool_id].rentals[ordinal]
        assert doc["kind"] == rental.kind.value
        assert doc["raw"] == rental.raw
        assert doc["fee"] in {"priced", "gratis", "unstated"}
        assert (doc["fee"] == "priced") == isinstance(rental.fee, Priced)


def test_there_is_no_feature_day_table(store: sqlite3.Connection) -> None:
    """Deliberate: every feature citywide has `hours=()`, so a date-keyed feature table would
    ship zero rows over the whole horizon. The per-date windows ride inside `pool_feature.doc`
    when a feature ever states hours — same table, no schema change."""
    tables = {r[0] for r in store.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "feature_day" not in tables
    docs = [json.loads(r["doc"]) for r in _rows(store, "SELECT doc FROM pool_feature")]
    assert docs and all(doc["days"] == {} for doc in docs), "a feature now states hours"


# --- Acceptance 4/5/6: horizon, hash, size ---------------------------------------------------


def test_the_horizon_is_fixed_at_400_days_regardless_of_calendar_coverage(
    exported: _Export,
) -> None:
    """E2: the export bakes the full horizon even where the calendar has no data, exactly as
    `/swim` serves those dates (with the warning) rather than withholding them."""
    report = exported.report
    assert report.horizon_start == TODAY
    assert report.horizon_end == TODAY + timedelta(days=FULL_DAYS - 1)
    uncovered = [d for d in horizon(TODAY, FULL_DAYS) if not exported.calendar.covers(d)]
    assert report.uncovered_days == len(uncovered) > 0
    print(f"\n{report.uncovered_days} of {FULL_DAYS} horizon days are outside calendar coverage")
    # Those days are EXPORTED, not withheld — the whole point of E2.
    assert report.uncovered_days == 0 or report.sessions > 0


def test_the_meta_row_states_the_horizon_and_the_schema_version(
    exported: _Export, store: sqlite3.Connection
) -> None:
    meta = dict(store.execute("SELECT key, value FROM meta").fetchall())
    assert meta["schema_version"] == str(SCHEMA_VERSION)
    assert meta["horizon_start"] == TODAY.isoformat()
    assert meta["horizon_end"] == exported.report.horizon_end.isoformat()
    assert meta["content_hash"] == exported.report.content_hash
    assert datetime.fromisoformat(meta["built_at"]).tzinfo is not None


def test_a_second_export_of_unchanged_gold_hashes_identically(
    gold_db: Path, exported: _Export, tmp_path: Path
) -> None:
    """The refresh path compares hashes to decide whether a download is worth it, so an export
    that hashed differently every run would push a new store at every build."""
    again = tmp_path / "again.sqlite"
    with sqlite3.connect(gold_db) as conn:
        result = export_ios(conn, again, today=TODAY, days=FULL_DAYS)
    assert isinstance(result, Ok)
    assert result.value.content_hash == exported.report.content_hash
    # `built_at` differs between the two runs, so the hash cannot simply be the file's digest.
    assert result.value.bytes == exported.report.bytes


def test_the_exported_file_stays_under_eight_megabytes(exported: _Export) -> None:
    size = exported.path.stat().st_size
    print(f"\nios.sqlite is {size / 1024 / 1024:.2f} MB ({size} bytes)")
    assert size == exported.report.bytes
    assert size < MAX_BYTES


# --- A store shaped like the ones the fixture cannot produce ---------------------------------


def _bespoke_gold(
    tmp_path: Path, facilities: tuple[Facility, ...], calendar: ZurichCalendar
) -> Path:
    """A gold store carrying `facilities` plus one pool with NO `facility_doc` at all.

    The recorded build gives every roster pool a blob and no pool a DAY-precision season, so the
    doc-less row and the day-precise season — both representable, both exported — have no other
    way to be exercised.
    """
    db = tmp_path / "gold.sqlite"
    conn = open_db(db)
    rows = tuple(
        PoolRow(
            id=f.identity.facility_id,
            name=f.identity.name,
            kind=f.identity.kind,
            address=f.address,
            geo=f.geo,
            url=None,
            description=None,
            phone=None,
            facility_doc=None,
        )
        for f in facilities
    )
    bare = PoolRow(
        id=PoolId("bare-pool"),
        name="Bare Pool",
        kind=PoolKind.OUTDOOR,
        address="",
        geo=None,
        url=None,
        description=None,
        phone=None,
        facility_doc=None,
    )
    write_pools(conn, PoolSpine(pools=(*rows, bare), aliases=(), xrefs=()))
    write_schedules(conn, tuple((f.identity.facility_id, f) for f in facilities))
    write_calendar(conn, calendar)
    conn.close()
    for facility in facilities:
        assert codec.loads(codec.dumps(facility)) == facility
    return db


def _sauna_facility() -> Facility:
    hours = ScheduleRule(
        weekdays=frozenset({Weekday.MONDAY}),
        time=TimeRange(time(10, 0), time(20, 0)),
        access=PublicSwim(),
    )
    return Facility(
        identity=PoolIdentity(
            facility_id=PoolId("sauna-pool"), name="Sauna Pool", kind=PoolKind.INDOOR
        ),
        address="Somewhere 1",
        provenance=Provenance(source="test", curated=False, valid_as_of=date(2026, 1, 1)),
        basins=(
            Basin(
                basin_id=BasinId("sauna-pool-becken"),
                name="Becken",
                kind=BasinKind.LAP,
                rules=(hours,),
            ),
        ),
        # A closure over the middle date, so the feature's resolved windows carry a
        # `closed_reason` on that date rather than only ever the open arm.
        closures=(ClosureRange(start=date(2026, 8, 25), end=date(2026, 8, 25), reason="Revision"),),
        features=(
            Feature(kind=FeatureKind.SAUNA, name="Sauna A", hours=(hours,)),
            # A SECOND feature of the same kind: `pool_feature` is keyed (pool_id, feature_key),
            # so a bare `kind` key would abort the whole export on a UNIQUE violation.
            Feature(kind=FeatureKind.SAUNA, name="Sauna B", temp_c=Decimal("90")),
        ),
    )


def _seasonal_facility() -> Facility:
    """A rule-less pool whose page states a DAY-precision season — the shape whose exported
    `operating_season` must name its days, where a MONTH window must not."""
    return Facility(
        identity=PoolIdentity(
            facility_id=PoolId("season-pool"), name="Season Pool", kind=PoolKind.PADDLING
        ),
        address="Somewhere 2",
        provenance=Provenance(source="test", curated=False),
        basins=(),
        operating_season=OperatingSeason(
            window=AnnualWindow(
                start=MonthDay(5, 30), end=MonthDay(8, 16), precision=DatePrecision.DAY
            ),
            weather=Weather.FAIR_ONLY,
        ),
    )


def test_a_feature_that_states_hours_carries_its_resolved_windows_per_date(
    tmp_path: Path, exported: _Export
) -> None:
    facility = _sauna_facility()
    db = _bespoke_gold(tmp_path, (facility, _seasonal_facility()), exported.calendar)
    out = tmp_path / "ios.sqlite"
    conn = sqlite3.connect(db)
    try:
        result = export_ios(conn, out, today=date(2026, 8, 24), days=3)
    finally:
        conn.close()
    assert isinstance(result, Ok), result

    with sqlite3.connect(out) as store:
        store.row_factory = sqlite3.Row
        docs = {
            r["feature_key"]: json.loads(r["doc"])
            for r in store.execute("SELECT feature_key, doc FROM pool_feature")
        }
        # The doc-less pool still gets a row, with no facility-derived facts on it.
        bare = store.execute("SELECT * FROM pool WHERE pool_id = 'bare-pool'").fetchone()
        season = json.loads(
            store.execute(
                "SELECT operating_season FROM pool WHERE pool_id = 'season-pool'"
            ).fetchone()[0]
        )
    assert set(docs) == {"sauna", "sauna#2"}
    days = docs["sauna"]["days"]
    # Monday 2026-08-24 states hours; the Tuesday and Wednesday after it do not.
    assert days["2026-08-24"] == {"windows": [["10:00", "20:00"]], "closed_reason": None}
    # The closure lands on the 25th: the feature is CLOSED that day, and says why.
    assert days["2026-08-25"] == {"windows": [], "closed_reason": "maintenance"}
    assert docs["sauna#2"]["days"] == {}, "a feature with no hours needs no per-date windows"
    assert bare["admission_state"] == "unknown"
    assert bare["source"] is None and bare["freshness"] == "no_source"
    # A DAY-precision season names its days; a MONTH one never may (it would overstate the page).
    assert season["precision"] == "day"
    assert (season["start_day"], season["end_day"]) == (30, 16)
    assert season["weather"] == "fair_only"


# --- The golden fixture S2 replays ------------------------------------------------------------

_PARITY_DIR = _REPO_ROOT / "tests" / "fixtures" / "ios_parity"
_PARITY_FILE = _PARITY_DIR / "answers.json"
_REGENERATE = os.environ.get("SWIMZH_REGENERATE_IOS_PARITY") == "1"

#: 3 pools × 5 dates × 3 personas — the golden answers S2's Swift `answer(...)` must reproduce.
#: The pools are the ones with the richest data (lane plans, a tariff, a girls-only session); the
#: dates straddle an ordinary weekday, a Sunday, a public holiday and an UNSEEDED calendar year.
_PARITY_POOLS = ("hallenbad-city", "hallenbad-oerlikon", "schulschwimmanlage-aemtler")
_PARITY_DATES = ("2026-08-24", "2026-09-17", "2026-11-15", "2026-12-25", "2027-01-05")
_PARITY_PERSONAS: tuple[tuple[str, Gender | None, int | None], ...] = (
    ("unspecified", None, None),
    ("woman-30", Gender.FEMALE, 30),
    ("boy-17", Gender.MALE, 17),
)
#: The time of day the personas ask at — the one input `open_at_query_time` turns on, which is
#: exactly the field S2 must compute in Swift rather than read from the store.
_PARITY_AT = time(12, 0)


def _parity_option(option: Any, person: Person) -> dict[str, Any]:
    verdict = eligibility(person, option.session.access)
    price = option.price
    return {
        "basin_id": str(option.basin_id),
        "start": option.session.time.start.strftime("%H:%M"),
        "end": option.session.time.end.strftime("%H:%M"),
        "access": type(option.session.access).__name__,
        "access_params": dataclasses.asdict(option.session.access),
        "weather": option.session.weather.value,
        "open_at_query_time": option.open_at_query_time,
        "eligible": verdict.allowed,
        "reason_code": str(verdict.code),
        "price": (
            None
            if price is None
            else {
                "category": price.category.value,
                "amount_chf": float(price.amount_chf),
                "display": price.display,
                "min_age": price.min_age,
            }
        ),
    }


def _parity_cases(
    facilities: tuple[Facility, ...], calendar: ZurichCalendar, roster: tuple[RosterEntry, ...]
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for day_iso in _PARITY_DATES:
        day = date.fromisoformat(day_iso)
        for label, gender, age in _PARITY_PERSONAS:
            person = Person(gender=gender, age=age)
            result = find_swim_options(
                SwimQuery(person=person, at=datetime.combine(day, _PARITY_AT, tzinfo=_ZURICH)),
                facilities,
                calendar,
                roster,
            )
            for pool in _PARITY_POOLS:
                cases.append(
                    {
                        "pool_id": pool,
                        "date": day_iso,
                        "persona": label,
                        "gender": gender.value if gender is not None else None,
                        "age": age,
                        "at": _PARITY_AT.strftime("%H:%M"),
                        "options": [
                            _parity_option(o, person)
                            for o in result.options
                            if str(o.facility_id) == pool
                        ],
                        "statuses": [
                            {
                                "status": s.status,
                                "detail_code": s.code.value,
                                "closure_code": (
                                    s.closure.value if s.closure is not None else None
                                ),
                                "detail_params": dict(s.params),
                            }
                            for s in result.statuses
                            if str(s.facility_id) == pool
                        ],
                        "warnings": list(result.warnings),
                    }
                )
    return cases


def test_the_ios_parity_golden_fixture_is_current(exported: _Export) -> None:
    """GENERATED from the domain query — the file S2's Swift `answer(...)` replays.

    Regenerate after a deliberate change::

        SWIMZH_REGENERATE_IOS_PARITY=1 uv run pytest tests/etl/test_ios_export.py
    """
    cases = _parity_cases(exported.facilities, exported.calendar, exported.roster)
    payload: Mapping[str, Any] = {
        "_note": (
            "GENERATED from swimzh.domain.query.find_swim_options by "
            "tests/etl/test_ios_export.py — do NOT hand-edit. Replayed by the Swift "
            "SwimZHKit golden test (plan S2 acceptance 3). Regenerate with "
            "SWIMZH_REGENERATE_IOS_PARITY=1."
        ),
        "generated_for": {"today": TODAY.isoformat(), "at": _PARITY_AT.strftime("%H:%M")},
        "cases": cases,
    }
    if _REGENERATE:
        _PARITY_DIR.mkdir(parents=True, exist_ok=True)
        _PARITY_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
    committed = json.loads(_PARITY_FILE.read_text(encoding="utf-8"))
    assert committed["cases"] == json.loads(json.dumps(cases)), (
        "the ios parity fixture is stale; regenerate with "
        "SWIMZH_REGENERATE_IOS_PARITY=1 uv run pytest tests/etl/test_ios_export.py"
    )
    # 3 pools × 5 dates × 3 personas, and the answers are not all empty.
    assert len(cases) == len(_PARITY_POOLS) * len(_PARITY_DATES) * len(_PARITY_PERSONAS)
    assert any(case["options"] for case in cases)
