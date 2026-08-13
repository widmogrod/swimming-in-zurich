"""The reported defect, pinned end-to-end: *"when I switch dates order of swimming pools
changes, this is non intuitive"* (board-order-and-defects, 2026-08-11).

Measured over the SERVED answer, at the place the UI actually sends — `PLACE_PRESETS[0]`
(Zürich HB, `app.ts:78-82`), always emitted as `lat`/`lon` by `api.ts:105-107`. A measurement
taken with no place is not evidence about the product: the app seeds a place on load, so no
user is ever in the state where every `distance_km` is null.

Rule O1: a row's position is a property of geography, never of today's outcome. Rule O2: the
two groups stay (open first, then closed / schedule-less), and a pool crossing that boundary is
a real change in the world — which is why nothing here asserts identical INDICES.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.web.main import create_app

# The place the UI sends on every request (Zürich HB).
HB = {"lat": 47.3779, "lon": 8.5403}

# The pair of consecutive dates the defect was measured on. Wednesday 2026-08-12 →
# Thursday 2026-08-13: Schulschwimmanlage Tannenrauch is open on the first and shut on the
# second, which is exactly the pool whose 15 → 41 jump the report leads with.
WEDNESDAY = "2026-08-12T12:00"
THURSDAY = "2026-08-13T12:00"

# The two halves of the status list, by the `status` values each source can emit.
# `_schedule_less_statuses` (query.py) runs OUTSIDE the facility loop and builds from a
# `RosterEntry`; everything else is emitted inside it from a `Facility`.
SCHEDULE_LESS = {"awaiting_scrape", "no_source"}


@pytest.fixture
def answers(gold_db: Path) -> dict[str, dict[str, Any]]:
    """Both days' served answers, from the one offline-built session store."""
    with TestClient(create_app()) as client:
        out = {}
        for at in (WEDNESDAY, THURSDAY):
            response = client.get("/swim", params={"at": at, **HB})
            assert response.status_code == 200, response.text
            out[at] = response.json()
        return out


def _open_group(answer: dict[str, Any]) -> list[str]:
    """The facilities of the OPEN group, in served order, de-duplicated — one pool may
    contribute several option rows (several basins, several sessions)."""
    names: list[str] = []
    for option in answer["options"]:
        if option["facility"] not in names:
            names.append(option["facility"])
    return names


def _closed_group(answer: dict[str, Any]) -> list[str]:
    return [s["facility"] for s in answer["statuses"]]


def _distance_of(answer: dict[str, Any], facility: str) -> float:
    """The one distance the answer states for a pool, from whichever group it is in. Fails
    loudly rather than returning `None`: on this store every pool publishes a position, so a
    missing number is the defect, not an input."""
    for row in [*answer["statuses"], *answer["options"]]:
        if row["facility"] == facility:
            km = row["distance_km"]
            assert isinstance(km, float), f"{facility} states no distance"
            return km
    raise AssertionError(f"{facility} is in neither group")


# --- AC1: the order itself ------------------------------------------------------------


def test_each_group_is_served_in_distance_order(answers: dict[str, dict[str, Any]]) -> None:
    """O1, stated directly: within a group, position is decided by `(distance, name)` and
    nothing else.

    This is the assertion the fix has to earn. The relative-order test below is NOT enough on
    its own — measured against this store it is green BEFORE the fix too, because the store
    iterates facilities in a stable order, so an unranked status list is still a *consistent*
    unranked status list from one day to the next. What the defect actually costs the reader is
    that the order is decided by something invisible: pre-fix, Hallenbad Leimbach — the
    FURTHEST closed pool at 6.07 km — was served third of 38.

    Only the DISTANCES are asserted monotonic here, not the full `(distance, name)` key: the
    wire rounds to 2 dp (`service._km_out`), which manufactures ties the domain does not have —
    Planschbecken Althoos and Hallenbad Bläsi both read 3.9 km and are genuinely 3 m apart. The
    name tie-break is a domain property and is pinned there, on an exact tie.
    """
    for at, answer in answers.items():
        closed = [s["distance_km"] for s in answer["statuses"]]
        assert closed == sorted(closed), f"{at}: the closed group is not in distance order"
        # The open group keeps the key it already had (distance, then session start, then name),
        # so only the distances are monotonic here too.
        open_km = [o["distance_km"] for o in answer["options"]]
        assert open_km == sorted(open_km), f"{at}: the open group is not in distance order"


def test_the_furthest_closed_pool_is_served_last_and_the_nearest_first(
    answers: dict[str, dict[str, Any]],
) -> None:
    """The same property named in pools, so a failure reads as a fact about the city rather
    than as a sorted-list assertion. Pre-fix Leimbach sat 3rd of 38 with no distance at all."""
    for at, answer in answers.items():
        closed = answer["statuses"]
        km = [s["distance_km"] for s in closed]
        assert closed[0]["distance_km"] == min(km), at
        # Named, on both days: Leimbach is the furthest pool that is shut, and it now reads last.
        assert closed[-1]["facility"] == "Hallenbad Leimbach", at
        assert closed[-1]["distance_km"] == pytest.approx(6.07, abs=0.01), at


