---
type: plan
status: in-progress      # draft -> approved -> in-progress -> done
created: 2026-07-28
feature: website-sourced-providers
branch: plan/website-sourced-providers
worktree: .claude/worktrees/plan-website-sourced-providers
base_branch: feat/new-ui
gates:
  qa: full               # ruff, mypy, pytest+coverage, crap.py  (+ ts-qa if UI touched)
  review: adversarial    # dev:critic-reviewer must find no blocking issues per slice
pause_after: ["S1"]      # hard go/no-go on the fidelity gap before any deletion work
links: ["[[discovery-driven-providers]]", "[[lane-plan-url-binding]]", "[[data-layer-architecture]]", "[[gold-store]]", "[[source-links]]", "[[lane-data-availability]]"]
---

# Remove curated-YAML-as-truth — every fact from a website provider, fail-fast

## Context

The ETL today builds gold from **hand-authored curated YAML** (`data/registry.yaml`,
`data/pools/*.yaml`, `data/calendar/*.yaml`) plus a committed WFS snapshot (`data/catalog.json`).
The owner decision recorded in [[discovery-driven-providers]] (2026-07-28) rejects this: every
fact — even low-volatility ones (roster, basin `kind`, eligibility rules, aliases, lane links) —
must originate from a **website provider**, providers are chained by *discovered* links, and the
build is **fail-fast** (a provider that can't produce a declared/discovered fact aborts the whole
build; no skip-and-continue-green). This plan removes the deprecated curated-YAML tier and the
best-effort posture, migrating each fact-class to a provider.

The core risk is **fidelity**: the source pages carry *less structure* than the curated YAML
asserts. Two source channels already exist and must be credited before deciding what is
"unsourced": (a) the stadt-zuerich **timetable** — a flat facility-level row list
(`day, hours, category`); the scraper already derives access categories (`Frauen→WomenOnly`,
`Senioren→SeniorsOnly`, `Schul→SchoolReserved`, else `PublicSwim`); and (b) the WFS
**`infrastruktur` prose**, which `providers/infrastruktur.py` (`parse_infrastruktur`,
`basin_from_physical`, `parse_features`, wired live in `build/seed.py:162-176`) already parses
into **basin `kind`, dimensions, lanes, nominal temp, and features/amenities**. So the genuinely
*unsourced* residue the curated YAML adds on top is narrower than it first appears: **per-basin
*schedule* decomposition** (routing the flat timetable to basins), **richer access**
(`lane_swim`, `family` + notes), **prices**, **`public_holiday_policy`**, and **closures**. S1 is
a hard go/no-go that measures exactly this residue — per fact-class — before any removal begins.

## Design (signature altitude)

**Provider chain (data-driven fetch-sets; no hardcoded URL lists).** Each fact-class is produced
by a provider returning `Result[…, ProviderError]`; the fetch-set of a downstream provider is a
projection of an upstream provider's *discovered* output, not YAML.

- `roster_provider` — WFS (+ pool-index page) → the ~57-pool identity spine (`PoolId`, name,
  facility `kind`, aliases, xref keys) + geo. Replaces `registry.yaml` + committed `catalog.json`.
- `page_provider` — a pool's official page → `PageDoc { schedule_rows, discovered_links, notices }`.
  `discovered_links` is the discovery hop: Belegungsplan / price / sub-resource URLs, each
  **stamped with the owning `PoolId`** so downstream joins stay deterministic (reuse the
  `ParsedPlan.source_url` URL-keyed-join pattern from [[lane-plan-url-binding]]; `basin_hint` is
  never an identity key).
- `schedule_provider` — `PageDoc.schedule_rows` → facility-level `ScheduleRule`s (extends today's
  `schedule_scraper`). Per-basin routing, if retained, is decided by S1.
- `basin_physical_provider` — **already exists**: `providers/infrastruktur.py` parses the WFS
  `infrastruktur` prose → basin `kind`, dimensions, lanes, nominal temp, features/amenities
  (`build/seed.py:162-176`). This plan *retains and formalizes* it as the provider for those
  fact-classes rather than reinventing or dropping them; S5 routes `kind`/dimensions/amenities here.
- `lane_provider` — `PageDoc.discovered_links` (filtered to Belegungsplan) → `LanePlan`. Fetch-set
  is the discovered links, **not** hand-authored `lane_plan_source`.
- `price_provider`, `notice_provider` — discovered price page / disturber notices → prices, closures.

