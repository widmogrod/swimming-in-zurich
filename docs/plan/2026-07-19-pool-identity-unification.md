---
type: plan
status: approved         # owner-approved 2026-07-19; run /dev:implement to execute
created: 2026-07-19
feature: pool-identity-unification
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [S2]        # S2 lands the identity spine + schema flip — the riskiest slice; human-review before wiring the app
scope: backend — unify pool identity so /swim ↔ /pools join and `uncurated` goes live, via a
       DB-enforced identity spine + one reconcile/compose builder. PURE typed Python, no
       orchestration framework. Schedule/price/basin row-normalization and committed snapshots are
       DEFERRED to follow-up plans.
links: ["[[data-layer-architecture]]", "[[2026-07-19-sqlite-sot-backend-redesign]]", "[[gold-store]]", "[[fastapi-service-integration]]"]
---

# Plan — pool-identity unification (the SoT-refactor delta)

Executes the identity-spine cut of the design agreed in [[data-layer-architecture]] (output of a
9-agent design + scrutiny panel; all four lenses converged on this minimal slice). The
single-source-of-truth refactor landed the runtime plumbing (one read-only gold DB, offline
`swimzh build` from committed `data/` YAML, git-ignored `.db`, fail-fast) but did **not** unify
identity — it materialized the split-brain as two un-joinable tables in the one store. This plan
closes that, and makes the class of bug **unrepresentable by construction** (DB `UNIQUE` + one
id-minting seam) — the owner's stated preference for typed/DB-enforced correctness.

## The problem (verified on a fresh build)

- `facility.facility_id ∈ {aemtler, bungertwies, city, oerlikon}` (short) vs
  `catalog.pool_id ∈ {hallenbad-city, flussbad-…}` (long) — **intersection = ∅**. Same pool, two
  rows, no shared key.
- `/swim` reads `facility`, `/pools` reads `catalog` → **disjoint**; no path from a catalog pool
  to its schedule.
- `uncurated` is never produced at runtime (`SwimData` port has no roster; `find_swim_options` gets
  no registry) — the UI guesses it client-side by *name*.
- `scrape-gold` bypasses `silver.reconcile` (`cli.py` → `write_gold` directly) and writes long
  catalog ids into the short-id `facility` PK — a live gold-internal PK split-brain, currently
  papered over by the `drop_curated_duplicates` name-match filter (a symptom patch, not a cure).
- Schema is a `doc` blob per row (`facility.doc`, `catalog.doc`) — the opacity that permits the above.

## Design (signature altitude)

Full block design in [[data-layer-architecture]]. The pieces this plan lands:

- **Canonical namespace.** `pool.id = slug(name)` (existing `domain/catalog.slug`), minted once when
  the catalog is generated. Every *other* identifier is a **value pointing at `pool.id`**, never a PK.
- **Identity spine (DB-enforced).** One `pool` table IS the registry (all ~57 pools, canonical id PK,
  a **derived** `curation_status`), plus
  `pool_alias(norm TEXT, UNIQUE(norm))` and `pool_xref(namespace, ext_id, UNIQUE(namespace, ext_id))`.
  A second id claiming one pool → a write-time `IntegrityError`. `STRICT` tables, FKs `ON DELETE CASCADE`.
- **`SourceRef` — providers emit references, never ids.** A small closed union
  `Xref(namespace, ext_id) | Name(display) | BasinHint(text) | Global` accompanies each provider payload.
  `etl/scrape._facility`'s `FacilityId(entry.pool_id)` id-minting is **deleted**.
- **`reconcile.resolve(SourceRef) -> Result[PoolId]` — the SOLE canonical-id producer**, by **lookup,
  never fuzzy** (xref → alias(norm) → basin-hint index; unresolved/ambiguous → loud `Err` naming
  offenders; unmatched refs surface as an inspectable list). Relocates `silver.reconcile` +
  `registry` + `attach_lane_plans` discipline. The store's write side is typed so a caller cannot
  reach a gold row without a reconciled id.
- **`compose` — declarative curated-wins merge.** Group reconciled aspects by `PoolId`, fold into one
  facility using an **aspect→precedence map** (not per-provider `if` arms); derive `curation_status`
  (curated iff ≥1 basin with ≥1 rule) — never authored. Replaces `drop_curated_duplicates`.
- **One cleaning home** `build/normalize.py` — pure, idempotent field normalization; hoists the
  byte-identical `_normalise` currently duplicated in `registry.py` and `silver.py`.
