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

**Two design decisions — SETTLED by the owner 2026-07-29 (both the larger-scope option):**
1. **Build contract → ONE ATOMIC PIPELINE COMMAND.** `swimzh build` orchestrates the whole provider
   chain — roster → page-discovery → schedule scrape → lane scrape → price scrape → compose —
   atomically (temp-DB + swap, reusing S4's `storage/atomic.py`), so a single invocation yields a
   **complete** store and a mid-chain provider failure aborts the whole build content-unchanged. This
   makes `build` **network-dependent** (already true for the WFS roster since S3) and effectively
   folds today's separate `scrape-gold`/`scrape-lanes` into `build` (they may remain as thin
   re-layer commands or be retired — the implementer records which). This is its **own slice** (see
   S2 below), larger than the plan's original "keep separate" recommendation.
2. **Curation model → THREE-STATE FRESHNESS, replacing the `is_curated` boolean.** A pool's
   schedule state becomes an enum surfaced on `/pools` (+ `/swim` status + UI): **`scraped`** (has a
   real scraped schedule), **`awaiting_scrape`** (scrapeable — an indoor stadt-zuerich pool — but no
   schedule yet), **`no_source`** (no schedule source at all, e.g. `aemtler` the school pool). This
   replaces the boolean `is_curated` (`storage/codec.py:182`) and touches the `/pools` + `/swim` API
   contract and the UI's curated/uncurated split — a larger change than a redefined boolean, so its
   API/UI reach is called out in S1's touches. A schedule-less pool never reads as "closed".

**Invariants.**
- Gold stays the sole runtime SoT; `apps/web/**` still reads only the gold DB (grep-asserted).
- After S6, `build`/`etl` read **no authoritative fact** (schedule/price/geo/physical) from curated
  YAML — only the thin crosswalk (grep-assertable, updated single-source test).
- A schedule-less pool is a first-class honest state, never an error or a silent empty.

## Out of scope

- Building any new provider (all sourcing shipped in S1–S5; this plan only deletes + rewires +
  orchestrates the existing providers into the atomic build).
- The `baditicker_poiid → poi_id` collapse (needs a live multi-layer WFS cassette; separate).
- Live occupancy / `measured_temp_c`.

## Slices

### S1 — Optional-DTO + WFS physicals/address + THREE-STATE freshness model (GO/NO-GO, riskiest)