**Build semantics — fail-fast, abort-whole-build (owner decision 2026-07-28).** `build_store`
composes provider outputs; **any** provider hard-failure on a declared/discovered source aborts
the entire build with a non-zero exit and leaves the prior gold DB **untouched** (all-or-nothing
fresh — no partial write). Today the build writes **in place, additively** (`etl/build.py:58`
`open_db(db_path)` → `write_pools`/`write_schedules`), and `scrape-gold`/`scrape-lanes` layer onto
an already-built store; so "no partial write" is a **new** requirement. S4 achieves it by building
into a **temp DB and atomically swapping** on success (rename), so a mid-build abort never mutates
the live file — the layered scrape commands either fold into that single transactional build or
run against the temp DB before the swap (S4 decides which). The typed `ProviderError` *values* are
preserved (surfaced in the abort message); what is deleted is every green-exit-with-a-hole path:
`scrape-gold`'s skip-and-report (`etl/scrape.py`), `LanePlanUnavailable`'s "the facility still
builds", and the stale-store fetch-set invariant.

**Invariants.**
- Gold remains the sole runtime SoT; the app still reads only the gold DB (unchanged, grep-asserted).
- No `build`/`etl` module reads `data/pools/*.yaml` or `data/registry.yaml` after S6 (grep-asserted).
- A build either fully succeeds against live/fixtured sources or aborts non-zero writing nothing.
- Every discovered link carries its parent `PoolId`; downstream joins are id-keyed, never fuzzy.

## Out of scope

- **This is a program-sized refactor kept to six risk-ordered slices with a hard S1 go/no-go.**
  If the S1 gap report shows the richer fact-classes need heavyweight (e.g. LLM) extraction, that
  extractor is its *own* follow-on plan — S5 here only routes each class to sourced-or-dropped.
- Changing the domain model's shape (basin-scoped) unless S1 forces facility-level flattening.
- Occupancy / `measured_temp_c` live providers (separate track; not curated-YAML tier).
- Any UI change beyond what deleting a fact-class forces (e.g. a dropped price chip).
- Per-cadence *scheduling* of providers (cron/orchestration) — the design allows it; wiring it is later.

## Slices

### S1 — Fidelity spike: provider-sourced schedule+access vs. curated YAML (GO/NO-GO)

- **Goal**: Measure exactly which curated facts a website provider can reproduce, for the 7
  currently-curated pools, before removing anything.
- **Touches**: `schedule_provider` (extend `providers/schedule_scraper.py`), a new
  `etl/fidelity_report.py` (pure), fixtures for the 7 pool pages, `docs/concepts/discovery-driven-providers.md` (record outcome).
- **Acceptance**: (1) For each of the 7 pools, provider-derived facility-level `ScheduleRule`s,
  compared against the curated rules **projected to facility level**, produce a diff whose every
  entry is classified (matched / source-poorer / source-richer) — the diff is the artifact the S1
  human gate reads; no silent unclassified rows. (2) A committed gap report classifies each
  curated fact-class as `sourced-by-<provider> | derivable-with-rule | not-in-source`, seeding it
  with the **known** classifications: `kind`/dimensions/amenities → `sourced-by-infrastruktur`
  (verify by running `parse_infrastruktur` against the 7 pools' WFS prose and comparing to their
  YAML — note this parser today runs only on the *uncurated* `_location_only_facility` path
  (`build/seed.py:162`), so S1 invokes it off its current production path, not existing build
  output), access-category → `sourced-by-schedule`; and resolving the residue (basin-*schedule*-split, `lane_swim`/`family`
  access, prices, `public_holiday_policy`, closures). (3) Test asserts both diff and report are
  regenerable from fixtures deterministically. **No production data path changes in S1.**
- **Depends on**: —

### S2 — Discovery hop: page provider emits links; lane fetch-set is a projection

- **Goal**: Remove hand-authored `lane_plan_source`; derive the lane fetch-set from discovered links.
- **Touches**: `page_provider` (link extraction), `etl/lane_plans.py` + `etl/silver.py` (fetch-set
  from discovered links, keep URL-keyed join), `domain` (drop `lane_plan_source` as curated input).
- **Acceptance**: For the covered pools, the discovered-link lane fetch-set **equals** the current
  YAML-declared `{(basin, url)}` set (test); `scrape-lanes` reads no `lane_plan_source` from YAML;
  the stacked-sheet `section` routing still binds by declared token against discovered links.
- **Risk**: assumes every currently-authored `lane_plan_source` URL is discoverable as a link on
  the pool page — a discoverability risk S1 (schedule/access) does **not** de-risk; if a URL isn't
  on the page, that basin's lane plan hard-fails under S4 (abort), which may force keeping the
  Altstetten-style out-of-scope carve-out rather than "revisiting" it (see the corrected
  [[discovery-driven-providers]] note). Surface any non-discoverable URL in this slice's report.
