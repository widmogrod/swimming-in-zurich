"""`swimzh build --lake`: the pipeline-owned lake end to end, over the same recorded transport the
other CLI tests use. What is proved here is the runtime contract of the page's option 2: a run
pulls last time's silver, fetches only what is due, keeps a stale silver when a source is DOWN
(exit 2, the store says which), and still aborts on schema drift or a too-old silver."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.cli import EXIT_BUILT_STALE, build, main
from swimzh.etl.ios_export import export_ios, manifest_for
from swimzh.storage.lake import SILVER_SOURCES, Lake, SilverStatus
from swimzh.storage.sqlite_repo import GoldRepository, load_source_freshness, open_db
from tests.pipeline_clients import recorded_build_clients, unreachable_wfs_clients

_ZURICH = ZoneInfo("Europe/Zurich")
_MONDAY = datetime(2026, 8, 31, 5, 0, tzinfo=_ZURICH)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _wfs_down(request: httpx.Request) -> httpx.Response | None:
    if request.url.params.get("TYPENAME"):
        return httpx.Response(500, text="<html>Internal Server Error</html>")
    return None


def _wfs_drifted(request: httpx.Request) -> httpx.Response | None:
    if request.url.params.get("TYPENAME"):
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [{"bogus": 1}]})
    return None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freshness(db: Path) -> dict[str, tuple[str, datetime]]:
    conn = open_db(db)
    try:
        return {
            row.header.source: (row.header.status.value, row.header.fetched_at)
            for row in load_source_freshness(conn)
        }
    finally:
        conn.close()


def _first_build(tmp_path: Path) -> tuple[Path, Lake]:
    db = tmp_path / "gold.sqlite"
    lake = Lake(tmp_path / "lake")
    code = build(
        db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients(), lake=lake, now=_MONDAY
    )
    assert code == 0
    return db, lake


def test_a_first_run_fetches_every_source_and_writes_four_fresh_silvers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, lake = _first_build(tmp_path)
    for source in SILVER_SOURCES:
        doc = lake.read(source)
        assert doc is not None, source
        assert doc.header.status is SilverStatus.FRESH and doc.header.fetched_at == _MONDAY
    rows = _freshness(db)
    assert set(rows) == set(SILVER_SOURCES)
    assert all(status == "fresh" and at == _MONDAY for status, at in rows.values())
    out = capsys.readouterr().out
    assert "sources: roster fresh (fetched" in out


def test_inside_the_ttl_a_rerun_reuses_the_lake_and_never_touches_the_network(
    tmp_path: Path,
) -> None:
    db, lake = _first_build(tmp_path)
    before = _digest(db)
    # Every connection refused: the only way this passes is by never opening one.
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=unreachable_wfs_clients(),
        lake=lake,
        now=_MONDAY + timedelta(hours=6),
    )
    assert code == 0
    assert _digest(db) != before  # rebuilt (built_at moved) ...
    rows = _freshness(db)
    assert all(
        status == "fresh" and at == _MONDAY for status, at in rows.values()
    )  # ... on the same facts
    assert GoldRepository(open_db(db)).count() == 57


def _xrefs(db: Path) -> set[tuple[str, str, str]]:
    conn = sqlite3.connect(db)
    try:
        return set(conn.execute("SELECT pool_id, namespace, ext_id FROM pool_xref").fetchall())
    finally:
        conn.close()


def _geo_sport_ids(db: Path) -> dict[str, str | None]:
    return {
        str(f.identity.facility_id): f.identity.geo_sport_id
        for f in GoldRepository(open_db(db)).load_all()
    }


def test_a_lake_warm_rebuild_keeps_every_spine_fact_of_the_cold_build(tmp_path: Path) -> None:
    """Regression: the roster silver once dropped the WFS `poi_id`, so a warm rebuild silently
    lost every `geo_sport` xref and nulled `geo_sport_id` on all 57 pools (2026-09-06 audit)."""
    db, lake = _first_build(tmp_path)
    cold_xrefs, cold_ids = _xrefs(db), _geo_sport_ids(db)
    assert cold_xrefs  # the recorded roster carries no poi_id, so the direct pin is in
    # `test_the_roster_silver_keeps_the_wfs_poi_id` below; this one proves the spine is stable.
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=unreachable_wfs_clients(),
        lake=lake,
        now=_MONDAY + timedelta(hours=6),
    )
    assert code == 0
    assert _xrefs(db) == cold_xrefs
    assert _geo_sport_ids(db) == cold_ids


def test_the_content_sha_tracks_facts_not_fetch_times(tmp_path: Path) -> None:
    _, lake = _first_build(tmp_path)
    first = {s: lake.read(s).header.content_sha for s in SILVER_SOURCES}  # type: ignore[union-attr]
    other = Lake(tmp_path / "lake2")
    assert (
        build(
            db_path=tmp_path / "g2.sqlite",
            data_dir=DATA_DIR,
            clients=recorded_build_clients(),
            lake=other,
            now=_MONDAY + timedelta(days=30),
        )
        == 0
    )
    second = {s: other.read(s).header.content_sha for s in SILVER_SOURCES}  # type: ignore[union-attr]
    assert first == second  # same recorded pages, a month apart: same facts, same sha


def test_a_down_source_past_its_ttl_is_kept_stale_and_the_build_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, lake = _first_build(tmp_path)
    friday = _MONDAY + timedelta(days=20)  # past the 14 d roster TTL, inside the 90 d max_stale
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=recorded_build_clients(_wfs_down),
        lake=lake,
        now=friday,
    )
    assert code == EXIT_BUILT_STALE
    rows = _freshness(db)
    assert rows["roster"] == ("stale", _MONDAY)  # the REAL fetch time, kept
    assert rows["prices"] == ("fresh", friday)  # every other source refetched on this run
    assert rows["schedules"] == ("fresh", friday)
    assert rows["lane_plans"] == ("fresh", friday)
    roster = lake.read("roster")
    assert roster is not None and roster.header.status is SilverStatus.STALE
    err = capsys.readouterr().err
    assert "roster: source unreachable" in err and "STALE" in err
    assert GoldRepository(open_db(db)).count() == 57


def test_a_down_source_past_max_stale_aborts_with_the_prior_store_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, lake = _first_build(tmp_path)
    before = _digest(db)
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=recorded_build_clients(_wfs_down),
        lake=lake,
        now=_MONDAY + timedelta(days=100),
    )
    assert code == 1
    assert _digest(db) == before
    err = capsys.readouterr().err
    assert "build aborted: WFS roster unavailable" in err and "past max_stale" in err
    roster = lake.read("roster")
    assert roster is not None and roster.header.status is SilverStatus.FRESH  # not rewritten


def test_schema_drift_aborts_even_with_a_young_silver_to_fall_back_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, lake = _first_build(tmp_path)
    before = _digest(db)
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=recorded_build_clients(_wfs_drifted),
        lake=lake,
        now=_MONDAY + timedelta(days=20),
    )
    assert code == 1
    assert _digest(db) == before
    assert "build aborted: WFS roster unavailable: roster:" in capsys.readouterr().err


def test_a_first_run_against_a_down_source_aborts_as_before_the_lake(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "gold.sqlite"
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=recorded_build_clients(_wfs_down),
        lake=Lake(tmp_path / "lake"),
        now=_MONDAY,
    )
    assert code == 1
    assert not db.exists()
    assert "first run" in capsys.readouterr().err


def test_force_refetches_inside_the_ttl(tmp_path: Path) -> None:
    db, lake = _first_build(tmp_path)
    later = _MONDAY + timedelta(hours=1)
    code = build(
        db_path=db,
        data_dir=DATA_DIR,
        clients=recorded_build_clients(),
        lake=lake,
        now=later,
        force=True,
    )
    assert code == 0
    assert all(at == later for _, at in _freshness(db).values())


def test_the_silver_is_our_facts_not_the_citys_bytes(tmp_path: Path) -> None:
    _, lake = _first_build(tmp_path)
    roster = lake.read("roster")
    assert roster is not None
    assert roster.payload["count"] == 57 and len(roster.payload["entries"]) == 57
    schedules = lake.read("schedules")
    assert schedules is not None
    assert schedules.payload["facilities"] and "<html" not in json.dumps(schedules.payload)
    lanes = lake.read("lane_plans")
    assert lanes is not None and lanes.payload["plans"] and lanes.payload["links"]


def test_pull_then_build_continues_from_a_published_lake(tmp_path: Path) -> None:
    """Runtime seam: export → (host it anywhere) → pull → build reuses without the network."""
    _, lake = _first_build(tmp_path)
    published = tmp_path / "dist"
    assert main(["lake", "export", "--lake", str(lake.root), "--out", str(published)]) == 0
    assert sorted(p.name for p in (published / "silver").iterdir()) == sorted(
        f"{s}.json" for s in SILVER_SOURCES
    )

    fresh_checkout = tmp_path / "elsewhere"
    assert main(["lake", "pull", str(published), "--lake", str(fresh_checkout / ".lake")]) == 0
    code = build(
        db_path=fresh_checkout / "gold.sqlite",
        data_dir=DATA_DIR,
        clients=unreachable_wfs_clients(),
        lake=Lake(fresh_checkout / ".lake"),
        now=_MONDAY + timedelta(hours=2),
    )
    assert code == 0


def test_main_threads_the_lake_flag_into_build(tmp_path: Path) -> None:
    lake_dir = tmp_path / "mylake"
    code = main(
        [
            "build",
            "--db",
            str(tmp_path / "g.sqlite"),
            "--data",
            str(DATA_DIR),
            "--lake",
            str(lake_dir),
        ],
        clients=recorded_build_clients(),
    )
    assert code == 0
    assert (lake_dir / "silver" / "roster.json").exists()


def test_pull_from_an_absent_origin_is_a_loud_no_op(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["lake", "pull", str(tmp_path / "nowhere"), "--lake", str(tmp_path / "lake")]) == 0
    assert "nothing" in capsys.readouterr().out


def test_pull_names_each_failed_source_on_stderr_and_still_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Best-effort by design: a corrupt upstream document is reported (typed, via `describe`)
    and skipped, and the next build treats that source as a first run."""
    origin = tmp_path / "origin" / "silver"
    origin.mkdir(parents=True)
    (origin / "roster.json").write_text("{not json", encoding="utf-8")
    assert main(["lake", "pull", str(tmp_path / "origin"), "--lake", str(tmp_path / "lake")]) == 0
    captured = capsys.readouterr()
    assert "lake pull: skipping roster:" in captured.err and "unreadable" in captured.err
    assert "nothing" in captured.out and "(failed: roster)" in captured.out
    assert "(absent: prices, schedules, lane_plans)" in captured.out


