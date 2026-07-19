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

from swimzh.domain.access import PublicSwim, SessionAccess
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