- **Depends on**: S1 (the go/no-go gate — everything waits on the S1 pause; S2 first builds
  `page_provider`, it is not inherited from S1).

### S3 — Roster + geo from providers; retire registry.yaml and committed catalog.json

- **Goal**: Build the identity spine and geo from a live WFS/page-index provider, not committed files.
- **Touches**: `roster_provider`, `build/seed.py` + `build/reconcile.py` (spine from provider),
  `storage/catalog_json.py` (WFS live vs. snapshot), xref-key sourcing.
- **Acceptance**: The provider-built ~57-pool spine + geo **matches** the current catalog on
  `PoolId`, name, facility `kind`, and lat/lon (golden test); `build` reads neither `registry.yaml`
  nor committed `catalog.json`; an unreachable WFS makes the build exit non-zero (this slice ships
  a **local** abort at the roster step; the general abort-orchestration/atomic-swap is S4).
- **Note**: this **reverses the documented offline/no-network build guarantee** (`etl/build.py:5`,
  CLAUDE.md) — recorded in Decisions.
- **Depends on**: S1 (go/no-go gate).

### S4 — Fail-fast, abort-whole-build

- **Goal**: Replace every green-exit-with-a-hole with a whole-build non-zero abort.
- **Touches**: `etl/build.py` / `build/compose.py` (abort orchestration, no partial write),
  `providers/schedule_scraper.py` (`scrape-gold` no skip), `etl/lane_plans.py`
  (`LanePlanUnavailable` → abort), the stale-store fetch-set invariant, `cli.py` exit codes.
- **Acceptance**: A build with one unparseable **declared/discovered** source exits non-zero and
  leaves the prior gold DB **content-unchanged** (row/table equality via a content digest, not a
  file-byte hash — a rolled-back/temp-swapped SQLite file can differ byte-wise while logically
  identical); the abort message carries the typed `ProviderError`; the single-source-of-truth and
  fetch-set-derivation tests are updated to the new semantics; no code path exits 0 with a missing
  declared fact.
- **Added by S2 (2026-07-29):** an authored `lane_plan_source.url` that its pool page **fails to
  advertise** (so discovery never fetches it) is today a **silent drop** — no `LanePlanMiss`, no
  `UnboundPlan`. S4 must make this a surfaced/aborting case (compute `authored − discovered` and
  fail loud), since "no silent drop" is rule 4. Not just PDF-fetch failures.
- **Depends on**: S2, S3.

### S5 — SOURCE every residual curated fact-class (per the S1 gap report; GO decision: no data loss)

> **Scope grew at the S1 GO gate (2026-07-28):** the owner chose *source the residue, don't drop
> it*. So S5 is no longer "source-or-drop" — it must **build providers** for the five
> `not-in-source` classes. This is large enough that **S5 will very likely split into its own
> plan(s)** (one per provider); this slice's acceptance is the *contract those sub-plans satisfy*,
> and closures are already proven sourced (route to `sourced-by-notice`, not residue).
- **Goal**: Provide a website-sourced producer for each residual class rather than dropping it:
  - **prices** → a `price_provider` over a discovered price page (the discovery hop from S2).
  - **basin physicals for the 5 NULL-prose pools** → another WFS/page field or per-page parse, so
    `kind`/dims/lanes are sourced beyond the current 2/7 (`infrastruktur` covers only city,
    bungertwies today).
  - **richer access (`lane_swim`/`family`/`adults_only`)** → extracted from the Belegungsplan lane
    doc or finer page text, since the flat timetable's category vocabulary is closed and cannot
    emit them.
  - **per-basin schedule split** → route the flat facility-level timetable to basins (needs a rule
    or a per-basin source; if genuinely impossible, this is the ONE class that may still be dropped
    with a recorded decision — but only after an extraction attempt is shown to fail).
  - **holiday policy** → from a discovered/parsed signal if one exists; else the recorded-drop
    exception applies.
- **Touches**: `price_provider`, richer-access extractor (Belegungsplan/page), basin-physical
  provider for NULL-prose pools, `providers/infrastruktur.py` (formalize), `notice_provider`
  (closures), `domain`, `docs/concepts/*` + `docs/entities/basin`.
- **Acceptance**: (1) A committed **field→producer table** maps *every* surviving domain field to
  exactly one **provider module** (drops are the recorded exception, allowed only for a class with
  a demonstrated failed extraction attempt — currently at most per-basin-split / holiday-policy);
  a test asserts the table covers all serialized `facility_doc` fields (no field unlisted). (2) A
  test asserts `build` reads **no** fact from `data/pools/*.yaml`. (3) Each residue fact-class has a
  dated `sourced-by-<module> | dropped-after-failed-extraction` decision in the Decisions section.
