---
type: plan
status: draft            # draft -> approved -> in-progress -> done
created: 2026-07-21
feature: richer-data-fidelity
gates:
  qa: full               # ruff, format, mypy strict, pytest+coverage floor (95), CRAP
  review: adversarial
pause_after: [D]         # D is the fidelity-preserving model/schema change — human-review before the parser rewrite (E) builds on it
links: ["[[techdebt-remediation-roadmap]]", "[[gold-store]]", "[[data-layer-architecture]]"]
---

# Plan — Extract more, lose nothing in the model, surface in the UI

## Context

Output of a 4-agent research panel (lane-data coverage · data-model fidelity · rich-data/UI). Theme
(owner's words): **increase precision, extract as much data as can be extracted, never lose it in the
data model, and leverage it in the UI/UX.**

Key research finding — the domain core is **already lossless where it exists**: `LanePlan`
(`domain/lane_plan.py`) stores the full weekly grid as RLE `LaneReservation`s (weekdays × `TimeRange` ×
lanes × owner), and `lane_availability_at(plan, weekday, t)` already derives the split at ANY instant.
The gold codec round-trips the whole `Facility` tree faithfully (incl. `LanePlan.fetched_at` — the
"dropped on round-trip" worry is **stale**, verified). **The fidelity loss is at three seams, not
storage:**

1. **Extraction is City-only.** `providers/belegungsplan.py` hard-codes A4 pixel bands
   (`GridSpec.central_x=(70,645)`, `_segment_grid` needs exactly 7×`lane_count` columns) → **1 of 8** live
   basin PDFs parses; `etl/lane_plans.py` doesn't even list 3 pools (Leimbach, Bläsi, Käferberg).
2. **Query-time collapse.** `query.py` evaluates each option at `session.time.start` → a 06:00–22:00
   public session reports identical lane counts at 12:00 and 18:00 — the timeline the model holds is
   discarded at the call site.
3. **API-boundary collapse.** `domain.facility_detail` computes basins, features (resolved hours),
   lockers, provenance — but `FacilityDetailOut` exposes only id/name/address/website/lane_panels. Water
   temperature, basin size, sauna, lockers, prices exist in the store and never reach the swimmer.
   Separately, `parse_infrastruktur`/`apply_physicals` (`providers/infrastruktur.py`) are **dead code**
   (no build call site) — 53 non-curated pools' prose physicals are never extracted.

## Invariants to preserve

Errors are typed values (`Result[..., ProviderError]`, `match` + `assert_never`); one gold DB is the
only runtime source (no `apps/web/**` reads `data/`); `PoolId` minted only in `build/reconcile` +
`build/seed` (`reconstruct_pool_id` the single re-wrap door); availability/timeline are **derived at
read, never stored** (regression-guarded, like `LiveOccupancy`); domain stays pure; routers stay thin.

## Design (signature altitude)

**Query-time timeline — pure derivation, no model/storage change (Slice B).** In `domain/lane_plan.py`,
mirroring the existing `lane_panel` derivations:
```
LaneSlotAvailability(time: TimeRange, availability: LaneAvailability)
LaneAvailabilityTimeline(weekday: Weekday, segments: tuple[LaneSlotAvailability, ...])
lane_availability_timeline(plan, weekday, within: TimeRange) -> LaneAvailabilityTimeline
    # cut at every reservation boundary within `within`; evaluate lane_availability_at() per sub-window
```
Keep `lane_availability_at(plan, weekday, t)` as the point primitive. In `query.py`, clamp the point
eval into the queried moment (`t = now if session.time.contains(now) else session.time.start`) and
attach the timeline to `SwimOption` (derived, not stored).

**Fidelity-preserving model change — ADDITIVE (Slice D, prereq for E).** Today `LanePlan.lane_count:int`
+ `LaneReservation.lanes: frozenset[int]` can't represent movable-floor basins (Vario/Käferberg run e.g.
4 lanes weekdays / 3 weekends) nor Oerlikon's named "Teil 1/Teil 2" sections. Extend so existing plans
are unchanged (new fields default `None`):
```
LanePlan.lanes_by_weekday: Mapping[Weekday, int] | None = None   # ragged floors; None = uniform lane_count
LaneReservation.section: str | None = None                       # "Teil 1" when the sheet names sections
```
Mirror both through `boundary/curated_dto.py`, `boundary/mapping.py`, `storage/codec.py`; the round-trip
test guards exactness.

