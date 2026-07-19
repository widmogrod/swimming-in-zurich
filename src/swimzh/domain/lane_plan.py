"""Lane-reservation plan (Belegungsplan): which of a basin's lanes are held by whom.

A pool's per-basin "Belegungsplan" PDF is a weekly grid of *7 days × N lanes × 30-min
slots*, each cell a legend code (public / school / a named club). These are recurring
"Dauerbelegungen" — **static**, so a parsed plan is stored in gold alongside the basin's
schedule, and refines (never overrides) the HTML-scraped eligibility with a lane count.

The representation is RLE-compressed: one `LaneReservation` per contiguous same-owner
region (a set of weekdays × a time range × a set of lanes), never a dense grid. Public
blocks are stored *explicitly* (as `PublicSwim` reservations); a blank/absent cell is
simply not represented and is never counted as public. Honesty about what was resolved
lives object-level in `PlanCoverage`, so *closed* (not represented) stays distinct from
*unknown* (unresolved). Availability is derived at query time and never stored here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from itertools import pairwise

from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved, SessionAccess
from swimzh.domain.schedule import TimeRange, Weekday


class PlanConfidence(Enum):
    """Whether every grid cell resolved to a known owner (COMPLETE) or some did not."""

    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class LaneReservation:
    """A contiguous same-owner region of the weekly grid.

    Isomorphic to a `ScheduleRule` plus a `lanes` axis. `lanes` is 1-based; both frozensets
    are serialised sorted so the gold round-trip is exact. Only `PublicSwim`,
    `SchoolReserved`, and `ClubReserved` are emitted by the parser (enforced there).
    """

    weekdays: frozenset[Weekday]
    time: TimeRange
    lanes: frozenset[int]
    access: SessionAccess


@dataclass(frozen=True, slots=True)
class PlanCoverage:
    """Object-level honesty signal for a parsed plan (the `BasinSource` precedent).

    `cells_total` / `cells_resolved` count grid cells (slots × 7 days × lanes) attempted vs
    mapped to a known owner. `unresolved_lanes` are lane indices touched by an unrecognised
    code — a queried slot on such a lane is `partial`, never silently counted as public.
    """

    confidence: PlanConfidence
    cells_total: int
    cells_resolved: int
    unresolved_lanes: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class LanePlan:
    """A basin's parsed lane-reservation plan — STORED in gold (static/recurring)."""

    lane_count: int
    reservations: tuple[LaneReservation, ...]
    valid_from: date | None
    coverage: PlanCoverage
    fetched_at: datetime | None = None


# --- Derived (query-time, DTO-free, never stored) ---------------------------------------
#
# `LaneAvailability` mirrors `LiveOccupancy`: it lives outside `models.py`/the gold codec
# (guarded by a regression test) and is attached to a `SwimOption` at query time. Unlike
# occupancy it is *not* gated to a "~now" query — it is a pure derivation of the stored,
# recurring plan, so it is meaningful for any query time (including future dates).


@dataclass(frozen=True, slots=True)
class LaneAvailability:
    """How a basin's lanes are split between public swimming and reservations at one slot.

    A pure derivation of the stored `LanePlan` — never stored, never serialised. `public_lanes`
    counts only lanes *explicitly* held by a `PublicSwim` reservation at the slot (never
    derived by complement — a blank/absent lane is not public). `public_until` is the end of
    the contiguous public run covering the slot. `partial` is True when the slot touches a
    lane the parser could not resolve (`PlanCoverage.unresolved_lanes`), so an honest badge
    can flag that the count may be incomplete.
    """

    lane_count: int
    public_lanes: int
    reserved_lanes: int
    owners: tuple[SessionAccess, ...]
    public_until: time | None
    partial: bool


def _active_reservations(plan: LanePlan, weekday: Weekday, t: time) -> tuple[LaneReservation, ...]:
    """Reservations covering (weekday, t). Lane-sets are pairwise-disjoint per slot (a parse
    invariant), so a lane appears in at most one active reservation."""
    return tuple(r for r in plan.reservations if weekday in r.weekdays and r.time.contains(t))