- **Depends on**: S1 (gap report), S2 (discovery hop feeds the price/access sources), S4 (fail-fast).

- **Decomposition (2026-07-29, owner chose "continue S5 in this worktree"; the S1 residue is
  SMALLER than reported — the S1 harness read only the pool-page timetable + WFS prose, missing the
  central price page and the Belegungsplan PDFs which are real providers):**
  - **S5a — field→producer audit** (do first): a committed, test-asserted table mapping every
    serialized `facility_doc` field to its producer, separating *already-sourced* (schedules/access
    → schedule scraper; **prices → the EXISTING `price_scraper`, already wired into scrape-gold**;
    closures → notices; identity/geo → WFS roster; basin physicals → `infrastruktur` for 2/7) from
    the *genuine residue* (richer access, per-basin split, holiday policy, physicals for 5 NULL-prose
    pools). This de-risks the rest — no provider is built for a fact already sourced.
  - **S5b — `geo_sport_id` from WFS `poi_id`** (shrinks the crosswalk by one field).
  - **S5c — richer access + per-basin split from the Belegungsplan PDFs** (the lane docs are
    per-basin and session-typed; feasibility TBD by S5a — SOURCE if the parser yields it, else DROP).
  - **S5d — recorded DROPs after demonstrated failed extraction**: basin physicals for the 5
    NULL-prose pools (probed: absent from both page and WFS prose), holiday policy, and any residue
    S5c can't source. Each with a dated decision.

### S6 — Delete the curated-YAML tier and reconcile docs

- **Goal**: Remove the deprecated inputs and update the knowledge base to the as-built reality.
- **Touches**: delete `data/pools/*.yaml` + `data/registry.yaml` (+ `data/catalog.json` if S3
  makes WFS live); `data/calendar/*.yaml` decision; grep-asserted single-source test; `CLAUDE.md`;
  mark [[discovery-driven-providers]] `status: implemented`; excise the superseded parts of
  [[lane-plan-url-binding]]; `docs/summaries/`.
- **Acceptance (REVISED 2026-07-29 — end-state is "no curated-YAML-as-*truth*", not zero-YAML):**
  the owner accepted that a **thin irreducible crosswalk** remains (facts on no website: per-basin
  lane URL binding, `baditicker_poiid`/`crowdmonitor_keys`, `aliases`). So S6 deletes the curated
  **authoritative** payload — the per-pool **schedules/rules/prices/closures** in `data/pools/*.yaml`
  (now sourced) — and reduces the YAML to that named crosswalk (e.g. `data/crosswalk/*.yaml`), NOT
  to nothing. A clean build succeeds reading **only** the WFS/scrape providers **plus** the thin
  crosswalk; a test asserts `build`/`etl` read no *authoritative* fact (schedule/price/geo) from
  curated YAML; `CLAUDE.md` + [[discovery-driven-providers]] updated to the thin-crosswalk end-state.
- **Blocked-by (surfaced by S2, 2026-07-29):** the lane-plan **binding key** is irreducibly
  per-basin and undiscoverable (discovery yields only pool+url; a single-basin PDF header can't
  name its basin — `test_bungertwies_binds_by_url_despite_a_garbled_basin_hint`). So `data/pools/`
  cannot be deleted until S5 supplies a **sourced per-basin url→basin binding** to replace the
  authored `lane_plan_source`. Until then S6's "`data/pools/` absent" is unreachable for lane plans.
