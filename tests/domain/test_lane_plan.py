"""Query-time derivation `lane_availability_at`: a pure projection of the stored recurring
`LanePlan` into a per-slot lane-availability glance. Public lanes are counted EXPLICITLY
(never by complement), `public_until` spans contiguous public runs, and a slot touching an
unresolved lane is honestly flagged `partial`.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved
from swimzh.domain.lane_plan import (
    LaneAvailability,
    LanePlan,
    LaneReservation,
    PlanConfidence,
    PlanCoverage,
    lane_availability_at,
)
from swimzh.domain.schedule import TimeRange, Weekday


def _plan(
    reservations: tuple[LaneReservation, ...],
    *,
    lane_count: int = 6,
    unresolved: frozenset[int] = frozenset(),
    confidence: PlanConfidence = PlanConfidence.COMPLETE,
) -> LanePlan:
    return LanePlan(
        lane_count=lane_count,
        reservations=reservations,
        valid_from=date(2026, 1, 1),
        coverage=PlanCoverage(
            confidence=confidence,
            cells_total=1344,
            cells_resolved=1344,
            unresolved_lanes=unresolved,
        ),
    )


# City Tue 06:00 (from the plan's Context): lanes 1–2 held by clubs, 3–6 public.
CITY_TUE = _plan(
    (
        LaneReservation(
            weekdays=frozenset({Weekday.TUESDAY}),
            time=TimeRange(time(6, 0), time(8, 0)),
            lanes=frozenset({1}),
            access=ClubReserved(club="ASVZ"),
        ),
        LaneReservation(
            weekdays=frozenset({Weekday.TUESDAY}),
            time=TimeRange(time(6, 0), time(8, 0)),
            lanes=frozenset({2}),
            access=ClubReserved(club="Swimatic"),
        ),
        LaneReservation(
            weekdays=frozenset({Weekday.TUESDAY}),
            time=TimeRange(time(6, 0), time(8, 0)),
            lanes=frozenset({3, 4, 5, 6}),
            access=PublicSwim(),
        ),
    )
)


def test_counts_explicit_public_and_reserved_lanes() -> None:
    avail = lane_availability_at(CITY_TUE, Weekday.TUESDAY, time(6, 30))
    assert avail == LaneAvailability(
        lane_count=6,
        public_lanes=4,
        reserved_lanes=2,
        owners=(ClubReserved(club="ASVZ"), ClubReserved(club="Swimatic")),
        public_until=time(8, 0),
        partial=False,
    )


def test_blank_lane_is_never_counted_as_public() -> None:
    # Only lanes 3–4 are explicitly public; lanes 5–6 are blank (not represented). public_lanes
    # must be 2, NOT 6 minus the reserved lanes — a blank lane is not public.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.MONDAY}),
                time=TimeRange(time(12, 0), time(13, 0)),
                lanes=frozenset({1}),
                access=SchoolReserved(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.MONDAY}),
                time=TimeRange(time(12, 0), time(13, 0)),
                lanes=frozenset({3, 4}),
                access=PublicSwim(),
            ),
        )
    )
    avail = lane_availability_at(plan, Weekday.MONDAY, time(12, 30))
    assert avail.public_lanes == 2  # explicit, not 6 - 1 reserved
    assert avail.reserved_lanes == 1


def test_no_reservation_at_slot_yields_zero() -> None:
    avail = lane_availability_at(CITY_TUE, Weekday.TUESDAY, time(9, 0))
    assert avail.public_lanes == 0
    assert avail.reserved_lanes == 0
    assert avail.owners == ()
    assert avail.public_until is None
    assert avail.partial is False


def test_other_weekday_sees_no_reservations() -> None:
    avail = lane_availability_at(CITY_TUE, Weekday.WEDNESDAY, time(6, 30))
    assert avail.public_lanes == 0
    assert avail.reserved_lanes == 0


def test_public_until_merges_adjacent_public_runs() -> None:
    # Two back-to-back public blocks (06:00–08:00, 08:00–10:00) form one contiguous run to 10:00.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2, 3}),
                access=PublicSwim(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(8, 0), time(10, 0)),
                lanes=frozenset({1, 2}),
                access=PublicSwim(),
            ),
        )
    )
    assert lane_availability_at(plan, Weekday.TUESDAY, time(6, 30)).public_until == time(10, 0)
    assert lane_availability_at(plan, Weekday.TUESDAY, time(9, 0)).public_until == time(10, 0)


def test_public_until_does_not_bridge_a_gap() -> None:
    # A gap (08:00–09:00 has no public) breaks the run: the 06:00 slot's run ends at 08:00.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
                access=PublicSwim(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(9, 0), time(11, 0)),
                lanes=frozenset({1, 2}),
                access=PublicSwim(),
            ),
        )
    )
    assert lane_availability_at(plan, Weekday.TUESDAY, time(6, 30)).public_until == time(8, 0)
    assert lane_availability_at(plan, Weekday.TUESDAY, time(8, 30)).public_until is None
    assert lane_availability_at(plan, Weekday.TUESDAY, time(9, 30)).public_until == time(11, 0)


def test_partial_when_slot_touches_an_unresolved_lane() -> None:
    # Lane 5 is unresolved (an unrecognised code). At a slot where lane 5 has no resolved
    # reservation, the derivation is honestly `partial` — never silently counted as public.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1, 2}),
                access=PublicSwim(),
            ),
        ),
        unresolved=frozenset({5}),
        confidence=PlanConfidence.PARTIAL,
    )
    avail = lane_availability_at(plan, Weekday.TUESDAY, time(6, 30))
    assert avail.partial is True
    assert avail.public_lanes == 2  # unresolved lane 5 is not counted as public


def test_not_partial_when_the_unresolved_lane_is_resolved_at_this_slot() -> None:
    # Lane 1 appears in unresolved_lanes (some OTHER slot had a bad code), but at THIS slot it
    # is covered by a resolved reservation — so this slot is not partial.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1}),
                access=ClubReserved(club="ASVZ"),
            ),
        ),
        unresolved=frozenset({1}),
        confidence=PlanConfidence.PARTIAL,
    )
    assert lane_availability_at(plan, Weekday.TUESDAY, time(6, 30)).partial is False


def test_owners_are_distinct_non_public_and_lane_ordered() -> None:
    # Two lanes held by the same club collapse to one owner; public is excluded from owners.
    plan = _plan(
        (
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({3, 4}),
                access=ClubReserved(club="ASVZ"),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({1}),
                access=SchoolReserved(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(time(6, 0), time(8, 0)),
                lanes=frozenset({5, 6}),
                access=PublicSwim(),
            ),
        )
    )
    avail = lane_availability_at(plan, Weekday.TUESDAY, time(7, 0))
    # Ordered by first lane: School on lane 1, then ASVZ on lanes 3–4.
    assert avail.owners == (SchoolReserved(), ClubReserved(club="ASVZ"))
    assert avail.reserved_lanes == 3


@pytest.mark.parametrize(
    ("t", "expected_public"),
    [(time(5, 59), 0), (time(6, 0), 4), (time(7, 59), 4), (time(8, 0), 0)],
)
def test_slot_boundaries_are_half_open(t: time, expected_public: int) -> None:
    # TimeRange.contains is [start, end): 06:00 is in, 08:00 is out.
    assert lane_availability_at(CITY_TUE, Weekday.TUESDAY, t).public_lanes == expected_public