def test_the_manifest_carries_the_stores_per_source_freshness(tmp_path: Path) -> None:
    db, lake = _first_build(tmp_path)
    friday = _MONDAY + timedelta(days=20)
    assert (
        build(
            db_path=db,
            data_dir=DATA_DIR,
            clients=recorded_build_clients(_wfs_down),
            lake=lake,
            now=friday,
        )
        == EXIT_BUILT_STALE
    )
    out = tmp_path / "ios.sqlite"
    conn = sqlite3.connect(db)
    try:
        assert export_ios(conn, out, today=friday.date(), days=3).__class__.__name__ == "Ok"
    finally:
        conn.close()
    manifest = manifest_for(out, url="https://example.test/ios.sqlite")
    assert manifest.__class__.__name__ == "Ok"
    freshness = {row["source"]: row for row in manifest.value.freshness}  # type: ignore[union-attr]
    assert freshness["roster"]["status"] == "stale"
    assert freshness["roster"]["fetched_at"] == _MONDAY.isoformat()
    assert freshness["schedules"]["status"] == "fresh"
    assert '"freshness"' in manifest.value.to_json()  # type: ignore[union-attr]


def test_the_roster_silver_keeps_the_wfs_poi_id() -> None:
    """The direct pin for the 2026-09-06 audit finding: `poi_id` is what becomes `geo_sport_id`
    and the `geo_sport` xref; a silver round-trip that drops it nulls both on a warm build."""
    from swimzh.domain.catalog import PoolCatalogEntry
    from swimzh.domain.models import PoolKind
    from swimzh.etl.silver_codec import decode_roster, encode_roster

    entry = PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=PoolKind.INDOOR,
        address="Sihlstrasse 77, 8001 Zürich",
        geo=None,
        url=None,
        description=None,
        phone=None,
        poi_id="hb001",
    )
    assert decode_roster(encode_roster((entry,), _MONDAY)) == (entry,)