- **Depends on**: S5.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-07-28 | S1 | done | measurement-only harness; `schedule_scraper.py` NOT modified (spike invoked off production path); gap report + diff shipped as golden files under `tests/etl/fidelity/` not `docs/` | schedule fidelity measured for 1/7 pools (only `city` has a page fixture); 5/7 pools have NULL WFS prose | yes |
| 2026-07-28 | S1 | re-measured | user chose "close fixture gap first": fetched real stadt-zuerich pages for all 7 curated pools → schedule fidelity now 7/7; fixed stale evidence prose in the generator | basin physicals still 2/7 (NULL WFS prose unchanged) | yes (GO/NO-GO) |
| 2026-07-29 | S2 | done | fetch-set moved to discovery, but `lane_plan_source` RETAINED as the per-basin binding key (irreducibly per-basin; discovery knows only pool+url) — plan intent met, literal "remove" deferred to S6; `cli.py` touched (necessary wiring) | S6 cannot delete `lane_plan_source` from YAML without a per-basin binding replacement; an authored URL a page fails to advertise is currently a silent drop (→ S4 must surface/abort) | yes |
| 2026-07-29 | S3 | done | roster identity+geo now from live WFS (`etl/roster.py`); `registry.yaml` RETAINED, reduced to the crosswalk (xref keys/aliases/kaeferberg kind-override); WFS I/O at CLI composition root, `build_store` takes roster as data; `reconcile.py` untouched | golden test is a WFS parser round-trip (fixtures reshaped from `catalog.json`); only the INDOOR layer's real wire shape is pinned (by `test_geo_sport`) — a non-indoor WFS field rename is invisible until a live re-record | yes |
| 2026-07-29 | S4 | done | temp-DB+atomic-swap (`storage/atomic.py`) for all 3 commands (scrape-gold/scrape-lanes survive as SEPARATE commands, `seed_from` live copy); skip-and-report + persisted-`LanePlanUnavailable` converted to hard aborts; the hole-persist code removed from `silver.py` (touch-list said `lane_plans.py`) | `LanePlanUnavailable` TYPE retained (lossless round-trip) but has NO ETL producer now — full type removal deferred (~S6); `build` no-commit branch unexercised (covered by atomic unit tests) | yes |
| 2026-07-29 | S5a | done | field→producer audit — machine-checkable `etl/field_sourcing.py` + coverage test over the real DTO fields; added a 4th `BUILD_METADATA` bucket for provenance tags (disclosed); prices confirmed already-sourced (curated-wins until S6) | audit coverage test guards only the 2 root DTOs, not nested leaf DTOs (disclosed scope) | yes |
| 2026-07-29 | S5b | done | `geo_sport_id` now SOURCED from the WFS `poi_id` (`build_spine` stamps it), reclassified crosswalk→sourced; removed the field from `IdentityDTO` + the null `registry.yaml` placeholder; +7 geo_sport `pool_xref` rows (were 0 — `geo_sport_id` was always null) | `baditicker_poiid` NOT collapsed despite 6/6 indoor `poi_id` match — non-indoor layers have no recorded `poi_id`; deferred to a live multi-layer WFS record | yes |

## Decisions & divergences

- 2026-07-28 (pre-approval, scoping): Owner chose **full website-sourced rewrite** (not the
  narrower fail-fast-only or discovery-only options) and **abort-whole-build** fail semantics over
  slice-red-keep-others — gold is all-or-nothing fresh, accepting that one flaky source blocks the
  whole build in exchange for never holding a partial/stale-but-green dataset.
- 2026-07-28 (pre-approval review, plan-critic): **Corrected a factual error** — basin `kind`,
  dimensions, and amenities were framed as unsourced/curated, but `providers/infrastruktur.py`
  already sources them from WFS prose (`build/seed.py:162-176`). Context, Design (added
  `basin_physical_provider`), S1's gap-report seeding, and S5 revised to retain/formalize that
  provider rather than re-source or drop those fields. The genuinely-unsourced residue narrows to
  basin-schedule-split, `lane_swim`/`family` access, prices, holiday policy, closures.
- 2026-07-28 (pre-approval review, plan-critic): **S5 acceptance made checkable** (B2) — the
  unverifiable "no field that is neither sourced nor deleted" replaced by a committed field→producer
  table asserted by a test to cover all serialized `facility_doc` fields.
- 2026-07-28 (pre-approval review, plan-critic): **S3 reverses the offline/no-network build
  guarantee** (`etl/build.py:1,8`, CLAUDE.md) — the roster/geo now come from a *live* WFS and a build
  aborts if WFS is unreachable. Accepted as a direct consequence of "every fact from a provider";
  CLAUDE.md's offline claim is updated in S6.
- 2026-07-28 (pre-approval review, plan-critic): **S4 atomicity specified** — build writes in place
  today (`etl/build.py:58`); S4 builds into a temp DB and atomically swaps, and "unchanged" is
  content/row equality, not a byte hash. Non-blocking critic notes on S2 dependency wording,
  discoverability risk, and the concept's stale "open decision" also applied.

### S1 (implementation)

