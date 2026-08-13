"""The facility-detail lane derivations — pure projections of a stored `LanePlan`:
`lane_day_view` (per-lane day timeline), `club_roster` (non-public reservations grouped by
owner), and `best_public_time` (the window with the most public lanes free). All invent no
data: a lane's day is exactly its stored reservations, and public lanes are counted
explicitly, so a blank slot is never made public.
"""

from __future__ import annotations

from datetime import date, time

from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved
from swimzh.domain.lane_plan import (
    ClubSlot,
    LanePlan,
    LaneReservation,
    LaneSegment,
    PlanConfidence,
    PlanCoverage,
    PublicWindow,
    best_public_time,
    club_roster,
    lane_day_view,
    lane_panel,
)
from swimzh.domain.schedule import TimeRange, Weekday


def _plan(reservations: tuple[LaneReservation, ...], *, lane_count: int = 6) -> LanePlan:
    return LanePlan(
        lane_count=lane_count,
        reservations=reservations,
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=PlanConfidence.COMPLETE, cells_total=1344, cells_resolved=1344
        ),
    )


def _res(
    weekdays: set[Weekday], start: time, end: time, lanes: set[int], access: object
) -> LaneReservation:
    return LaneReservation(
        weekdays=frozenset(weekdays),
        time=TimeRange(start, end),
        lanes=frozenset(lanes),
        access=access,  # type: ignore[arg-type]
    )


# City Tue 06:00–08:00: lanes 1 (ASVZ), 2 (Swimatic), 3–6 public; then 08:00–10:00 all public.
CITY = _plan(
    (
        _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {1}, ClubReserved(club="ASVZ")),
        _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {2}, ClubReserved(club="Swimatic")),
        _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {3, 4, 5, 6}, PublicSwim()),
        _res({Weekday.TUESDAY}, time(8, 0), time(10, 0), {1, 2, 3, 4, 5, 6}, PublicSwim()),
    )
)


# --- lane_day_view ----------------------------------------------------------------------


def test_day_view_has_one_strip_per_lane_time_ordered() -> None:
    view = lane_day_view(CITY, Weekday.TUESDAY)
    assert view.lane_count == 6
    assert [s.lane for s in view.strips] == [1, 2, 3, 4, 5, 6]
    # Lane 1: reserved 06:00–08:00, then public 08:00–10:00 — sorted by start.
    lane1 = view.strips[0]
    assert lane1.segments == (
        LaneSegment(time=TimeRange(time(6, 0), time(8, 0)), access=ClubReserved(club="ASVZ")),
        LaneSegment(time=TimeRange(time(8, 0), time(10, 0)), access=PublicSwim()),
    )
    # Lane 3 was public both windows.
    lane3 = view.strips[2]
    assert [type(s.access).__name__ for s in lane3.segments] == ["PublicSwim", "PublicSwim"]


def test_day_view_leaves_gaps_implicit_never_public() -> None:
    # Lane 1 is only reserved 06:00–08:00; the rest of the day is simply absent (no segment) —
    # never invented as a public segment.
    plan = _plan(
        (_res({Weekday.MONDAY}, time(6, 0), time(8, 0), {1}, SchoolReserved()),),
        lane_count=2,
    )
    view = lane_day_view(plan, Weekday.MONDAY)
    assert len(view.strips[0].segments) == 1  # one reserved block, gaps not filled
    assert view.strips[1].segments == ()  # lane 2 never used that day → empty strip, not public


def test_day_view_other_weekday_is_all_empty() -> None:
    view = lane_day_view(CITY, Weekday.SUNDAY)
    assert all(strip.segments == () for strip in view.strips)


# --- club_roster ------------------------------------------------------------------------


def test_roster_groups_non_public_by_owner_and_excludes_public() -> None:
    roster = club_roster(CITY)
    # Only the two clubs — public blocks are not in the roster.
    assert [(r.club, r.lanes) for r in roster] == [
        ("ASVZ", (1,)),
        ("Swimatic", (2,)),
    ]
    assert all(r.weekday == Weekday.TUESDAY for r in roster)


def test_roster_expands_weekdays_and_labels_schools() -> None:
    plan = _plan(
        (
            _res(
                {Weekday.MONDAY, Weekday.WEDNESDAY},
                time(12, 0),
                time(13, 0),
                {1, 2},
                SchoolReserved(),
            ),
        ),
        lane_count=6,
    )
    roster = club_roster(plan)
    # One ClubSlot per weekday, sorted by weekday; SchoolReserved renders as "Schools".
    assert roster == (
        ClubSlot(
            club="Schools",
            weekday=Weekday.MONDAY,
            time=TimeRange(time(12, 0), time(13, 0)),
            lanes=(1, 2),
        ),
        ClubSlot(
            club="Schools",
            weekday=Weekday.WEDNESDAY,
            time=TimeRange(time(12, 0), time(13, 0)),
            lanes=(1, 2),
        ),
    )


def test_roster_sorts_by_owner_then_weekday_then_time() -> None:
    plan = _plan(
        (
            _res({Weekday.TUESDAY}, time(18, 0), time(20, 0), {1}, ClubReserved(club="Zebra")),
            _res({Weekday.MONDAY}, time(6, 0), time(8, 0), {2}, ClubReserved(club="Alpha")),
            _res({Weekday.MONDAY}, time(6, 0), time(8, 0), {1}, SchoolReserved()),
        )
    )
    order = [(r.club, int(r.weekday)) for r in club_roster(plan)]
    assert order == [("Alpha", 0), ("Schools", 0), ("Zebra", 1)]  # club label, then weekday