- **Goal**: Make `address`/`source`/`rules`/physicals optional in the curated DTO, source `address`
  + basin physicals from the WFS when omitted, and land the **three-state freshness** curation model
  (decision #2) — BEFORE any real YAML is stripped and BEFORE the atomic-build rewire (S2).
- **Touches**: `boundary/curated_dto.py` (make `FacilityDTO.address`/`.source`/`BasinDTO.rules` +
  physical fields optional), `build/seed.py` + `build/compose.py` (stamp `address` from
  `entry.address` onto the curated blob; wire `infrastruktur.apply_physicals` so a curated facility's
  basins get WFS-prose physicals — the location-only path is not enough), `storage/codec.py` (replace
  the `is_curated` boolean with a `ScheduleFreshness` enum `scraped | awaiting_scrape | no_source`,
  derived from the blob having rules + whether the pool is scrapeable), the **`/pools` + `/swim` API
  contract** (`curated` bool → freshness field) and the **UI** curated/uncurated split, +
  `tests/storage/test_is_curated.py` (→ freshness tests).
- **Acceptance** (concrete, against a stripped *fixture*, not real `data/`): (1) a pool blob reduced
  to the allowlist (`facility_id` + basins with `basin_id`/`name`/`lane_plan_source` only) loads +
  builds without a validation error; its `address` is the roster's. (2) the freshness of a
  rules-present pool is **`scraped`**; a schedule-less scrapeable (indoor stadt-zuerich) pool is
  **`awaiting_scrape`**; `aemtler` (school, unscraped) is **`no_source`** — each pinned by a test.
  (3) `/swim` for a non-`scraped` pool returns its freshness status, **NOT "closed"**, no option, no
  error; `/pools` exposes the freshness field and the UI renders all three states. (4) For a stripped
  **prose** pool (city/bungertwies analogue), basin `kind`/dimensions are present via
  `apply_physicals` OR a deliberate drop is recorded — assert whichever is decided. **No
  `data/pools/*.yaml` stripped; no atomic-build rewire yet.**
- **Depends on**: —

### S2 — Atomic pipeline build (decision #1): `swimzh build` runs the whole provider chain

- **Goal**: Fold the provider chain — roster → page-discovery → schedule scrape → lane scrape →
  price scrape → compose — into a single **atomic** `swimzh build` (temp-DB + swap, reusing
  `storage/atomic.py`), so one invocation yields a complete store and a mid-chain failure aborts
  content-unchanged.
- **Touches**: `cli.py` (`build` orchestrates the chain; `scrape-gold`/`scrape-lanes` become thin
  re-layer commands or are retired — record which), `etl/build.py`/`build/compose.py` (compose the
  scraped schedule/lanes/prices into the store within the one atomic swap), and the tests that ran
  the phases separately (incl. `apps/web/tests/conftest.py` `gold_db`, which becomes "one atomic
  offline `build`" via `MockTransport` over the committed page/WFS fixtures).
- **Acceptance**: `swimzh build` against fixtured providers yields a store with **schedules present**
  (from the scrape) in one command; a single injected provider failure exits non-zero and leaves the
  prior gold **content-unchanged** (iterdump digest, per S4); `scrape-gold`/`scrape-lanes` behaviour
  is preserved or their retirement is recorded; full QA green. **Still no `data/pools/*.yaml`
  stripped** (schedules still come from curated YAML here — S3 flips the source).
- **Depends on**: S1.

### S3 — Strip `data/pools/*.yaml` to the crosswalk; retest

- **Goal**: Delete the authoritative payload from the pool files (heavy in 4: `city`, `oerlikon`,
  `bungertwies`, `aemtler`; the other 3 are already minimal), keeping only the binding.
- **Goal**: Delete the authoritative payload from the pool files (heavy in 4: `city`, `oerlikon`,
  `bungertwies`, `aemtler`; the other 3 are already minimal), keeping only the binding — so the
  atomic build's **scrape becomes the sole schedule source**.
- **Touches**: `data/pools/*.yaml` (all), and the ~40 tests that assume curated schedules/prices
  (convert to the sourced pipeline's expectations — not weakened). The `gold_db` rewire is **already
  done in S2** (the atomic build scrapes offline), so this slice just removes the curated schedules
  and confirms the S2 pipeline now supplies them; it does not re-touch conftest for the fixture.
- **Acceptance** (ALLOWLIST, not a partial denylist — a 6-field grep would pass green while
  `amenities`/`public_holiday_policy`/`lockers`/basin `kind`/`exceptions`/… survive in the served
  blob): **S3 authors** a **parsed-YAML key-set test** (allowlist-per-level) asserting every
  `data/pools/*.yaml` has top-level keys ⊆ {`facility_id`, `basins`}, each basin's keys ⊆
  {`basin_id`, `name`, `lane_plan_source`}, and — where present — `lane_plan_source`'s keys ⊆
  {`url`, `section`} (keep the binding's own nested fields; not "no key anywhere"). With curated
  schedules gone, the S2 atomic build supplies `city`/`oerlikon` schedules from the scrape and the
  web suite still asserts them; `city`/`bungertwies` basin physicals resolve per the S1 decision
  (`apply_physicals` or recorded drop); `aemtler` (school, unscraped) is `no_source`; full QA green.
- **Depends on**: S2.

### S4 — Reconcile the single-source test, CLAUDE.md, and concept docs

- **Goal**: Update the guardrails and knowledge base to the as-built thin-crosswalk end-state.
- **Touches**: the S3 **build-side** key-set test (the parsed-YAML allowlist) is the guard that
  curated YAML carries no authoritative fact — that belongs with `etl/`/`field_sourcing`, NOT the
  app-runtime `apps/web/tests/api/test_single_source_of_truth.py` (whose `FORBIDDEN` tuple guards a
  *different* invariant: no `apps/web/**` module reads YAML at runtime — already true, leave it).
  `CLAUDE.md` (data-sourcing + the new atomic-build contract + three-state freshness); mark
  [[discovery-driven-providers]] `status: implemented`; excise the superseded parts of
  [[lane-plan-url-binding]]; distil `docs/summaries/website-sourced-providers.md`.
- **Acceptance**: the S3 build-side key-set test enforces "no authoritative fact from curated YAML";
  the app-runtime single-source test still passes unchanged; `CLAUDE.md` documents the one-command
  atomic build + three-state freshness and no longer calls curated YAML a source of truth; concept
  docs match reality; full QA green.
- **Depends on**: S3.

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
- 2026-07-29 (post-approval, owner settled the two S1-gated decisions — both the LARGER option, so
  the plan was re-decomposed from 3 to **4 slices**): **#1 build contract → ONE ATOMIC PIPELINE
  COMMAND** (`swimzh build` runs roster→discover→scrape→lanes→prices atomically; folds the separate
  scrape commands) — now its own slice **S2**. **#2 curation model → THREE-STATE FRESHNESS**
  (`scraped | awaiting_scrape | no_source`) replacing the `is_curated` boolean — expands S1 to touch
  the `/pools` + `/swim` API contract and the UI. Slice chain is now S1→S2→S3→S4 (S1 optional-DTO +
  WFS physicals/address + freshness model; S2 atomic build; S3 strip; S4 docs); `pause_after: S1`
  unchanged. NB: the `/dev:implement` specialised subagents became unavailable this session, so
  execution mechanics differ (implement + adversarial review run without the `dev:*` agents).
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