**Richer facility fields — ADDITIVE, lockstep (Slice F).** `Basin.measured_temp_c: Decimal | None`
(distinct from `nominal_temp_c`, tagged by `physical_source`) + `Basin.diving_platforms_m`; grow
`FeatureKind` (terrace/rest/gastronomy) or a free `Feature.note`; `Facility.accessibility: str | None`,
`Facility.last_admission_before: timedelta | None` — each with matching DTO + mapping + codec.

**Extraction targets.** (A) add `leimbach`/`blaesi`/`kaeferberg` + both Oerlikon slugs to
`CITY_BELEGUNGSPLAN_URLS`. (E) replace `_segment_grid`'s global 7×lane_count rectangle with per-weekday
columns under DETECTED weekday x-anchors; make `GridSpec` **page-relative** (anchor off the weekday-row
span + page width, not absolute A4 pixels); add abbreviated weekday names; ragged/partial → `PARTIAL`
coverage, not `SchemaMismatch`. (F) wire `parse_infrastruktur`/`apply_physicals` into build over
`catalog.json` prose (tag `BasinSource.PARSED_PROSE`); widen `ScrapedAspects` + `_ASPECTS` with
features/lockers/website/amenities/accessibility.

**UI surfacing.** `/swim` `OptionOut` gains a compact timeline (badge renders "4/6 then 2/6 after
18:00"). `/pools/{id}` `FacilityDetailOut` grows basins (kind, L×W, lanes, temp badge + `physical_source`
caveat, diving heights), features (open-now + hours + surcharge + temp), lockers, prices, amenities,
accessibility, provenance — **pure mapping, data already computed**. Real detail panel: basin cards,
prominent water-temp badge, size/lane chips, facilities "open now?" pill, a "PARSED_PROSE auto-extracted"
caveat where prose-derived; amenity chips in the all-pools table.

## Out of scope

- Live occupancy / Countee wiring (commercial, ToS unverified) — the `OccupancyProvider` port stays
  fake-only; never presented as per-lane.
- Altstetten lane data (separate operator `bad-altstetten.ch`, no stadt-zuerich slug).
- A full tariff engine — `pricing.py` stays the dated age-band picker; Slice C only surfaces the
  existing table.
- Storing any derived availability/timeline in gold (stays derive-at-read).
- Re-reading `data/` at request time.

## Slices

- **A — Basin PDF coverage quick win.** *(S)* Add `leimbach`/`blaesi`/`kaeferberg` + both Oerlikon slugs
  to `CITY_BELEGUNGSPLAN_URLS` (`etl/lane_plans.py`); one saved-PDF fixture per newly-listed basin +
  parse assertion (Leimbach parses today; the rest are typed skips until E).
  **Acceptance:** `scrape-lanes` attaches a Leimbach `LanePlan`; `/pools/{leimbach}` returns non-empty
  `lane_panels`; skipped basins counted in `LanePlanReport.skipped`, never fatal; QA green.
  **Depends on:** —

- **B — Query-time lane timeline (the 12:00 == 18:00 fix).** *(M)* `+LaneSlotAvailability`,
  `+LaneAvailabilityTimeline`, `+lane_availability_timeline` (`domain/lane_plan.py`); clamp `t` into the
  session + attach timeline to `SwimOption` (`query.py`); timeline in `/swim` `OptionOut`
  (model+service); badge renders the arc (`ui/router.py`); update the session-start assertions + the
  derive-at-read grep-guard.
  **Acceptance:** a query at 18:00 (club takes lanes then) reports fewer public lanes than 12:00; the
  timeline never reaches `codec.py` (grep-guard green); QA green.
  **Depends on:** —