- **Enforcement is honest.** A Python `NewType`/`FacilityId` is **not** a private constructor — mypy
  accepts `PoolId("anything")` anywhere. The airtight lock is the DB `UNIQUE` constraint; back it with
  a **grep-guard test** forbidding canonical-id construction outside the seed loader + `reconcile`
  (reusing the repo's existing "no `data/` reads at runtime" grep-guard pattern). Document the
  boundary as **grep + DB**, never "the compiler forbids it".

## Invariants to preserve (do not regress)

Pure/deterministic domain core (resolver, eligibility) untouched; errors-as-values across
boundaries; the three never-merged states (open / closed(reason) / uncurated) — this plan makes
`uncurated` *real at runtime*, never merges it; provenance always attached; ports-as-Protocols, one
composition root, env only in config; committed generated artifacts stay reviewable text; the app
keeps reading **only** the gold DB (never `data/` at runtime); `.db` stays git-ignored and is built
offline + deterministically (a "build-twice → equal rows" test guards it).

## Out of scope (deferred to follow-up plans)

- **Full row-normalization** of the schedule/basin/price payload off the `doc` blob
  (`schedule_rule`, `basin`, `schedule_exception`, `closure`, `notice`, `price`, `locker`,
  provenance-per-aspect + total weekday-mask / `SessionAccess` row↔domain mappers). This plan keeps
  the composed schedule payload as a **typed blob on the `pool` row**, keyed by the canonical id.
  Normalizing it is a separate plan (`schedule-schema-normalization`) — the identity spine here is
  what actually cures the split-brain; the blob-vs-rows choice is orthogonal to identity.
- **Committed frozen snapshots + `refresh`/`verify` two-phase** (per-source `.json` + manifest with
  `fetched_at`/`sha256`). Resilience/replay for the brittle scrapers — a separable determinism/audit
  decision; the id fix does not depend on it. `build` stays: live-or-frozen inputs → deterministic
  offline transform.
- **Dagster / any DAG-orchestration framework.** The stages are pure typed-Python functions; a
  framework becomes an additive `swimzh/orchestration/` skin only when scheduled/observable `refresh`,
  backfills, or lineage are needed (original plan milestone 6). Nothing here couples to it.

## Slices

Each is one vertical, shippable increment through the QA + adversarial-review gates. Ordered by
value/risk: S1 unblocks, S2 is the centerpiece (identity spine), S3 delivers the user-visible payoff,
S4 closes the scrape hole with the compose merge.

- **S1 — Canonical id + crosswalk in the inputs (unblocker).** *(S–M)*
  Re-key the curated `data/pools/*.yaml` and `data/registry.yaml` to the catalog **slug** id
  namespace (`city` → `hallenbad-city`, via `domain/catalog.slug`). Preserve every legacy id as an
  alias/xref (lossless). Update the curated DTOs/loaders that key on `facility_id`. No schema/app
  change yet — the existing two-table gold still builds.
  **Acceptance:** a test asserts every curated `facility_id ∈ catalog pool_id` (referential
  integrity) and every legacy short id still resolves by lookup; `swimzh build` green; old `/swim`
  unchanged.
  **Depends on:** —

- **S2 — Identity spine: `pool` table = registry + `reconcile` as the sole id minter.** *(L — pause after)*
  Replace `facility` + `catalog` with ONE `pool` table (all ~57 pools, canonical id PK, **derived**
  `curation_status`), plus `pool_alias(UNIQUE norm)` / `pool_xref(UNIQUE namespace, ext_id)` as
  `STRICT` tables. Introduce the `SourceRef` closed union and `build/reconcile.resolve(SourceRef) ->
  Result[PoolId]` as the **sole** canonical-id producer (relocating the `silver.reconcile` /
  `registry` lookup discipline); type the store write side to accept only reconciled ids. Hoist
  `_normalise` into `build/normalize.py`. Curated schedule payload stays a typed blob **on the pool
  row** (row-normalization is out of scope). `build` writes it; retire the separate `catalog` table.
  **Acceptance:** build yields exactly 57 `pool` rows with correct derived statuses; every legacy id
  lands as an alias/xref (lossless, asserted by a cutover test before the old tables are dropped); a
  **duplicate alias/xref raises `IntegrityError`** (the constraint is proven, not assumed); a
  **grep-guard test** fails if a canonical id is constructed outside the seed loader + `reconcile`; a
  build-twice → equal-rows determinism test; QA green. **Pause for human review** before S3.
  **Depends on:** S1

- **S3 — Wire `uncurated` live + join `/swim` ↔ `/pools`.** *(M)*
  `SwimData` → `SwimStore` Protocol with `roster()` (all pools) + `facility(id)`;
  `find_swim_options(..., uncurated = roster − scheduled)` so the backend emits `uncurated`
  statuses; `/pools` and `/pools/{id}` read the one `pool` table (joining to schedule by canonical
  id); **retire the UI's client-side name-join** (the usability-pass workaround). Retires the dead
  `find_swim_options(registry=None)` path.
  **Acceptance:** `/swim` at a location returns `uncurated` statuses live for catalog pools without
  schedules; `/pools/{id}` resolves a catalog pool to its schedule from the same store; the UI reads
  statuses from the API, not by name; the three states stay un-merged.
  **Depends on:** S2

- **S4 — One builder: `SourceRef` providers + declarative `compose` (close the scrape hole).** *(M)*
  Providers emit `(SourceRef, payload)`; **delete** `scrape._facility`'s `FacilityId(entry.pool_id)`.
  Route `scrape-gold` through `reconcile` (lookup → canonical id, never a long id into the PK) and
  `compose` (declarative aspect→precedence map, curated-wins). **Delete `drop_curated_duplicates`** —
  compose subsumes it and, unlike the filter, **keeps** a curated pool's scraped price (per-aspect
  merge, not whole-row drop). One offline builder path; no second door to a gold row.
  **Acceptance:** `build` and `scrape-gold` write the same id namespace; a test builds both ways and
  asserts id/PK consistency; an unreconcilable scrape name → typed `Err`, reported, never a silent
  wrong-pool write; a test proves City keeps **both** its curated schedule and its scraped price
  (the merge the old filter dropped); `drop_curated_duplicates` is gone.
  **Depends on:** S3

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/pool-identity-unification.md` (what EXISTS now, not what was intended).
