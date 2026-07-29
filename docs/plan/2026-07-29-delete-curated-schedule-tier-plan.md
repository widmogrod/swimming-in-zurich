---
type: plan
status: approved         # draft -> approved -> in-progress -> done
created: 2026-07-29
feature: delete-curated-schedule-tier
gates:
  qa: full               # ruff, mypy, pytest+coverage, crap.py  (+ ts-qa if UI touched)
  review: adversarial    # dev:critic-reviewer must find no blocking issues per slice
pause_after: ["S1"]      # confirm the build-contract change + curation model before mass deletion
links: ["[[discovery-driven-providers]]", "[[lane-plan-url-binding]]", "[[everything-website-sourced-providers-fail-fast]]", "[[gold-store]]", "[[data-layer-architecture]]", "[[fastapi-service-integration]]"]
---

# Delete the curated schedule tier — reduce curated YAML to the thin crosswalk (S6)

## Context

The `website-sourced-providers` refactor shipped S1–S5 to `feat/new-ic`: roster/geo/`geo_sport_id`
now come from the live WFS, schedules from the page scraper, prices from `price_scraper`, closures
from `parse_notices`, lane plans from discovered Belegungsplan links — and the build is fail-fast +
atomic. The `etl/field_sourcing.py` audit proves every authoritative `facility_doc` field is sourced
or a recorded drop; the **only** curated YAML that still carries authoritative weight is the thin
crosswalk. This plan finishes the job: **delete the curated schedule/price/physical payload from
`data/pools/*.yaml`** so the sourced data is the sole authority, leaving only the crosswalk.

This is the destructive slice the S1–S5 run deliberately deferred (owner decision 2026-07-29): it
changes the **build contract** (plain `swimzh build` will yield schedule-less pools until
`scrape-gold` runs), touches ~40 tests that assume curated schedules, and dissolves the
curated/uncurated distinction the UI derives from `facility_doc` carrying rules. See
[[website-sourced-providers-refactor-state]] and the parent plan's S5 Decisions for the residue map.

**Narrower than it looks: 3 of the 7 pool files are already schedule-less today** (`blaesi.yaml`,
`leimbach.yaml`, `kaeferberg.yaml` carry `rules: []` + `lane_plan_source` only and already serve no
`/swim` option). Only **4 files carry the heavy payload** (`city`, `oerlikon`, `bungertwies`,
`aemtler`). So S1's real delta is *tolerating omitted `rules`/`address`/`source`* (they are required
in the DTO today, which is why the 3 minimal files still carry explicit `rules: []`), not "teach the
loader schedule-less from scratch." One wrinkle: `aemtler` is `kind: school`, which
`scrape_indoor_facilities` does not scrape — so after stripping it stays **permanently**
schedule-less even after `scrape-gold`; its tests convert to schedule-less expectations, not
source-driven.

## Design (signature altitude)

**What is deleted** from every `data/pools/*.yaml`: **everything except the kept allowlist below.**
Stated positively rather than as a denylist, because the files carry more authoritative/dropped
fields than a short list captures — `rules`, `prices`, `closures`, `public_holiday_policy`,
`amenities`, `features`, `lockers`, `accessibility`, `last_admission_before`, basin `kind`/`lanes`/
`dimensions`/`nominal_temp_c`/`diving_platforms_m`/`exceptions`, `valid_as_of`, `geo`, `website`, and
`address` (WFS-roster-sourced) + `source` (build/provenance). Each is sourced (roster/schedule/price/
notice/infrastruktur) or a recorded drop per the S5a audit (`etl/field_sourcing.py`).

**What is kept — the thin crosswalk** (facts on no website): the per-basin `lane_plan_source`
(url + optional `section`) URL→basin binding, and in `registry.yaml` the `baditicker_poiid`,
`crowdmonitor_keys`, `aliases`, and the kaeferberg `thermal` kind override. A stripped
`data/pools/*.yaml` therefore carries `facility_id` + basins (`basin_id`, `name`, `lane_plan_source`)
— a **binding file**, not a curated-facts file.

**DTO change is a prerequisite (S1).** Today `FacilityDTO.address` and `.source` and `BasinDTO.rules`
are **required, no default** (`boundary/curated_dto.py` — this is why the 3 already-minimal files
still carry explicit `rules: []`). So a stripped file *fails validation* until S1 makes
`address`/`source`/`rules` **optional** (omitted → address from roster, rules empty, source =
build-assigned). This is an explicit S1 deliverable, not an afterthought.

**Loader / compose** (`providers/curated.py`, `boundary/curated_dto.py`, `build/compose.py`,
`build/seed.py`): must accept an `address`/`source`/`rules`/physicals-omitted pool file and produce a
facility whose address + basin physicals come from the WFS and whose schedule is empty until a scrape
layers it in. `build_store` (offline) yields **schedule-less** pools; the `scrape-gold`/`scrape-lanes`
layers add the real schedule/lane data.