- 2026-07-28 (S1, worktree-misrouting incident + remedy): the `slice-implementer` subagent wrote
  its three deliverables into the **main checkout** (`feat/new-ui`), not the plan worktree — the
  known hazard in memory `dev-implement-subagents-write-to-main-not-worktree`, which fired even
  though the session launched from the main checkout (the subagent cwd was pinned to the session's
  original launch dir, not the orchestrator's post-`EnterWorktree` cwd). The critic caught it as a
  **blocking** finding (files absent from the plan branch, outside its QA gates). Remedy applied by
  the orchestrator per the memory: patch-transferred the three files onto `plan/website-sourced-
  providers`, scrubbed the main checkout back to clean, and re-ran the **full** QA chain in the
  worktree (ruff/format/mypy clean; pytest 459 passed incl. 11 new; coverage 95.75%; crap OK).
- 2026-07-28 (S1, divergence — schedule_scraper.py untouched): the spike measures via the existing
  `parse_schedule`/`parse_notices` off their production path rather than extending them, honoring
  "no production data path changes." The plan listed that touch as optional. No functionality lost.
- 2026-07-28 (S1, findings for the GO/NO-GO gate): (a) only `hallenbad-city` has a saved page
  fixture — schedule fidelity is measured for **1/7** pools; the other 6 are honest recorded gaps,
  not fabricated. (b) City shows **zero** matched facility-level rules (its curated YAML is
  explicitly illustrative fiction; the real page parses to 8 rules). (c) WFS `infrastruktur` prose
  exists for only **2/7** pools (city, bungertwies); the other 5 are literal `"NULL"` — so
  `kind`/dimensions/amenities are `sourced-by-infrastruktur` for a *minority*, narrowing the S5 seed
  from the plan-critic round. (d) Even with prose, `kind` can mismatch (bungertwies parses `other`
  vs curated `lap`). (e) **Positive:** closures ARE reproduced by `parse_notices` (exact city
  range) → S5 closure class routes to `sourced-by-notice`, not dropped. (f) Residue confirmed
  `not-in-source`: basin-schedule-split, `lane_swim`/`family`/`adults_only` access, prices,
  `public_holiday_policy`.
- 2026-07-28 (S1, critic non-blocking suggestions — accepted, deferred): the `_kind_entry`
  "sourced" verdict is an `any_match` OR across prose pools (honest per-pool evidence is in the
  string, but a reproduced/not-reproduced *tally* would prevent over-reading); the `access.*`
  not-in-source verdicts should cite the scraper's **closed category vocabulary** as the structural
  reason rather than one fixture's observed kinds. Both are evidence-string polish on a spike whose
  output the human reads; deferred to the S1 gate review, not blocking.

### S1 re-measurement (real fixtures, 7/7) — the GO/NO-GO evidence

- 2026-07-28: on the user's "close fixture gap first" decision, fetched real stadt-zuerich.ch
  pages for all 7 curated pools (all HTTP 200, all parse: aemtler 3, blaesi 5, bungertwies 3,
  city 8, kaeferberg 6, leimbach 10, oerlikon 7 rules) and committed them under
  `tests/providers/fixtures/`. Schedule fidelity is now measured **7/7** (was 1/7).
- **`matched = 0` across all 7 pools — but the cause is instructive, not damning:**
  - **3/7 pools (blaesi, leimbach, kaeferberg) have ZERO curated schedule rules** (the minimal
    lane-plan-only YAMLs). The source is **purely additive** — it supplies 5 + 10 + 6 = 21 real
    rules the app currently lacks entirely. Clear win for sourcing.
  - **4/7 (bungertwies, city, oerlikon, aemtler) have illustrative curated schedules.** The
    zero-match there is dominated by (a) the source's **coarse access vocabulary** folding
    `LaneSwim`/`FamilyTime`/`AdultsOnly` → `PublicSwim`, and (b) different time-slot boundaries —
    curated fiction vs. real hours, not a factual contradiction of two real sources.
- **Positive: closures now sourced for 3 pools** (bungertwies `07-11..07-31`, city `07-04..08-07`,
  oerlikon `08-02..08-23`) with exact dates via `parse_notices` → the S5 closure class routes to
  `sourced-by-notice`, confirmed at scale.
- **Confirmed `not-in-source` residue** (unchanged, now over 7 real pages): richer access
  (`lane_swim`/`family`/`adults_only` — the scraper's category vocabulary is closed at
  public/women/seniors/school and none of the 7 pages even emit seniors/school), basin-schedule
  split, term/holiday scope, admission prices, holiday policy.
- **Basin physicals still 2/7** — only city & bungertwies have WFS `infrastruktur` prose; the
  other 5 are literal `"NULL"`, so `sourced-by-infrastruktur` for `kind`/dims/lanes holds for a
  minority. Narrows the S5 seed further.
- **Net GO/NO-GO read:** sourcing schedules is *good-to-better* (fills 3 empty pools, replaces
  illustrative fiction) and closures are sourced; the real cost of full removal is concentrated in
  four `not-in-source` classes (richer access, per-basin split, prices, holiday policy) + thin
  basin-physical coverage. The decision reduces to: drop those four classes, or source/curate them.

### S1 GO/NO-GO decision (2026-07-28)

- **Verdict: GO**, with the directive **"source the residue, don't drop it."** On the real 7/7
  evidence the owner chose to proceed S2→S6 and to have S5 **build providers** for the five
  `not-in-source` classes (prices, richer access, basin physicals for the 5 NULL-prose pools,
  per-basin split, holiday policy) rather than accept data loss. S5 accordingly grew (see the
  amended S5) and is expected to split into its own plan(s). Closures are already sourced, so they
  leave the residue. The only classes that may still end in a recorded *drop* are ones with a
  demonstrated failed extraction attempt (at most per-basin-split and holiday-policy).

### S2 (implementation) — discovery hop

- 2026-07-29 (S2, divergence #1 — reviewed, accepted): the fetch-set moved to discovered links
  (`etl/lane_plans.py` `fetch_set()` projects `DiscoveredLink.url`; `declared_source_urls` deleted;
  `cli.py scrape_lanes` drives off `discover_pages(...).links`), but `lane_plan_source` is
  **retained as the per-basin URL→basin binding key** (`etl/silver.py build_url_bindings`). The
  critic confirmed this satisfies the plan's Design intent ("fetch-set is the discovered links, not
  hand-authored `lane_plan_source`") and that the binding is irreducibly per-basin — discovery
  yields only pool+url and a single-basin PDF header cannot name its basin. The literal "remove
  `lane_plan_source`" is therefore deferred to S6 and gated on S5 sourcing a per-basin binding.
- 2026-07-29 (S2, finding — discovery is a superset): the city page advertises
  `belegungsplaene/city-variobecken.pdf`, a real lane sheet **no basin authored** — surfaced as a
  discovered link, never dropped. A candidate basin for S5 to source; any strict discovered==authored
  assumption is wrong.
- 2026-07-29 (S2, non-blocking → folded into S4/S6): (a) a non-advertised authored URL is currently
  a silent drop → **S4 must surface/abort** (recorded in S4). (b) `data/pools/` can't be deleted
  until S5 supplies a sourced per-basin binding → **recorded in S6 Blocked-by**. (c) `fetch_set`
  dedupes by URL across pools, discarding the second pool's `pool_id` stamp — revisit if binding
  ever becomes pool_id-load-bearing. Scope stayed clean (no roster/fail-fast/price work); the
  "~57-page fetch" concern does not materialize (`load_all()` filters `facility_doc IS NOT NULL` →
  only the curated ~7).

### S3 (implementation) — roster from live WFS

- 2026-07-29 (S3): the **offline/no-network build guarantee is now reversed in production** —
  `cli.build` fetches the roster from the live WFS via `etl/roster.py fetch_roster` and aborts
  non-zero (before `open_db`, so nothing is written) if the WFS is unreachable. `build_store` reads
  neither committed `catalog.json` nor `registry.yaml`-for-identity; it takes the roster as data
  (WFS I/O kept at the CLI composition root — `build_store` stays pure). Approved by critic.
- 2026-07-29 (S3, crosswalk retained — mirrors S2): `registry.yaml` is kept but reduced to the
  irreducible crosswalk WFS cannot carry — `baditicker_poiid`, `geo_sport_id`, `crowdmonitor_keys`,
  human `aliases`, and the kaeferberg `thermal` kind override. Physical thinning/deletion is S6.
- 2026-07-29 (S3, fidelity caveat): the golden test (`test_roster_spine_matches_committed_catalog`)
  pins a **WFS parser round-trip**, not live-WFS fidelity — its layer fixtures were reshaped from
  `catalog.json` because the environment can't record a live cassette. Only the **indoor** layer's
  real wire shape is pinned (by the pre-existing `test_geo_sport` cassette); the other 5 layers'
  assumed shape is validated only against reshaped fixtures. Residual risk: a non-indoor WFS field
  rename is invisible until a live re-record. Not blocking (catalog.json is a real WFS dump; real
  DTO parse/slug/kind-mapping are exercised), but a live per-layer cassette is owed.
- 2026-07-29 (S3, shrinks the crosswalk later): the real WFS payload carries `poi_id` (e.g.
  `"hb001"`) which `build_catalog` currently discards — so `geo_sport_id` is **WFS-sourceable**, an
  S5 candidate that would remove one field from the retained crosswalk.

### S4 (implementation) — fail-fast, abort-whole-build

- 2026-07-29 (S4, atomic approach chosen): **temp-DB-before-swap for all three commands**, not a
  single folded transactional build. `build` seeds an empty temp; `scrape-gold`/`scrape-lanes`
  `seed_from` a byte-copy of the live store, layer enrichment, and `os.replace` on success
  (`storage/atomic.py`). Consequence for the ledger/architecture: **scrape-gold and scrape-lanes
  survive as separate commands** (the build→scrape→scrape shape is unchanged; they just no longer
  mutate the live file in place). Content-unchanged-on-abort is asserted via `conn.iterdump()`
  digests, not byte hashes. Critic: approve.
- 2026-07-29 (S4, semantic reversal — as designed): `scrape-gold`'s skip-and-report and the
  persisted-`LanePlanUnavailable`-that-lets-the-facility-build are **gone**; a failed declared/
  discovered source now aborts the whole command non-zero with its typed `ProviderError`, gold
  untouched. The `LanePlanUnavailable` *value* type stays (round-trips) but has no ETL producer.
- 2026-07-29 (S4, judgment call — validated by critic): a pool page that fails to fetch but
  declares **no** lane source is a non-fatal audit line (strands no *declared* fact, per rule 4); a
  page failure that strands an **authored** source aborts via `undiscovered_authored`
  (`authored − discovered`), which also makes the stale-store fetch-set invariant loud.
- 2026-07-29 (S4 → S5/S6 gating): the `undiscovered_authored` abort is the guard that a declared
  lane source can't silently vanish — but it depends on `lane_plan_source` existing as the
  `authored` set. So when S6 deletes `lane_plan_source`, **S5's sourced per-basin binding must
  carry this invariant forward**, or the protection is lost with the field.

### S5 checkpoint decisions (2026-07-29)

- **End-state redefined (owner): "no curated-YAML-as-*truth*", NOT zero-YAML.** Across S2–S4 it
  became clear some facts are on no website (per-basin lane binding, `baditicker_poiid`/
  `crowdmonitor_keys`, `aliases`), so S6's zero-YAML goal is unreachable. Accepted: source the
  authoritative facts (schedules/geo/closures/prices/physicals-where-present); retain a **thin,
  clearly-named crosswalk** for the irreducible correlation/binding facts. S6 acceptance amended.
- **Proceed: continue S5 in this worktree** (owner), accepting it is research-heavy with possible
  dead ends and many sub-slices. S5 decomposed into S5a–S5d (see the S5 slice).
- **Finding — the residue is smaller than the S1 gap report:** the S1 harness measured only the
  pool-page timetable + WFS prose. It did NOT run the **central price page** (`price_scraper`,
  already wired into `scrape-gold`) or the **Belegungsplan PDFs** (per-basin, session-typed). So
  prices are ALREADY sourced, and richer-access / per-basin-split may be sourceable from the lane
  PDFs. S5a's audit establishes the true residue before any provider is built.
- **Probed drops (feasibility, 2026-07-29):** the 5 NULL-prose pools' pages carry no basin
  dimensions/kind (grep of blaesi/leimbach/kaeferberg fixtures) and their WFS prose is `"NULL"` — so
  basin physicals for them are not sourceable → accept absent (no curation), a recorded S5d drop.

### S5a residue map (audit result — the ground truth for S5b–d)

- **Already sourced** (no new provider): identity/geo → roster; schedules/access-categories/closures/
  notices/basins → schedule_scraper; **prices → price_scraper** (wired; curated-wins until S6);
  basin physicals (kind/dims/lanes/temp/diving/features) → infrastruktur (2/7 prose pools);
  `lane_plan` → belegungsplan.
- **Thin crosswalk** (on no website, retained): `geo_sport_id`, `crowdmonitor_keys`,
  `baditicker_poiid`, `aliases`, `lane_plan_source`.
- **Belegungsplan feasibility** (code-verified): **per-basin session times → SOURCEABLE** (S5c;
  one ParsedPlan per basin, but only for basins with a PDF); **richer access
  (lane_swim/family/adults_only) → DROP** — `_code_to_access` maps only to
  {PublicSwim, SchoolReserved, ClubReserved}; the legend encodes lane *ownership*, not session
  *subtype*, so neither the timetable (S1) nor the lane PDF can emit them.
- **Drops (residue, S5d)**: richer access (above), `amenities` (distinct from sourced `features`),
  `public_holiday_policy`, `lockers`, `accessibility`, `last_admission_before`, basin `exceptions`,
  `measured_temp_c`, and basin physicals for the 5 NULL-prose pools (probed absent).
- **Net**: S5b (geo_sport_id from WFS poi_id) and S5c (per-basin split from lane PDFs) are the only
  build work left; everything else is already-sourced or a recorded drop.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/website-sourced-providers.md` (what EXISTS now, not what was intended).