# --- best_public_time -------------------------------------------------------------------


def test_best_public_picks_the_window_with_most_public_lanes() -> None:
    # 06:00–08:00 has 4 public lanes; 08:00–10:00 has all 6 — the latter wins.
    best = best_public_time(CITY, Weekday.TUESDAY)
    assert best == PublicWindow(time=TimeRange(time(8, 0), time(10, 0)), public_lanes=6)


def test_best_public_is_none_when_no_public_that_day() -> None:
    plan = _plan((_res({Weekday.MONDAY}, time(6, 0), time(8, 0), {1, 2}, SchoolReserved()),))
    assert best_public_time(plan, Weekday.MONDAY) is None
    assert best_public_time(CITY, Weekday.SUNDAY) is None  # no reservations at all


def test_best_public_merges_adjacent_equal_windows() -> None:
    # Two back-to-back public blocks with the same count merge into one 06:00–10:00 window.
    plan = _plan(
        (
            _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {1, 2, 3}, PublicSwim()),
            _res({Weekday.TUESDAY}, time(8, 0), time(10, 0), {4, 5, 6}, PublicSwim()),
        )
    )
    assert best_public_time(plan, Weekday.TUESDAY) == PublicWindow(
        time=TimeRange(time(6, 0), time(10, 0)), public_lanes=3
    )


def test_best_public_ties_go_to_the_earliest_window() -> None:
    # Two separate 2-lane windows (a gap between them); the earlier one wins the tie.
    plan = _plan(
        (
            _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {1, 2}, PublicSwim()),
            _res({Weekday.TUESDAY}, time(10, 0), time(12, 0), {1, 2}, PublicSwim()),
        )
    )
    assert best_public_time(plan, Weekday.TUESDAY) == PublicWindow(
        time=TimeRange(time(6, 0), time(8, 0)), public_lanes=2
    )


def test_best_public_counts_overlapping_public_reservations_as_a_union() -> None:
    # Overlapping public blocks: 07:00–08:00 has lanes {1,2,3} public → the peak window.
    plan = _plan(
        (
            _res({Weekday.TUESDAY}, time(6, 0), time(8, 0), {1, 2}, PublicSwim()),
            _res({Weekday.TUESDAY}, time(7, 0), time(9, 0), {3}, PublicSwim()),
        )
    )
    best = best_public_time(plan, Weekday.TUESDAY)
    assert best == PublicWindow(time=TimeRange(time(7, 0), time(8, 0)), public_lanes=3)


# --- best_public_time, bounded by `within` (lane-stack-board S2) -------------------------
#
# `/swim` attaches this window to a `SwimOption`, which IS one session, so it passes the
# session as `within`. `/pools`' `lane_panel` passes nothing, because a `LanePanel` is a
# per-day object. The default must therefore stay whole-day, and the bound must actually bind.


def test_best_public_within_a_session_ignores_windows_outside_it() -> None:
    # The day's best window is 08:00–10:00 (6 lanes), but a 06:00–08:00 session cannot tell
    # anyone to "come at 08:00" — inside it only the 4-lane morning window exists.
    best = best_public_time(CITY, Weekday.TUESDAY, TimeRange(time(6, 0), time(8, 0)))
    assert best == PublicWindow(time=TimeRange(time(6, 0), time(8, 0)), public_lanes=4)


def test_best_public_within_clips_a_window_starting_before_the_bound() -> None:
    # The 08:00–10:00 all-public block starts before a session opening at 09:00, so the window
    # is reported FROM the bound: a band drawn from 08:00 behind a row that opens at 09:00
    # would overhang the row.
    best = best_public_time(CITY, Weekday.TUESDAY, TimeRange(time(9, 0), time(12, 0)))
    assert best == PublicWindow(time=TimeRange(time(9, 0), time(10, 0)), public_lanes=6)


def test_best_public_within_clips_a_window_running_past_the_bound() -> None:
    # The mirror case, at the far end: the same 08:00–10:00 block runs past a session that ends
    # at 09:00, so the window must be reported as 08:00–09:00. Note the bound also KEEPS the
    # right window — the earlier 06:00–08:00 stretch is public too, but only 4 lanes.
    best = best_public_time(CITY, Weekday.TUESDAY, TimeRange(time(6, 0), time(9, 0)))
    assert best == PublicWindow(time=TimeRange(time(8, 0), time(9, 0)), public_lanes=6)


def test_best_public_within_a_session_with_no_public_lane_is_none() -> None:
    # A bound missing every public block yields None — never a zero-lane window.
    assert best_public_time(CITY, Weekday.TUESDAY, TimeRange(time(20, 0), time(22, 0))) is None


def test_best_public_without_a_bound_is_unchanged() -> None:
    # The `/pools` path: omitting `within` behaves exactly as before the parameter existed.
    assert best_public_time(CITY, Weekday.TUESDAY, None) == best_public_time(CITY, Weekday.TUESDAY)


# --- lane_panel (the aggregate the facility-detail view consumes) ------------------------


def test_lane_panel_bundles_the_three_derivations() -> None:
    panel = lane_panel(CITY, Weekday.TUESDAY)
    assert panel.day_view == lane_day_view(CITY, Weekday.TUESDAY)
    assert panel.best_public == best_public_time(CITY, Weekday.TUESDAY)
    assert panel.roster == club_roster(CITY)