def test_the_facilities_common_to_both_days_keep_their_relative_order(
    answers: dict[str, dict[str, Any]],
) -> None:
    """AC1 as the plan states it — RELATIVE order, per group, not identical indices.

    Identical indices are unachievable and asserting them would be asserting a bug: a pool
    crossing the open/closed boundary shifts every later index in the destination group, which
    O2 concedes is a real change in the world. Over this pair of days 18 facilities are common
    to both open groups and 36 to both closed groups, and their relative order is unchanged
    while many of their indices move.

    **This test does not discriminate the fix, and no reader should believe it does.** It was
    measured green BEFORE the status sort existed too: the store iterates facilities in a
    stable order, so an unranked status list is a *consistently* unranked one from one day to
    the next. It is a NON-REGRESSION guard — it catches a future ordering key that is unstable
    across dates (a clock, a session start, an insertion order) — and nothing more.

    `test_each_group_is_served_in_distance_order` above is the one that earns the fix. Deleting
    THAT test and keeping this one would leave the reported defect entirely unguarded while the
    suite still read as though AC1 were covered.
    """
    wed, thu = answers[WEDNESDAY], answers[THURSDAY]
    for group in (_open_group, _closed_group):
        a, b = group(wed), group(thu)
        common = set(a) & set(b)
        assert len(common) >= 18, "too few common facilities for this to prove anything"
        assert [f for f in a if f in common] == [f for f in b if f in common]


def test_a_pool_that_shuts_overnight_lands_at_its_own_distance_rank(
    answers: dict[str, dict[str, Any]],
) -> None:
    """The reported pool, by name. Tannenrauch is open on the Wednesday and shut on the
    Thursday — the move between groups is real and stays. What must NOT happen any more is the
    pool landing in an arbitrary slot: on Thursday its closed-group neighbours are the pools
    immediately nearer and further than it, and its distance is unchanged from Wednesday.
    """
    wed, thu = answers[WEDNESDAY], answers[THURSDAY]
    assert "Schulschwimmanlage Tannenrauch" in _open_group(wed)
    closed_thu = _closed_group(thu)
    assert "Schulschwimmanlage Tannenrauch" in closed_thu

    km = _distance_of(wed, "Schulschwimmanlage Tannenrauch")
    assert _distance_of(thu, "Schulschwimmanlage Tannenrauch") == km

    index = closed_thu.index("Schulschwimmanlage Tannenrauch")
    before = thu["statuses"][index - 1]["distance_km"]
    after = thu["statuses"][index + 1]["distance_km"]
    assert before <= km <= after


# --- AC2: BOTH status sources carry a distance ----------------------------------------


def test_no_status_for_a_geo_bearing_pool_ships_a_null_distance(
    answers: dict[str, dict[str, Any]],
) -> None:
    """AC2, asserted over the WHOLE answer so the harder half cannot be missed.

    Every one of the 57 roster pools publishes a position, so on this store a `null` here is
    always a bug rather than an honest unknown. The counts are pinned per SOURCE because that
    is the failure this criterion exists for: `_schedule_less_statuses` emits 18 of the 38 rows
    from a `RosterEntry` outside the facility loop, and a fix that only threads the distance
    through the loop leaves exactly those 18 unranked — half the closed board stranded in O4's
    tail, with the other half ordered correctly and nothing on screen to say so.
    """
    for at, answer in answers.items():
        statuses = answer["statuses"]
        schedule_less = [s for s in statuses if s["status"] in SCHEDULE_LESS]
        in_loop = [s for s in statuses if s["status"] not in SCHEDULE_LESS]
        # Both halves are actually present, so neither assertion below is vacuous.
        assert len(schedule_less) == 18, at
        assert len(in_loop) >= 19, at
        assert [s["facility"] for s in statuses if s["distance_km"] is None] == [], at
        assert all(isinstance(s["distance_km"], float) for s in statuses), at
        # O4's forbidden mis-fix: a fabricated zero would rank an unknown pool first.
        assert all(s["distance_km"] > 0 for s in statuses), at


# --- AC4: one number, whichever group the pool is in ----------------------------------


def test_a_closed_pools_distance_is_the_one_its_option_carries_when_it_is_open(
    answers: dict[str, dict[str, Any]],
) -> None:
    """AC4. Both values go through the same wire rounding (`service._km_out`), so this is an
    equality and not an approximation — the point of the rule is that the pool does not move."""
    wed, thu = answers[WEDNESDAY], answers[THURSDAY]
    open_wed = {o["facility"]: o["distance_km"] for o in wed["options"]}
    closed_thu = {s["facility"]: s["distance_km"] for s in thu["statuses"]}
    crossed = set(open_wed) & set(closed_thu)
    assert crossed, "no pool crosses the boundary between these two days"
    for facility in crossed:
        assert closed_thu[facility] == open_wed[facility], facility