**Two wiring gaps this exposes (both NEW S1 work, do not assume they already exist):**
- **Address-from-roster for a CURATED facility is not yet wired.** `providers/curated._map_facility`
  gets no roster and sets `address=dto.address` directly; the curated blob is serialized at
  `build/seed.py:106` (`codec.dumps(facility)`) with **no** address stamp (the `seed.py:115` stamp is
  the `PoolRow` *column*; `:193` is the *location-only* path). So sourcing address onto the curated
  blob from `entry.address` is new work in the build/seed/compose path — not `_map_facility`, and
  never a silent `""`.
- **Basin physicals for `city`/`bungertwies` will be LOST unless `apply_physicals` is wired.**
  `infrastruktur` (the S5a-claimed producer for basin `kind`/dimensions/`features` on the 2 prose
  pools) runs **only** on the `_location_only_facility` path (`seed.py:175,180`); a curated facility
  (has a YAML) takes the `codec.dumps(facility)` branch and never invokes it. So after the strip,
  city/bungertwies lose their physicals unless S1 wires `apply_physicals` (which `infrastruktur`
  already exposes to merge prose physicals into an existing facility's basins) onto the built
  facility. S1 must either wire it (source-where-possible) or record a deliberate drop for those 2.

**Two design decisions this plan must settle (S1 pause):**
1. **Build contract** — does `swimzh build` stay offline-assembly-only (operator then runs
   `scrape-gold`), or does a single command orchestrate the whole provider chain
   (roster→discover→scrape→lanes→prices) atomically? Recommendation: keep them separate (smaller
   change, honors S4's atomic-per-command design), but document the required sequence and make a
   schedule-less store an **honest, non-error** state, not a silent hole.
2. **Curation model** — the real seam is **`is_curated(facility_doc)`** (`storage/codec.py:182`,
   today = "the blob is present AND ≥1 basin has ≥1 rule"), surfaced as the `/pools` `curated` flag
   and the `/swim` uncurated status. After deletion a schedule-less-but-scrapeable pool must not read
   as "closed". S1 **decides and documents** the redefinition (proposal: a scraped pool with rules
   reads `curated=true`; a pool awaiting/without a schedule source reads `curated=false` +
   uncurated status, never "closed") and **pins the chosen concrete values with tests** (see S1
   acceptance) — the redefinition is a deliverable, its pinned values are the checkable artifact.

**Invariants.**
- Gold stays the sole runtime SoT; `apps/web/**` still reads only the gold DB (grep-asserted).
- After S6, `build`/`etl` read **no authoritative fact** (schedule/price/geo/physical) from curated
  YAML — only the thin crosswalk (grep-assertable, updated single-source test).
- A schedule-less pool is a first-class honest state, never an error or a silent empty.

## Out of scope

- Building any new provider (all sourcing shipped in S1–S5; this plan only deletes + rewires).
- The `baditicker_poiid → poi_id` collapse (needs a live multi-layer WFS cassette; separate).
- Live occupancy / `measured_temp_c`.
- Folding scrape into build as one command, unless S1 chooses that build-contract option.

## Slices

### S1 — Schedule-less build + curation-model redefinition (GO/NO-GO, riskiest)

- **Goal**: Make `address`/`source`/`rules`/physicals optional in the curated DTO, source `address`
  + basin physicals from the WFS when omitted, and settle + pin the curation model — BEFORE any real
  YAML is stripped.
- **Touches**: `boundary/curated_dto.py` (make `FacilityDTO.address`/`.source`/`BasinDTO.rules` (and
  the physical fields) optional), `build/seed.py` + `build/compose.py` (stamp `address` from
  `entry.address` onto the curated blob; wire `infrastruktur.apply_physicals` so a curated facility's
  basins get WFS-prose physicals — the location-only path is not enough), `storage/codec.py`
  (`is_curated` for a schedule-less blob), the `apps/web` `/pools` `curated` + `/swim` status surface
  + `tests/storage/test_is_curated.py`.
- **Acceptance** (concrete, against a stripped *fixture*, not real `data/`): (1) a pool blob reduced
  to the allowlist (`facility_id` + basins with `basin_id`/`name`/`lane_plan_source` only) loads +
  builds without a validation error; its `address` is the roster's. (2) `is_curated(<that blob>)`
  returns the **decided value** (proposal: `False`) — pinned by a test asserting that exact value.
  (3) `/swim` for that pool returns **uncurated status, NOT "closed"**, no option, no error;
  `/pools` lists it with `curated == <decided>`. (4) A scraped pool (rules present) still reads
  `is_curated == True`. (5) For a stripped **prose** pool (city/bungertwies analogue), basin `kind`/
  dimensions are present via `apply_physicals` OR a deliberate drop is recorded — assert whichever is
  decided. The S1 pause records the decided values. **No `data/pools/*.yaml` stripped.**
- **Depends on**: —

### S2 — Strip `data/pools/*.yaml` to the crosswalk; retest

- **Goal**: Delete the authoritative payload from the pool files (heavy in 4: `city`, `oerlikon`,
  `bungertwies`, `aemtler`; the other 3 are already minimal), keeping only the binding.
- **Touches**: `data/pools/*.yaml`, the ~40 tests that assume curated schedules/prices, AND
  critically **`apps/web/tests/conftest.py`** — the session `gold_db` fixture today calls only
  `build_store(DATA_DIR, db, _ROSTER)` (offline), so after the strip it yields schedule-less pools
  and the web integration assertions (`/swim` options non-empty; `city` `curated is True`) break.
  **Rewire `gold_db` to also run `scrape_gold` offline** via `MockTransport` over the committed page
  fixtures (`tests/providers/fixtures/*.html`; the machinery exists in `tests/test_cli.py`), so the
  web suite exercises the real sourced pipeline and `city` stays served + `curated`.
- **Acceptance** (ALLOWLIST, not a partial denylist — a 6-field grep would pass green while
  `amenities`/`public_holiday_policy`/`lockers`/basin `kind`/`exceptions`/… survive in the served
  blob): **S2 authors** a **parsed-YAML key-set test** (allowlist-per-level) asserting every
  `data/pools/*.yaml` has top-level keys ⊆ {`facility_id`, `basins`}, each basin's keys ⊆
  {`basin_id`, `name`, `lane_plan_source`}, and — where present — `lane_plan_source`'s keys ⊆
  {`url`, `section`} (keep the binding's own nested fields; not "no key anywhere"). The rewired
  `gold_db` serves `city`/`oerlikon` schedules from the offline scrape and the web suite asserts them
  (not weakened to "no options"); `city`/`bungertwies` basin physicals resolve per the S1 decision
  (`apply_physicals` or recorded drop); `aemtler` (school, unscraped) is asserted schedule-less;
  full QA green.
- **Depends on**: S1.

### S3 — Reconcile the single-source test, CLAUDE.md, and concept docs

- **Goal**: Update the guardrails and knowledge base to the as-built thin-crosswalk end-state.
- **Touches**: the S2 **build-side** invariant test (the parsed-YAML key-set allowlist) is the guard
  that curated YAML carries no authoritative fact — that belongs with `etl/`/`field_sourcing`, NOT
  the app-runtime `apps/web/tests/api/test_single_source_of_truth.py` (whose `FORBIDDEN` tuple guards
  a *different* invariant: no `apps/web/**` module reads YAML at runtime — already true, leave it).
  `CLAUDE.md` (data-sourcing section → sourced + thin crosswalk); mark [[discovery-driven-providers]]
  `status: implemented`; excise the superseded parts of [[lane-plan-url-binding]]; distil
  `docs/summaries/website-sourced-providers.md`.
- **Acceptance**: the build-side key-set test (from S2) enforces "no authoritative fact from curated
  YAML"; the app-runtime single-source test still passes unchanged; `CLAUDE.md` no longer calls
  curated YAML a source of truth; concept docs match reality; full QA green.
- **Depends on**: S2.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

- 2026-07-29 (pre-approval): spun off from the S1–S5 run because deletion is destructive,
  high-churn (~40 tests), and changes the build contract + curation model — it earns its own gated
  plan rather than being appended to a long run.
- 2026-07-29 (pre-approval review, plan-critic): **B1** — S1 acceptance pinned to concrete values
  (named the real seam `is_curated` at `storage/codec.py:182`, not the nonexistent
  `curation_status`; `/swim` must read uncurated not "closed"; `is_curated(stripped)` test-pinned).
  **B2** — S2 now names the `apps/web/tests/conftest.py` `gold_db` rewire (run `scrape_gold` offline
  via `MockTransport` over the committed page fixtures) so the web suite keeps real /swim assertions
  instead of weakening them. **B3** — reconciled the kept-field list with the DTO schema: making
  `FacilityDTO.address`/`.source`/`BasinDTO.rules` optional is an explicit S1 deliverable, `address`
  (WFS-sourced) + `source` added to the delete-list and the S2 grep. Non-blocking facts folded in:
  3/7 files already schedule-less; only 4 carry the heavy payload; `aemtler` (school) is permanently
  schedule-less after strip (unscraped).
- 2026-07-29 (pre-approval, 2nd independent plan-critic): **BLOCKING fixed** — S2 acceptance was a
  6-field denylist grep that would pass green while `amenities`/`public_holiday_policy`/`lockers`/
  basin `kind`/`exceptions`/`valid_as_of`/`features` survived in the served blob (they're
  DROP/BUILD_METADATA per `field_sourcing.py`, all have DTO defaults so they load clean). Replaced
  with a **parsed-YAML key-set allowlist test** (top-level ⊆ {facility_id, basins}; basin ⊆
  {basin_id, name, lane_plan_source}); Design delete-list restated positively as "everything except
  the allowlist". **Non-blocking fixed**: (a) the curated-blob `address`-from-roster stamp is NEW S1
  work — `seed.py:106` `codec.dumps` has no address stamp; `seed.py:115` is the column, `:193` the
  location-only path — corrected the citation; (b) `infrastruktur` runs ONLY on the location-only
  path, so stripping city/bungertwies would LOSE their physicals unless S1 wires
  `apply_physicals` — added as an explicit S1 deliverable / recorded-drop choice; (c) S3 clarified
  which test owns which invariant (build-side key-set vs. app-runtime single-source).

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/website-sourced-providers.md` (what EXISTS now, not what was intended).
