---
type: summary
created: 2026-07-21
links: ["[[2026-07-21-richer-data-fidelity-plan]]", "[[gold-store]]", "[[data-layer-architecture]]"]
---

# Richer data fidelity — what exists now

Extract more, lose nothing in the model, surface it in the UI. Delivered across 8 slices; the
gold store, domain, and web surface now carry and expose substantially richer data.

## Extraction — the Belegungsplan parser (`providers/belegungsplan.py`)

- **8/8 listed basins parse** (was City-only). Geometry is **page-relative / anchor-derived**: the
  day-grid band is derived from the detected weekday-row anchors + page width — no absolute A4 pixel
  constants. Recognises full and abbreviated weekday names.
- **Per-weekday segmentation**: lane count may differ by weekday → `LanePlan.lanes_by_weekday`
  (populated only when genuinely ragged; all committed sheets are currently uniform, so this path is
  exercised by a synthetic test). A previously-`SchemaMismatch` ragged grid now resolves to `PARTIAL`,
  never fabricating public lanes; a support-weighted fragment-merge folds stray sub-pitch cells.
- **Multi-basin / named sections**: `parse_belegungsplan_sheet(...) -> tuple[ParsedPlan, ...]` segments
  a sheet that stacks several basins and/or names "Teil 1/Teil 2" sections → `LaneReservation.section`
  (real data via Oerlikon Nichtschwimmer/Sprungbecken). `etl/lane_plans.py` `extend`s over the result.
- Golden digests pin City + Leimbach byte-identically; all failures stay typed `Result` errors.
- **Known correctness history**: the old absolute-pixel geometry silently dropped the rightmost lane on
  A4 sheets wider than City (fixed in E2). The mandated live-PDF spot-check of all 8 parsed basins was
  deferred and is still owed before the lane data is authoritative.

## Prose extraction wired into the build (`providers/infrastruktur.py`, `build/seed.py`, `build/compose.py`)

- `parse_infrastruktur` + `basin_from_physical` + `parse_features` run in the **offline build** over
  `catalog.json` WFS prose. A location-only pool whose description names basins gets a **schedule-less
  facility** of `BasinSource.PARSED_PROSE` basins + `Feature`s (e.g. `hallenbad-altstetten` → 3 basins
  incl. a diving basin with platforms `(1,3,5)` + 6 features). Build-time only — the app never reads
  `data/` at request time (grep-guarded).
- `apply_physicals` is kept as a tested primitive but **intentionally unwired** — no sound offline-build
  call site over the committed inputs (curated basins with prose already hold hand-verified physicals;
  those lacking physicals have no prose). Revisit for a fuzzy prose→scheduled-basin match at compose.
- `ScrapedAspects` / `_ASPECTS` widened with features/lockers/website/amenities/accessibility (compose
  fold tested; the live scraper does not yet populate the new aspects).

## Model fidelity (additive, lockstep, round-trip-guarded)

`LanePlan.lanes_by_weekday`, `LaneReservation.section`, `Basin.measured_temp_c`, `Basin.diving_platforms_m`,
`Facility.accessibility`, `Facility.last_admission_before`, and `FeatureKind` grown (TERRACE/REST/GASTRONOMY,
exhaustiveness parity-tested). Each mirrors through `boundary/curated_dto.py` + `boundary/mapping.py` +
`storage/codec.py`; new fields default None/empty and are popped-when-default on the byte-stability-contracted
basin/lane-plan DTOs, so pre-existing gold serialises unchanged. `measured_temp_c` has no live producer yet.

## Query + surfacing

- **Lane availability is clamped to the queried moment** `now_time` (not wall-clock `now`), fixing the
  12:00≡18:00 collapse; a derived `LaneAvailabilityTimeline` rides on each `SwimOption`. Availability and
  the timeline are derived-at-read, never stored (grep-guarded, incl. the `timeline` key).
- **`/swim` `at` is optional**, defaulting to server time at the boundary (was a required 422).
- **Decision #5 gate**: `find_swim_options` skips **rule-less** basins before `resolve_basin`, so a
  prose-only (PARSED_PROSE, schedule-less) basin appears in `/pools/{id}` with its caveat, produces **no**
  `/swim` option, and its pool stays `uncurated`; a curated basin keeps its rules and is unaffected.
- **`/pools/{id}`** (`FacilityDetailOut`) now surfaces basins (temp badge + `physical_source` caveat,
  size/lane chips, diving heights), features (open-at-query-time), lockers, prices, amenities, accessibility,
  last-admission, provenance — pure mapping in the pools service (the router passes `facility.prices` in).

## Coverage / gates

Full QA green throughout; coverage held ≥95% (final 95.52%). `find_swim_options` (CRAP 24) and the sectioned-
parser functions (CRAP ~18–21) are the most complex, all under the 30 gate.
