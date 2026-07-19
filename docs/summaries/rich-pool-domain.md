---
type: summary
created: 2026-07-19
links: ["[[2026-07-19-rich-pool-domain]]", "[[basin]]", "[[locker-option]]", "[[feature]]"]
---

# Rich pool domain — what exists now

Implemented 2026-07-19 via /dev:implement (4 slices, all gates green:
128 tests, coverage 93.48% ≥ 91 floor, CRAP clean).

## Domain surface

- **Basin physicals** (`domain/models.py`): `kind: BasinKind` (8 values),
  `dimensions: Dimensions(Decimal length/width)`, `lanes`, `nominal_temp_c`
  (design target, not live), `physical_source: BasinSource(CURATED |
  PARSED_PROSE)`. Missing facts stay `None` — partiality is a feature.
- **`providers/infrastruktur.py`**: total best-effort parser of WFS
  `infrastruktur` prose → `ParsedBasinPhysical` records; `apply_physicals`
  enriches a scheduled Basin and stamps `PARSED_PROSE`. NOT yet wired into
  ETL — when wiring, feed the UNCLEANED field (`geo_sport._clean` strips `;`).
- **Facility statics**: `website`, `features: tuple[Feature, ...]` (sauna etc.,
  hours resolve through the SAME `resolve_hours` path as basins — closures
  shut the sauna too), `lockers: tuple[LockerOption, ...]` (orthogonal
  fee/deposit/period axes, `raw` kept for audit). `facility_detail()` returns
  `FacilityDetail` with tri-state `FeatureStatus.open_at_query_time`
  (unknown-hours ≠ closed).
- **`AdultsOnly(min_age=18)`** in `SessionAccess`; `ACCESS_TYPES` derived from
  `REPRESENTATIVE_ACCESS`; union-completeness test makes a forgotten arm a
  test failure. School pools are ordinary Basins (aemtler.yaml proof case —
  timetable ILLUSTRATIVE, verify before relying).
- **Live occupancy** (`domain/query.py`, live-only): `OccupancyProvider`
  Protocol → `Result[Occupancy, ProviderError]`; attach in `find_swim_options`
  within 30 min of now, keyed by `identity.crowdmonitor_keys`;
  `LiveOccupancy(reading, age)` (staleness derived) or
  `OccupancyUnavailable(reason)`; `None` = not requested. Never serialized to
  gold (guard test). `Occupancy.measured_at` must be tz-aware (constructor
  guard). Real CrowdMonitor adapter deferred pending ToS (`data/sources.md`).

## Invariants now under test

- Codec round-trips every new field; legacy flat `length_m` payloads rejected.
- All mapping token tables are enum-complete (`test_token_tables_cover_their_enums`).
- `SessionAccess` union ↔ `REPRESENTATIVE_ACCESS` completeness.
- `"occupancy"` never appears in `codec.dumps` output.

## Backlog (from the plan ledger)

ETL wiring for the prose parser (+ depth-word guard, real-WFS fixture),
aemtler timetable verification, `Feature` exceptions axis, `facility_detail`
caller, `find_swim_options` extraction (CC 21), coverage ratchet 91→93,
duplicate-representative assert.
