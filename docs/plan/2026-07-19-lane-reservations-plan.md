---
type: plan
status: in-progress         # design→2 agents→2 critics→synthesis; executing via /dev:implement
created: 2026-07-19
feature: lane-reservations
gates:
  qa: full                  # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial       # critic subagent must find no blocking issues
pause_after: [S1]           # parser + model + invariants is the riskiest slice — human review before fan-out
links: ["[[basin]]", "[[lane-plan]]", "[[schedule-rule]]"]
---

# Plan — Lane reservations (Belegungsplan PDF → "how many lanes are free for the public")

Design by 2 design sub-agents (experience-max + clean-integration) → 2 critic agents
(correctness/integration + complexity/experience) → this synthesis. Net verdict:
**ship the clean-minimal storage, spend the richness budget on cheap pure derivations.**

## Context

The most useful missing signal for Hallenbad City (and every city indoor pool) is **which of
the pool's lanes are free for public swimming at a given time** — most valuable of all for
City's 50 m / 6-lane Schwimmerbecken. This is published *only* as per-basin PDF
"Belegungspläne" (`.../belegungsplaene/city-schwimmerbecken.pdf`): a weekly grid of
**7 days × N lanes × 30-min slots (06:00–22:00)**, each cell a legend code (1 =
Öffentlichkeit/public, 2 = Schulen, 3..N = named clubs). Header carries the lane count
("6 Bahnen") and a valid-from date; these are recurring "Dauerbelegungen" → **static**, not
live. Feasibility is proven end-to-end (pdfplumber reconstructs the 42-cell grid by
coordinate; e.g. City Tue 06:00 = 4/6 public, lanes 1–2 held by ASVZ + Swimatic). No API /
Open Data / iCal alternative exists — the PDF is canonical.

## Decisions (adjudicated)

| # | Question | Verdict |
|---|----------|---------|
| 1 | Group/owner typing | **Reuse `SessionAccess`** (public→`PublicSwim`, schools→`SchoolReserved`, club→`ClubReserved(name)`). No new `LaneGroup` union. Do **not** overload `LaneSwim`. Constrain emitted arms to `{PublicSwim, SchoolReserved, ClubReserved}` at parse time (invariant), so gold can't hold a nonsense lane like `WomenOnly`. |
| 2 | "Closed"/blank cell | **Store public blocks explicitly** (as `PublicSwim` reservations). A blank/absent cell is therefore simply *not represented* and is **never counted as public** (no over-count) — so no `Closed`/`LaneUse` union is needed in v1. Add one only if a real fixture shows blank-closed cells. |
| 3 | Row shape | **`LaneReservation(weekdays: frozenset[Weekday], time: TimeRange, lanes: frozenset[int], access: SessionAccess)`** — isomorphic to `ScheduleRule` + a `lanes` axis. RLE-compressed (one row per contiguous same-owner region), never a dense 7×32×N store. |
| 4 | Availability | **Derived at query time, never stored.** `SwimOption.lane_availability: LaneAvailability | None` mirrors `live_occupancy` (attached under the same "~now" gating; kept OUT of `models.py`/codec by the existing regression guard). |
| 5 | Integration | **Overlay / additive.** Scraped HTML `ScheduleRule`s stay authoritative for eligibility; the plan only *refines* with a lane count. Divergence → a `QueryResult.warnings` string, never an overwrite (fail-safe: a bad parse degrades a badge, not an eligibility answer). |
| 6 | Segmentation guard | **Disjointness invariant**: for each (weekday, slot) the reservation lane-sets must be pairwise-disjoint (**half-open** overlap: `a.start < b.end and b.start < a.end`) and ⊆ `{1..N}` (**skip the ⊆ check when `Basin.lanes is None`**). Violation ⇒ segmentation is corrupt ⇒ `Err(ParseError)` (skip the pool; overlay is optional so this degrades gracefully). |
| 7 | Coverage/honesty | **`PlanCoverage(confidence: COMPLETE|PARTIAL, unresolved_lanes, cells_total, cells_resolved)`** — object-level (the `BasinSource` precedent), not per-cell `Fact[T]`. Preserves closed≠unknown. A queried slot touching an unresolved lane → `LaneAvailability.partial=True`. |
| 8 | Basin↔PDF mapping | Provider returns a **`basin_hint`** (PDF header name); **`etl/silver.py` reconciles** it to the right `Basin` (facility+basin granular, lookup-not-fuzzy, loud failure) — never a hardcoded id in provider config. `classify_fn` + `GridSpec` tolerances stay **provider-local**. |
| 9 | Dependency | **`pdfplumber` as an optional extra** `[project.optional-dependencies] pdf`, **lazy-imported** in the provider (missing → `ProviderSpecific`). `pypdf` rejected (no reliable per-word x/y). |

