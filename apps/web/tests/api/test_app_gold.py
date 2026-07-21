"""When SWIMZH_GOLD_DB points at a populated gold store, the app serves from it (the same
answers, now sourced through the SQLite gold path)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app
from swimzh.core.result import Ok
from swimzh.domain.access import ClubReserved, PublicSwim
from swimzh.domain.lane_plan import LanePlan, LaneReservation, PlanConfidence, PlanCoverage
from swimzh.domain.models import Basin, Facility
from swimzh.domain.schedule import TimeRange, Weekday
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import open_db, write_schedules

DATA_DIR = Path(__file__).resolve().parents[4] / "data"


def _gold_db_with_lane_plan(tmp_path: Path) -> Path:
    """A complete gold DB (facilities + catalog + calendar) whose City 50m basin carries a
    lane plan, so a gold-backed query surfaces the availability badge."""
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    # Re-write City's `pool.facility_doc` (the flipped read path) with a lane-plan-attached copy
    # via the single write door; the other pools keep their build-stamped catalog geo.
    attached = _attach_lane_plan(dataset.value.facilities)
    city = next(f for f in attached if f.identity.name == "Hallenbad City")
    write_schedules(open_db(db), ((city.identity.facility_id, city),))
    return db


def _attach_lane_plan(facilities: tuple[Facility, ...]) -> tuple[Facility, ...]:
    """Give City's 50m basin a lane plan (lanes 1–2 club, 3–6 public, all day every day) so a
    gold-backed query surfaces the availability badge. No curated pool has a plan yet (S2 needs
    live URLs), so the test populates one itself."""
    plan = LanePlan(
        lane_count=6,
        reservations=(
            LaneReservation(
                weekdays=frozenset(Weekday),
                time=TimeRange(time(0, 0), time.max),
                lanes=frozenset({1, 2}),
                access=ClubReserved(club="ASVZ"),
            ),
            LaneReservation(
                weekdays=frozenset(Weekday),
                time=TimeRange(time(0, 0), time.max),
                lanes=frozenset({3, 4, 5, 6}),
                access=PublicSwim(),
            ),
        ),
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )

    def with_plan(basin: Basin) -> Basin:
        return replace(basin, lane_plan=plan) if basin.name == "50m-Becken" else basin

    out: list[Facility] = []
    for facility in facilities:
        if facility.identity.name == "Hallenbad City":
            out.append(replace(facility, basins=tuple(with_plan(b) for b in facility.basins)))
        else:
            out.append(facility)
    return tuple(out)


def test_app_serves_from_gold_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34}
        )
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" in accesses


def test_lane_availability_badge_surfaces_through_the_swim_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _gold_db_with_lane_plan(tmp_path)

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        # Monday 20:30: City's 50m basin runs an 11:00–22:00 public session → an option exists.
        response = client.get(
            "/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34}
        )
    assert response.status_code == 200
    options = response.json()["options"]
    city_50m = [
        o for o in options if o["facility"] == "Hallenbad City" and o["basin"] == "50m-Becken"
    ]
    assert city_50m, "City's 50m basin must produce an option at this time"
    badge = city_50m[0]["lane_availability"]
    assert badge is not None
    assert badge["lane_count"] == 6
    assert badge["public_lanes"] == 4  # explicit public lanes 3–6, never derived by complement
    assert badge["reserved_lanes"] == 2
    assert badge["partial"] is False
    # Every other option (no plan) degrades to None, never an invented badge.
    assert any(o["lane_availability"] is None for o in options)


def test_lane_timeline_surfaces_through_the_swim_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _gold_db_with_lane_plan(tmp_path)

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34}
        )
    assert response.status_code == 200
    options = response.json()["options"]
    city_50m = [
        o for o in options if o["facility"] == "Hallenbad City" and o["basin"] == "50m-Becken"
    ]
    assert city_50m
    timeline = city_50m[0]["lane_timeline"]
    assert timeline is not None
    # The seeded plan is constant all day, so the 11:00–22:00 session is one segment (4 public).
    assert timeline["segments"]
    assert timeline["segments"][0]["public_lanes"] == 4
    assert timeline["segments"][0]["lane_count"] == 6
    # No-plan options carry no timeline, never an invented one.
    assert any(o["lane_timeline"] is None for o in options)


def test_facility_detail_lane_panel_surfaces_through_pools_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4: the /pools/{id} facility-detail response carries a per-basin lane panel — the
    per-lane day timeline, the best public window, and the club roster — for basins with a
    parsed Belegungsplan."""
    db = _gold_db_with_lane_plan(tmp_path)

    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        # 2026-09-15 is a Tuesday; the plan is every-day, so the panel resolves.
        response = client.get("/pools/hallenbad-city", params={"at": "2026-09-15T07:00"})
    assert response.status_code == 200
    body = response.json()
    panels = {p["basin_name"]: p for p in body["lane_panels"]}
    assert "50m-Becken" in panels  # the basin we gave a plan
    panel = panels["50m-Becken"]["panel"]

    # Best public time: lanes 3–6 are public (4 lanes) all day.
    assert panel["best_public"]["public_lanes"] == 4
    # Day timeline: one strip per lane; lane 1 is held by ASVZ (reserved, not public).
    day = panel["day_view"]
    assert day["lane_count"] == 6
    assert day["weekday"] == 1  # Tuesday
    lane1 = next(s for s in day["strips"] if s["lane"] == 1)
    assert lane1["segments"][0]["access"] == "ClubReserved"
    assert lane1["segments"][0]["owner"] == "ASVZ"
    lane3 = next(s for s in day["strips"] if s["lane"] == 3)
    assert lane3["segments"][0]["access"] == "PublicSwim"
    assert lane3["segments"][0]["owner"] is None  # public lanes carry no owner label
    # Club roster: ASVZ holds lanes 1–2, public is excluded.
    assert {r["club"] for r in panel["roster"]} == {"ASVZ"}
    assert next(r for r in panel["roster"] if r["club"] == "ASVZ")["lanes"] == [1, 2]
