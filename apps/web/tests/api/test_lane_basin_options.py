"""lane-stack-board S1: a curated lane basin carried beside the scraped Hauptbecken inherits the
scraped timetable, so it produces its own `/swim` session — the session whose basin owns the
Belegungsplan, which is what puts a real lane split on the wire.

The phase that exercises the join is `build` (the atomic pipeline), not the `scrape-gold` re-layer
(see `docs/2026-08-10-scrape-gold-recompose-defect.md`), so both tests run against the `gold_db`
fixture — a fresh offline build.

`swim_baseline_2026-08-12.json` was generated from that same fixture build **before** the
`_carry_bindings` change, so it is a reference independent of the code under test. It is a frozen
pre-change artefact: never regenerate it to make a test pass.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from fastapi.testclient import TestClient

from apps.web.main import app
from apps.web.services.gold_store import GoldSwimStore
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import SwimQuery, find_swim_options

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_DATA_POOLS = Path(__file__).resolve().parents[4] / "data" / "pools"

# Wednesday 2026-08-12 12:00 — the instant the committed baseline was measured at. Oerlikon is
# shut that day, which is exactly why the baseline is per-date and no store-wide total is asserted.
AT = "2026-08-12T12:00"
_AT_DT = datetime(2026, 8, 12, 12, 0, tzinfo=ZoneInfo("Europe/Zurich"))


def _baseline() -> dict[str, Any]:
    text = (_FIXTURES / "swim_baseline_2026-08-12.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def _binding_basin_ids() -> set[str]:
    """Every basin declaring a `lane_plan_source` in the thin crosswalk — the only basins that may
    gain an option under S1."""
    ids: set[str] = set()
    for path in sorted(_DATA_POOLS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for basin in doc.get("basins", ()):
            if basin.get("lane_plan_source") is not None:
                ids.add(basin["basin_id"])
    return ids


def test_city_lane_basin_serves_its_own_option_with_a_lane_timeline() -> None:
    """AC3: Hallenbad City's `Schwimmerbecken` (6 lanes, Belegungsplan-bound) now reaches `/swim`
    as its own option, and it is the option carrying the parsed lane split."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": AT, "eligible_only": "false"})
    assert response.status_code == 200
    lane_options = [
        o
        for o in response.json()["options"]
        if o["facility_id"] == "hallenbad-city" and o["basin"] == "Schwimmerbecken"
    ]
    assert lane_options, "the carried City lane basin produced no option"
    timelines = [o["lane_timeline"] for o in lane_options]
    assert all(t is not None for t in timelines), "the lane basin's option carries no lane timeline"
    lane_counts = {seg["lane_count"] for t in timelines for seg in t["segments"]}
    assert lane_counts == {6}


def test_options_contain_the_baseline_and_gain_only_lane_bound_basins(gold_db: Path) -> None:
    """AC4: baseline-relative containment — no loss, no drift, bounded gain.

    Read through the domain query rather than `/swim`, because `basin_id` (the identity half of a
    baseline tuple) does not reach the wire until S2.
    """
    baseline = _baseline()
    assert baseline["at"] == _AT_DT.isoformat()
    store = GoldSwimStore.open(gold_db)
    result = find_swim_options(
        SwimQuery(person=Person(gender=Gender.FEMALE, age=34), at=_AT_DT),
        store.facilities(),
        store.calendar(),
    )
    current = {
        (
            str(o.facility_id),
            str(o.basin_id),
            o.session.time.start.strftime("%H:%M"),
            o.session.time.end.strftime("%H:%M"),
            type(o.session.access).__name__,
        )
        for o in result.options
    }
    before = {tuple(row) for row in baseline["options"]}

    missing = before - current
    assert not missing, f"baseline options lost or drifted: {sorted(missing)}"

    baseline_facilities = {row[0] for row in before}
    baseline_pairs = {(row[0], row[1]) for row in before}
    bindings = _binding_basin_ids()
    gained = {(fid, bid) for fid, bid, *_ in current} - baseline_pairs
    assert gained, "no lane basin gained an option — the join did not fire"
    for facility_id, basin_id in sorted(gained):
        assert basin_id in bindings, f"{basin_id} gained an option without a lane_plan_source"
        assert facility_id in baseline_facilities, (
            f"{facility_id} gained its first option from a lane basin — "
            "a carried basin must never make a facility appear that was absent before"
        )
