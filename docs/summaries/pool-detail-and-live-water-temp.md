---
type: summary
created: 2026-07-26
links: ["[[2026-07-25-water-temperature-provider-plan]]", "[[water-temperature-provider]]", "[[data-layer-architecture]]", "[[basin]]"]
---

# Pool detail for all + live water temperature — what exists

Distilled from [[2026-07-25-water-temperature-provider-plan]] (4 slices, all done).

## Universal pool detail

Every catalog pool now materializes a `facility_doc`, so `GET /pools/{id}` returns a detail
for **all ~57 pools** — Freibad Heuried and all outdoor/river/lake pins are viewable (no more
404s). `seed._prose_facility` became `_location_only_facility`: it always mints a schedule-less
`Facility` (prose `PARSED_PROSE` basins when the WFS description names any, else **zero
basins**, provenance `source="catalog"`), building the identity from `registry.get(pool_id)`
when present so external keys survive. Invariants held: a zero-basin facility stays
`is_curated=False`, yields **no `/swim` option** and no spurious "closed" status — universal
detail gives uncurated pins a viewable card, not a swim result.

## Live water temperature (facility-level, request-time, never persisted)

The pool detail carries a facility-level `live_water_temp` attached at request time from the
OGD **Baditicker** feed. It is a freshness-bearing `LiveTemp(reading, age)` mirroring the
occupancy scaffold — the reading is **never stored in gold** (only the `baditicker_poiid` key
is, guarded by an import-token test). Per-basin `measured_temp_c`/`nominal_temp_c` are
untouched; live temp is additive.

- **Domain** (`domain/query.py`, live-only): `TempReading` (tz-aware, no `PoolId`), `LiveTemp`
  (`is_stale`, 6 h limit), `TempUnavailable`, `TemperatureProvider` port, `read_temperature`.
  No key → `TempUnavailable("no baditicker key")`; empty feed cell → `LiveTemp(celsius=None)`;
  provider `Err` → `TempUnavailable(describe(...))`; never raises.
- **Identity**: `PoolIdentity.baditicker_poiid: str | None`, authored in `data/registry.yaml`,
  threaded DTO → `curated.py` → `codec.py`, riding the S1 location-only mint for uncurated pools.
- **Adapter** (`providers/baditicker.py`): `fetch`/`parse` over the feed
  (`stadt-zuerich.ch/stzh/bathdatadownload`), regex extraction (house style), errors-as-values,
  German `dateModified` → tz-aware Europe/Zurich, TTL cache (~120 s, errors not cached). Pinned
  by the real saved fixture `tests/providers/fixtures/baditicker.xml`.
- **Wiring** (`config.py`/`main.py`): behind `SWIMZH_BADITICKER_URL` (presence = enabled);
  unset → `None` → fail-open `TempUnavailable("live temperature not configured")`, never a 500.
- **UI** (`detailpanel.js`): "N °C · measured M ago"; empty cell → "not yet measured"; stale >
  limit → visibly marked; unavailable → the reason, never a stale number.

Roster: real poiids mapped for the reconcilable pools (indoor Hallenbäder incl. Bungertwies
`hb002`, outdoor/lake pins); a no-dangling-keys test pins every declared poiid to the fixture.

## Known follow-ups (tech debt)

- `parse()` fails the whole snapshot on one malformed bath (one bad hand-typed feed entry drops
  live temp for **all** pools) — should be best-effort per bath (skip + audit), matching
  `schedule_scraper`.
- No direct "errors-not-cached" test (behavior is correct in code).
- **Flussbad Unterer Letten** unmapped — two feed poiids (`flb6940`/`flb8803`) for two catalog
  pools, undisambiguable; needs a human decision.
- Optional `at≈now` gate on the detail temp for future-dated queries.
- Occupancy / people-count is a **separate** effort, still blocked on the countee.ch/ASE ToS
  check ([[water-temperature-provider]] / `data/sources.md`).