## Model (new module `domain/lane_plan.py`, pure)

```python
class PlanConfidence(Enum): COMPLETE = "complete"; PARTIAL = "partial"

@dataclass(frozen=True, slots=True)
class LaneReservation:
    weekdays: frozenset[Weekday]
    time: TimeRange
    lanes: frozenset[int]          # 1-based; sorted on serialize (exact round-trip)
    access: SessionAccess          # only PublicSwim | SchoolReserved | ClubReserved emitted

@dataclass(frozen=True, slots=True)
class PlanCoverage:
    confidence: PlanConfidence
    cells_total: int
    cells_resolved: int
    unresolved_lanes: frozenset[int] = frozenset()

@dataclass(frozen=True, slots=True)
class LanePlan:                    # STORED in gold (static/recurring)
    lane_count: int                # N from header — never assumed
    reservations: tuple[LaneReservation, ...]
    valid_from: date | None
    coverage: PlanCoverage
    fetched_at: datetime | None = None

# Basin gains ONE optional field:  lane_plan: LanePlan | None = None
```

### Derived (query-time, DTO-free, never stored)
```python
@dataclass(frozen=True, slots=True)
class LaneAvailability:            # on SwimOption, like live_occupancy
    lane_count: int
    public_lanes: int              # count of lanes in PublicSwim reservations at the slot
    reserved_lanes: int
    owners: tuple[SessionAccess, ...]   # distinct non-public owners active now
    public_until: time | None      # end of the current public run (static "public until 18:00")
    partial: bool

def lane_availability_at(plan: LanePlan, weekday: Weekday, t: time) -> LaneAvailability: ...

# Facility-detail (pure derivations — no new sourced data):
def lane_day_view(plan, weekday) -> LaneDayView          # per-lane timeline strips
def club_roster(plan) -> tuple[ClubSlot, ...]            # groupby owner
def best_public_time(plan, weekday) -> PublicWindow | None  # max free lanes while >=1 public
```

## Provider (`providers/belegungsplan.py`, mirrors `schedule_scraper.py`)

`fetch_plan(client, url) -> Result[bytes, ProviderError]` · `parse_belegungsplan(pdf_bytes)
-> Result[ParsedPlan, ProviderError]` (where `ParsedPlan(basin_hint, plan)`) ·
`scrape_belegungsplan(client, url)`. Parse: lazy `import pdfplumber` → words with bboxes →
read header (basin name, N, valid_from) + legend (code→`SessionAccess`) → segment grid by
x into N×7 columns / y into slot rows (`GridSpec` tolerances) → cell→code→access → **RLE**
into `LaneReservation`s → run invariants → compute `PlanCoverage`.

**Error mapping (zero new `ProviderError` variants):** undecodable/no-text PDF → `ParseError`
(its docstring names "unreadable PDF"); missing `pdfplumber` → `ProviderSpecific`; header/
legend/grid missing or layout changed → `SchemaMismatch`; disjointness/⊆ violation →
`ParseError`; **low-but-nonzero coverage → `Ok` + `PlanCoverage.PARTIAL`** (never an error —
"empty-but-valid is Ok"); fetch errors propagate from `HttpClient`.

**Owner-relabel trap:** the disjointness guard catches lane *overlap*, not a misread owner
label. So reconcile club/school labels against the pool's known legend set; an unrecognized
label → treat that lane as **unresolved (partial) + a warning**, never as public.

## Serialization (small, additive)

`curated_dto.py`: `+LaneReservationDTO` (lanes `list[int]`, weekdays reuse `_Weekday`,
**access reuses the existing `AccessDTO` discriminated union** — no new access codec),
`+PlanCoverageDTO`, `+LanePlanDTO`; `BasinDTO.lane_plan: LanePlanDTO | None = None` (optional
→ old rows valid). `mapping.py`: `+lane_reservation_*`, `+lane_plan_*` (reuse `access_*_dto`,
`_WEEKDAY_*`, `time_range`), thread through `basin_*_dto`. `storage/codec.py`: no structural
change (delegates basins). **Serialize both frozensets sorted** or the round-trip test flaps.

## Correctness traps (from critics — guard each)