- **C — Surface the full FacilityDetail through `/pools/{id}` + UI.** *(M)* Extend `FacilityDetailOut`
  with basins/features/lockers/prices/amenities/provenance; `facility_detail_out` maps the
  already-computed fields; UI detail panel + amenity chips. No domain change.
  **Acceptance:** `/pools/{city}` JSON includes basins (`nominal_temp_c`, lanes, dimensions,
  `physical_source` caveat), features (open-at-query-time), lockers, prices; UI renders a temperature
  badge; the no-`data/`-at-request grep-guard stays green; QA green.
  **Depends on:** —

- **D — Model fidelity: per-weekday lane counts + named sections.** *(M — pause after)* Add
  `LanePlan.lanes_by_weekday` + `LaneReservation.section`; mirror through `curated_dto` + `mapping` +
  `codec` (both directions); round-trip + DTO-vs-domain tests.
  **Acceptance:** a hand-built plan with `lanes_by_weekday` + a sectioned reservation survives
  `dumps→loads` exactly; existing uniform plans serialize unchanged (new fields default `None`); QA
  green. **[PAUSE — schema/DTO change before the parser builds on it.]**
  **Depends on:** —

- **E — Anchor-derived, page-relative parser (→ up to 8/8).** *(L)* Per-weekday columns under detected
  anchors; page-relative `GridSpec`; abbreviated weekday names; multi-basin/Teil segmentation writing
  D's fields; ragged → `PARTIAL`; keep all failures typed. One fixture + assertion per newly-supported
  basin.
  **Acceptance:** Vario/Bläsi/Käferberg (→5/8) then both Oerlikon sheets (→8/8) parse to the expected
  lane/section shape + confidence; a truncated grid → `PARTIAL`, not an exception; City still parses
  `COMPLETE` (no regression); QA green.
  **Depends on:** D

- **F — Richer facility extraction across all 57 pools.** *(L)* `Basin.measured_temp_c`/
  `diving_platforms_m`, `Facility.accessibility`/`last_admission_before`, `FeatureKind` growth (+ DTO +
  mapping + codec lockstep); emit `Feature`s from non-Becken infrastruktur segments; wire
  `parse_infrastruktur`/`apply_physicals` into build; widen `ScrapedAspects` + `_ASPECTS`; UI badges with
  `PARSED_PROSE` caveat; update `data/sources.md`.
  **Acceptance:** `swimzh build` yields `PARSED_PROSE` basins for a previously location-only pool; a
  scraped feature/locker survives compose onto a non-curated base; round-trip test green; `sources.md`
  updated; QA green.
  **Depends on:** C (UI surface) for the badges; model additions independent of D/E.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

- **2026-07-21 — open-question defaults (revisit at approval).** #1 `fetched_at` round-trip is already
  correct (no action). #2 named sections modeled as `section: str | None` label (not first-class lane
  equivalents) — revisit if `lane_day_view`/`best_public` need it. #3 commit one saved-PDF fixture per
  supported basin (accept a refresh-cadence tech-debt). #4 measured temp overrides nominal in the badge,
  nominal in a tooltip. #5 low-confidence `PARSED_PROSE` basins are shown in `/pools` detail (with
  caveat) but gated out of `/swim` options.
- **OWNER SIGN-OFF NEEDED (#6, gates A/E):** broadening lane-plan scraping from City to all 8 basins
  increases the copyright/ToS surface flagged in `data/sources.md`. Recommendation: best-effort,
  read-only, per-term is consistent with the existing `scrape-gold` posture — but confirm before A/E,
  and keep the "ask OGD for a machine-readable feed" action open.

## Summary

Written at `done`; distilled into `docs/summaries/richer-data-fidelity.md`.