def _public_run_end(plan: LanePlan, weekday: Weekday, t: time) -> time | None:
    """End of the maximal contiguous window (on `weekday`) that has ≥1 public lane and
    covers `t`; `None` when no public reservation covers `t`. Adjacent public blocks
    (`prev.end == next.start`) are merged so "public until 18:00" spans several RLE rows."""
    ranges = sorted(
        (
            r.time
            for r in plan.reservations
            if weekday in r.weekdays and isinstance(r.access, PublicSwim)
        ),
        key=lambda tr: (tr.start, tr.end),
    )
    merged: list[tuple[time, time]] = []
    for tr in ranges:
        if merged and tr.start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], tr.end))
        else:
            merged.append((tr.start, tr.end))
    for start, end in merged:
        if start <= t < end:
            return end
    return None


def lane_availability_at(plan: LanePlan, weekday: Weekday, t: time) -> LaneAvailability:
    """Derive, from the stored recurring plan, how the basin's lanes are allocated at
    (`weekday`, `t`). Pure; safe for any query time including future dates."""
    active = _active_reservations(plan, weekday, t)
    public: set[int] = set()
    reserved: set[int] = set()
    owners: list[SessionAccess] = []
    for r in sorted(active, key=lambda r: min(r.lanes) if r.lanes else 0):
        if isinstance(r.access, PublicSwim):
            public |= r.lanes
        else:
            reserved |= r.lanes
            if r.access not in owners:
                owners.append(r.access)
    covered = public | reserved
    partial = any(lane not in covered for lane in plan.coverage.unresolved_lanes)
    return LaneAvailability(
        lane_count=plan.lane_count,
        public_lanes=len(public),
        reserved_lanes=len(reserved),
        owners=tuple(owners),
        public_until=_public_run_end(plan, weekday, t),
        partial=partial,
    )


# --- Facility-detail derivations (pure; DTO-free, never stored) --------------------------
#
# Three richer projections of the SAME stored `LanePlan` for the facility-detail panel — a
# per-lane day timeline, the club roster, and the "best time to come" public window. Like
# `LaneAvailability` they invent no data: a lane's day is exactly its stored reservations,
# and public lanes are always counted explicitly (a blank slot is never made public).


@dataclass(frozen=True, slots=True)
class LaneSegment:
    """One owner's hold on a single lane for a time range — a cell of a lane's day strip."""

    time: TimeRange
    access: SessionAccess


@dataclass(frozen=True, slots=True)
class LaneStrip:
    """One lane's day: its reservations for the weekday, sorted by start. Gaps are left
    implicit (a blank slot is simply absent, never invented as public)."""

    lane: int
    segments: tuple[LaneSegment, ...]


@dataclass(frozen=True, slots=True)
class LaneDayView:
    """A per-lane timeline for one weekday — one `LaneStrip` per lane ``1..lane_count``."""

    weekday: Weekday
    lane_count: int
    strips: tuple[LaneStrip, ...]


@dataclass(frozen=True, slots=True)
class ClubSlot:
    """One owner's standing reservation on one weekday: who, when, and which lanes.

    A single `LaneReservation` spanning several weekdays expands into one `ClubSlot` per
    weekday, so the roster reads as "ASVZ: Tue 06:00–08:00, lanes 1–2"."""

    club: str
    weekday: Weekday
    time: TimeRange
    lanes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PublicWindow:
    """A time range during which `public_lanes` lanes are open to the public."""

    time: TimeRange
    public_lanes: int


@dataclass(frozen=True, slots=True)
class LanePanel:
    """The facility-detail lane panel for one basin on one weekday: the per-lane day
    timeline, the "best time to come" public window, and the club roster. All three are
    pure derivations of the one stored `LanePlan` — no new sourced data."""

    day_view: LaneDayView
    best_public: PublicWindow | None
    roster: tuple[ClubSlot, ...]