1. **Ownership relabel** (disjoint but wrong owner) → reconcile labels vs known set; unknown → partial + warning, never public.
2. **Three-way blank collapse**: public / not-in-use / unresolved must stay distinct — public is *explicit*, unknown is `PlanCoverage`, absent is neither counted nor invented.
3. **Two opposite codec guards**: STORED `LanePlan` *must* round-trip (test a basin carrying a plan, sorted frozensets); DERIVED `LaneAvailability` must *never* enter `models.py`/codec (regression guard mirroring `live_occupancy`).
4. **Overlay staleness**: carry `valid_from`; warn if it predates the schedule's `valid_as_of`.
5. **Wrong-basin attachment**: basin-granular loud reconcile in silver.
6. **False-positive pool drops**: half-open overlap check; skip ⊆ bound when `Basin.lanes is None`.
7. **Optional-dep QA**: test the missing-`pdfplumber` branch (monkeypatch import → `ProviderSpecific`) so it isn't an uncovered CRAP line; add mypy `ignore_missing_imports` for pdfplumber.

## Experience scope

**v1 (build now — all pure derivations of the one stored plan):**
- **Glance** on `SwimOption`: `LaneAvailability` (public/reserved counts, `owners`, `public_until`, `partial`), attached at query-time under the `live_occupancy` gating; rendered as a badge on `/swim` cards + the week-planner grid. "5/6 lanes public · until 18:00".
- **Facility-detail panel** (existing `/pools/{id}` / facility detail, no new route): per-lane **day timeline** (strips), **best public time** badge, **club roster** ("ASVZ: Tue 06:00–08:00, lanes 1–2").

**v2 / deferred:** step-function availability sparkline; glance-level `per_lane` tuple; ticking countdown; a `LaneClosed`/`LaneUse` union (only when a fixture demands); a dedicated `/pools/{id}/lanes` endpoint.

## Slices (for /dev:implement)

- **S1 — model + parser + provider + codec (riskiest; pause after).** `domain/lane_plan.py`
  (`LaneReservation`/`PlanCoverage`/`LanePlan`), `Basin.lane_plan`, DTO+mapping+codec
  round-trip, `providers/belegungsplan.py` with the invariants + error mapping, `pdfplumber`
  optional extra. Fixture: committed `city-schwimmerbecken.pdf` → assert `lane_count==6`,
  `valid_from`, a known club owns a known lane/slot; partial/ambiguous/missing-dep tests.
- **S2 — silver reconcile + gold + CLI.** Basin-granular hint reconcile in `etl/silver.py`;
  attach plans; `scrape-gold` (or a `scrape-lanes`) fetches the per-basin PDFs for city pools.
- **S3 — query-time glance.** `lane_availability_at` + `SwimOption.lane_availability` +
  regression guard (never serialized); `/swim` badge.
- **S4 — facility-detail rich views.** `lane_day_view` / `club_roster` / `best_public_time`
  derivations + the facility-detail panel (timeline, best-time, roster).

## Rejected (don't relitigate)
- New `LaneGroup` union / `group_to_access` bridge — reuse `SessionAccess`.
- Per-lane `LaneBlock` rows / dense grid store — use per-owner `LaneReservation` (RLE).
- Making the plan the *sole* source of the public schedule — a mis-parse would flip eligibility; keep HTML authoritative, plan refines.
- Per-cell `Fact[T]` — object-level `PlanCoverage` only.
- `pypdf` — no reliable per-word coordinates.
- Sparkline / countdown / glance per-lane / dedicated lanes endpoint — v2.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| 2026-07-19 | S1 | done | Orchestrator reverted out-of-scope `apps/web` UI changes the implementer introduced (unrelated "all-pools hub"); parser derives grid rows (32 filled slots) instead of assuming; `fetched_at` stamped in S2 | unknown-owner-label warning string not surfaced (query-time, S3); `GridSpec` tolerances calibrated to City layout only; label-vs-known-set reconciliation not implemented (code-absent-from-legend triggers unresolved, not a garbled label) | yes |
| 2026-07-19 | S2 | done | none on contract; reconcile index model-derived (not hardcoded ids); best-effort fetch/parse skip vs loud-Err on unreconcilable parsed hint; geo reconcile untouched | `CITY_BELEGUNGSPLAN_URLS` is a single unverified/guessed URL — real per-pool URLs need verifying before live use; `scrape-lanes` needs a `build-gold` store (curated `BasinKind`/names), won't reconcile against a `scrape-gold` "Hauptbecken/OTHER" store; duplicate hints resolving to the same basin overwrite silently (no warning) | yes |
| 2026-07-19 | S3 | done | `lane_availability` attached **ungated** (not ~now) — the adjudicated-correct reading, since the plan is recurring and applies to any query time; plan #4's "~now gating" wording is loose | `find_swim_options` complexity rising (CRAP=23, CC=23, still < 30); `partial` is plan-level approximate (`unresolved_lanes` has no per-slot time → conservative over-flag, never under-flag); UI badge test asserts JS source substrings, not rendered output | no |
| 2026-07-19 | S4 | done | Added `GET /pools/{facility_id}` general facility-detail route despite plan's "no new route" — no facility-detail HTTP surface existed (`facility_detail()` was never wired); critic confirmed it's the general detail route (extensible to full detail), NOT the rejected `/pools/{id}/lanes` | Facility-detail route currently projects only `lane_panels` (website/features/lockers/basins from `facility_detail()` still unsurfaced — follow-up slice); `best_public_time` CC=16; detail endpoint accepts naive `at` (weekday only); UI verified via JS-source substrings | yes |

