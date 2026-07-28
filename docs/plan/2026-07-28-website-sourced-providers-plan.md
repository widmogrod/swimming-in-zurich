---
type: plan
status: approved         # draft -> approved -> in-progress -> done
created: 2026-07-28
feature: website-sourced-providers
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
- **Depends on**: S2, S3.

### S5 — Resolve every residual curated fact-class (per the S1 gap report)

- **Goal**: Route each fact-class in the S1 **residue** (basin-*schedule*-split, `lane_swim`/
  `family` access, prices, `public_holiday_policy`, closures) to exactly one of:
  sourced-by-provider, or dropped-from-domain-with-a-recorded-decision. (`kind`/dimensions/
  amenities are **already** sourced by `infrastruktur` — this slice only formalizes that binding,
  it does not re-source or drop them.)
- **Touches**: `price_provider`, `notice_provider`, the basin-schedule-decomposition rule (or its
  removal), `providers/infrastruktur.py` (formalize as the `kind`/amenities provider),
  `domain` (drop any abandoned field), `docs/concepts/*` + `docs/entities/basin` (record decisions).
- **Acceptance**: (1) A committed **field→producer table** maps *every* surviving domain field to
  exactly one producing provider module (or names the PR that deleted the field); a test asserts
  the table covers all serialized `facility_doc` fields (no field unlisted). (2) A test asserts
  `build` reads **no** fact from `data/pools/*.yaml`. (3) Each residue fact-class has a dated
  `sourced-by-<module> | dropped` decision in the plan's Decisions section.
- **Depends on**: S1 (gap report), S4 (fail-fast in place before dropping fallbacks).

### S6 — Delete the curated-YAML tier and reconcile docs

- **Goal**: Remove the deprecated inputs and update the knowledge base to the as-built reality.
- **Touches**: delete `data/pools/*.yaml` + `data/registry.yaml` (+ `data/catalog.json` if S3
  makes WFS live); `data/calendar/*.yaml` decision; grep-asserted single-source test; `CLAUDE.md`;
  mark [[discovery-driven-providers]] `status: implemented`; excise the superseded parts of
  [[lane-plan-url-binding]]; `docs/summaries/`.
- **Acceptance**: A clean build succeeds with `data/pools/` and `data/registry.yaml` **absent**;
  full QA chain green; a test asserts those paths are not referenced by `build`/`etl`; `CLAUDE.md`
  no longer describes curated YAML as a source of truth.
- **Depends on**: S5.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

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

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/website-sourced-providers.md` (what EXISTS now, not what was intended).