def owner_label(access: SessionAccess) -> str:
    """A short display name for a non-public reservation's owner (the roster/timeline label).
    `ClubReserved` shows its club; `SchoolReserved` shows "Schools"; any other arm falls back
    to its type name (the parser only ever emits club/school/public)."""
    if isinstance(access, ClubReserved):
        return access.club or "Club"
    if isinstance(access, SchoolReserved):
        return "Schools"
    return type(access).__name__


def lane_day_view(plan: LanePlan, weekday: Weekday) -> LaneDayView:
    """Split the stored plan into one time-ordered strip per lane for `weekday`. Every lane
    ``1..lane_count`` gets a strip (empty when the lane has no reservation that day)."""
    strips: list[LaneStrip] = []
    for lane in range(1, plan.lane_count + 1):
        segments = sorted(
            (
                LaneSegment(time=r.time, access=r.access)
                for r in plan.reservations
                if weekday in r.weekdays and lane in r.lanes
            ),
            key=lambda s: (s.time.start, s.time.end),
        )
        strips.append(LaneStrip(lane=lane, segments=tuple(segments)))
    return LaneDayView(weekday=weekday, lane_count=plan.lane_count, strips=tuple(strips))


def club_roster(plan: LanePlan) -> tuple[ClubSlot, ...]:
    """Every non-public reservation grouped by owner: one `ClubSlot` per (owner, weekday),
    sorted by owner then weekday then time so same-club rows sit together. Public blocks are
    excluded (they are not a reservation *of* anyone)."""
    slots: list[ClubSlot] = []
    for r in plan.reservations:
        if isinstance(r.access, PublicSwim):
            continue
        label = owner_label(r.access)
        lanes = tuple(sorted(r.lanes))
        slots.extend(
            ClubSlot(club=label, weekday=weekday, time=r.time, lanes=lanes)
            for weekday in sorted(r.weekdays)
        )
    slots.sort(key=lambda s: (s.club, s.weekday, s.time.start, s.time.end, s.lanes))
    return tuple(slots)


def best_public_time(plan: LanePlan, weekday: Weekday) -> PublicWindow | None:
    """The "best time to come": the window with the MOST public lanes free (while ≥1 is
    public) on `weekday`, or `None` if no lane is ever public that day. Ties go to the
    earliest window. Public-lane count only changes at a public reservation's boundary, so
    the day is cut at those boundaries and adjacent equal-count cuts are merged."""
    publics = [
        r for r in plan.reservations if weekday in r.weekdays and isinstance(r.access, PublicSwim)
    ]
    if not publics:
        return None
    bounds = sorted({r.time.start for r in publics} | {r.time.end for r in publics})
    windows: list[PublicWindow] = []
    for lo, hi in pairwise(bounds):
        lanes: set[int] = set()
        for r in publics:
            if r.time.start <= lo and hi <= r.time.end:
                lanes |= r.lanes
        count = len(lanes)
        if count == 0:  # a gap with no public lanes — never a "best time"
            continue
        if windows and windows[-1].public_lanes == count and windows[-1].time.end == lo:
            windows[-1] = PublicWindow(TimeRange(windows[-1].time.start, hi), count)
        else:
            windows.append(PublicWindow(TimeRange(lo, hi), count))
    if not windows:
        return None
    # `max` returns the FIRST maximal item; `windows` is chronological, so ties give the
    # earliest window without a second sort key.
    return max(windows, key=lambda w: w.public_lanes)


def lane_panel(plan: LanePlan, weekday: Weekday) -> LanePanel:
    """Assemble the full facility-detail lane panel (day timeline + best public window +
    club roster) for one basin's plan on `weekday`."""
    return LanePanel(
        day_view=lane_day_view(plan, weekday),
        best_public=best_public_time(plan, weekday),
        roster=club_roster(plan),
    )