## Decisions & divergences

### 2026-07-19 — S1 (model + parser + provider + codec)
- **Blocking review finding, resolved:** the slice-implementer's tree carried unrelated
  `apps/web/api/ui/router.py` + `test_ui.py` changes ("all-pools hub", 0 lane references).
  Orchestrator reverted both to HEAD so the S1 commit is lane-reservations-only; QA re-run
  green (196 passed, 94.72% coverage). Flagged for human review.
- Parser derives the grid row count from the actual digit grid (32 filled slot rows,
  06:00–22:00), skipping the unconstructable "24:00" label; `cells_total = 32×7×6 = 1344`.
- `pdfplumber` added to the dev group (tests need it installed) in addition to the `[pdf]`
  extra; the missing-dep branch is exercised by monkeypatching `sys.modules`; import stays
  lazy and the extra remains the production path.
- Non-blocking, deferred: the ⊆-bound invariant is present but a tautology for parser-built
  grids (the `Basin.lanes is None` skip belongs to S2/silver, which has the `Basin`);
  unrecognized-label warning strings surface at query time (S3).

### 2026-07-19 — S2 (silver reconcile + gold + CLI)
- `attach_lane_plans` reconciles the PDF `basin_hint` to a `Basin` via a model-derived index
  (facility name/alias × basin name / `BasinKind` German word), exact-normalised; ambiguity or
  no-match → loud `Err(SchemaMismatch)` naming the offender (never a wrong-basin attach). The
  wrong-basin negative is tested (City "Schwimmerbecken" hint lands on the 50m basin; the
  teaching basin stays `None`). The facility-level geo `reconcile` is untouched.
- `fetched_at` stamped here (S1 left it `None`); staleness warning fires for the committed
  fixture (Jan `valid_from` vs Jul schedule `valid_as_of`) — correct.
- New `scrape-lanes` CLI: reads a gold store, best-effort fetches/parses per-basin PDFs,
  reconciles loudly, rewrites gold. Critic verdict **approve** (QA independently reproduced).
- Tech debt (see ledger): real per-pool Belegungsplan URLs unverified; `scrape-lanes` needs a
  `build-gold` (curated) store — the `scrape-gold` path's single `Hauptbecken/OTHER` basins
  won't reconcile. Unifying the two gold-build paths is out of S2 scope.

### 2026-07-19 — S4 (facility-detail rich views)
- Pure derivations `lane_day_view` / `club_roster` / `best_public_time` (+ result types)
  added to `domain/lane_plan.py`; `query.py` `FacilityDetail` gains `lane_panels`. No codec /
  stored-type change — the "derived never stored" invariant holds (guard still green).
- **Divergence (critic-approved):** the plan assumed an existing `/pools/{id}` detail route to
  fold into; none existed (`facility_detail()` was never HTTP-wired). Added `GET
  /pools/{facility_id}` — the *general* detail route (extensible to the full `FacilityDetail`),
  explicitly not the rejected dedicated `/pools/{id}/lanes` endpoint. UI: a lazy-loaded "Lane
  schedule this week" expander (timeline strips + best-time badge + club roster).
- Discovered: the rich-pool-domain `facility_detail()` (website/features/lockers/physicals)
  still has no HTTP/UI surface — only the lane panel is exposed. A follow-up slice can
  serialize the full detail through the now-existing route + response model.
