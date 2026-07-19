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
from datetime import date, datetime
from enum import Enum

from swimzh.domain.access import SessionAccess
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
