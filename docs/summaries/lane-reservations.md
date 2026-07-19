---
type: summary
feature: lane-reservations
plan: "[[2026-07-19-lane-reservations-plan]]"
status: done
updated: 2026-07-19
---

# Lane reservations

Parses Zürich pool **Belegungsplan PDFs** (per-basin weekly lane grids) into a stored
`LanePlan`, and derives — at query time, never stored — "how many lanes are free for the
public right now/at time T", the per-lane day timeline, the best public time, and the club
roster. Answers the highest-value question for City's 6-lane Schwimmerbecken.

## Shape

- **Stored** (`domain/lane_plan.py`, persists via codec on `Basin.lane_plan`):
  `LanePlan(lane_count, reservations: tuple[LaneReservation], valid_from, coverage, fetched_at)`;
  `LaneReservation(weekdays: frozenset[Weekday], time: TimeRange, lanes: frozenset[int],
  access: SessionAccess)` — reuses `SessionAccess` (public→`PublicSwim`, schools→`SchoolReserved`,
  club→`ClubReserved(name)`); **public blocks are stored explicitly** so a blank cell is never
  counted public. `PlanCoverage(confidence, unresolved_lanes, …)` is the object-level honesty
  signal (no `Fact[T]`).
- **Derived** (pure, never serialized — same guard as live occupancy):
  `lane_availability_at` → `LaneAvailability`; `lane_day_view` → `LaneDayView`; `club_roster`;
  `best_public_time` → `PublicWindow`.

## Pipeline

`providers/belegungsplan.py` (pdfplumber, optional `[pdf]` extra, lazy import) fetch→parse→
`Result[ParsedPlan(basin_hint, plan), ProviderError]`. **Disjointness invariant** (half-open;
skip ⊆ bound when lanes unknown) catches column mis-segmentation → `ParseError`. Errors reuse
the closed union (unreadable→`ParseError`, layout→`SchemaMismatch`, missing dep→`ProviderSpecific`,
low coverage→`Ok`+`PARTIAL`). `etl/silver.py attach_lane_plans` reconciles `basin_hint` to a
`Basin` (facility+basin granular, lookup-not-fuzzy, loud on no-match, never wrong-basin) and
stamps `fetched_at`. CLI `scrape-lanes` builds it into gold. Query attaches
`SwimOption.lane_availability` (ungated — recurring) and `FacilityDetail.lane_panels`; surfaced
via a `/swim` badge and `GET /pools/{id}` + a UI lane-schedule panel.

## Key decisions (design→2 agents→2 critics)

- **Overlay, not replace:** scraped HTML `ScheduleRule`s stay authoritative for eligibility;
  the plan only refines the lane count; divergence → a warning, never an overwrite (a bad
  parse degrades a badge, not an eligibility answer).
- Reuse `SessionAccess`; per-owner `LaneReservation` rows (not per-lane / dense grid).
- Availability derived per query (works for future dates), never stored.

## Not done / backlog

Real per-pool Belegungsplan URLs unverified (only a pinned City fixture drives tests — no
curated pool carries a plan in production yet); `scrape-lanes` needs a `build-gold` (curated)
store, not a `scrape-gold` one; the general `/pools/{id}` route surfaces only the lane panel so
far (features/lockers/website from `facility_detail()` still unwired); owner label-vs-known-set
reconciliation. See the plan ledger for per-slice detail.
