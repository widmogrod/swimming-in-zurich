---
type: plan
status: draft            # PROPOSED — awaiting owner approval of the slice list before implementation
created: 2026-07-19
feature: pool-identity-unification
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [S2]        # S2 flips the store schema — the riskiest slice; human-review before wiring the app
isolation: worktree      # run in a git worktree; rebase onto the concurrent lane-reservations work before S5
scope: backend — unify pool identity so /swim ↔ /pools join, uncurated goes live, one builder, normalized store
links: ["[[2026-07-19-sqlite-sot-backend-redesign]]", "[[ux-usability-pass]]", "[[fastapi-service-integration]]"]
---

# Plan — pool-identity unification (the SoT-refactor delta)

Executes the re-scoped delta from [[2026-07-19-sqlite-sot-backend-redesign]] §0. The concurrent
single-source-of-truth refactor landed the runtime plumbing (one read-only gold DB, offline
`swimzh build` from committed `data/` YAML, git-ignored `.db`, fail-fast). It did **not** unify
identity — it materialized the split-brain as two un-joinable tables in the one store. This plan
closes that.

## The problem (verified on a fresh build)

- `facility.facility_id ∈ {aemtler, bungertwies, city, oerlikon}` (short) vs
  `catalog.pool_id ∈ {hallenbad-city, flussbad-…}` (long) — **intersection = ∅**. Same pool, two
  rows, no shared key.
- `/swim` reads `facility`, `/pools` reads `catalog` → **disjoint**; no path from a catalog pool
  to its schedule.
- `uncurated` is never produced at runtime (`SwimData` port has no roster; `find_swim_options` gets
  no registry) — the UI guesses it client-side by *name*.
- `scrape-gold` bypasses `silver.reconcile` (`cli.py` → `write_gold` directly) and writes long
  catalog ids into the short-id `facility` PK — a live gold-internal PK split-brain.
- Schema is a `doc` blob per row (`facility.doc`, `catalog.doc`) — the opacity that permits the above.

## Invariants to preserve (do not regress)

Pure/deterministic domain core (resolver, eligibility) untouched; errors-as-values across
boundaries; the three never-merged states (open / closed(reason) / uncurated) — this plan makes
`uncurated` *real at runtime*, never merges it; provenance always attached; ports-as-Protocols, one
composition root, env only in config; committed generated artifacts stay reviewable text; the app
keeps reading **only** the gold DB (never `data/` at runtime).

## Slices

Each is one vertical, shippable increment through the QA + adversarial-review gates. Ordered by
value/risk: S1 unblocks, S2 is the centerpiece, S3 delivers the user-visible payoff, S4 closes the
scrape hole, S5 is the no-tech-debt finish.

- **S1 — Canonical id + crosswalk in the inputs (unblocker).** *(S–M)*
  Re-key the curated `data/pools/*.yaml` and `data/registry.yaml` to the catalog **slug** id
  namespace (`city` → `hallenbad-city`, via `domain/catalog.slug`). Preserve every legacy id as an
  alias/xref (lossless). Update the curated DTOs/loaders that key on `facility_id`. No schema/app
  change yet — the existing two-table gold still builds. **Gate:** a test asserts every curated
  `facility_id ∈ catalog pool_id` (referential integrity) and every legacy short id still resolves
  by lookup; `swimzh build` green; old `/swim` unchanged.

- **S2 — `pool` table = registry (unify the two tables under one id).** *(L — pause after)*
  Replace `facility` + `catalog` with ONE `pool` table: all ~57 pools, canonical id PK, a
  **derived** `curation_status` (`curated` iff ≥1 basin with rules; else `uncurated`), plus
  `pool_alias(UNIQUE norm)` / `pool_xref(UNIQUE namespace, ext_id)` so a second id scheme is a
  write-time constraint violation. Curated schedule payload may remain a typed blob **on the pool
  row** this slice (normalized in S5) — the point here is one identity table, not yet full
  normalization. `build` writes it; retire the separate `catalog` table. **Gate:** build yields
  exactly 57 `pool` rows with correct derived statuses; legacy ids all land as aliases (lossless);
  a build-twice-equal determinism test; QA green. **Pause for human review** before S3.

- **S3 — Wire `uncurated` live + join `/swim` ↔ `/pools`.** *(M)*
  `SwimData` → `SwimStore` Protocol with `roster()` (all pools) + `facility(id)`;
  `find_swim_options(..., uncurated = roster − scheduled)` so the backend emits `uncurated`
  statuses; `/pools` and `/pools/{id}` read the one `pool` table (joining to schedule by canonical
  id); **retire the UI's client-side name-join** (the S5 usability-pass workaround). **Gate:**
  `/swim` at a location returns `uncurated` statuses live for catalog pools without schedules;
  `/pools/{id}` resolves a catalog pool to its schedule; UI reads statuses from the API, not by name.

- **S4 — One builder (scrape through reconcile).** *(M)*
  Route `scrape-gold` through `silver.reconcile` so it resolves ids by **lookup** and writes
  canonical ids — never long ids into the `pool` PK. **Gate:** `build` and `scrape-gold` write the
  same id namespace; a test builds both ways and asserts id/PK consistency; unreconcilable scrape
  name → typed `Err`, reported, not a silent wrong-pool write.

- **S5 — Normalize the schedule/basin schema off the `doc` blob (no-tech-debt finish).** *(L)*
  Replace the per-pool `doc` blob with normalized tables (`basin`, `schedule_rule`,
  `schedule_exception`, `closure`, `notice`, `price`, `locker`, provenance-per-aspect) per the
  design contract DDL, with total row↔domain mappers (weekday-mask bijection, `SessionAccess` union
  via `match`/`assert_never`). Resolver/eligibility unchanged. **Gate:** `:memory:` materialize →
  hydrate round-trip equality; property tests on mask/access; resolver tests still green off-DB.
  Rebase onto the concurrent lane-reservations work first (it owns the `basin.lane_plan_json` seam).

## Coordination

Run in a **git worktree** (`../swimzh-pool-identity`) isolated from the concurrent lane-reservations
`/dev:implement` session — it touches `lane_plan.py`/`belegungsplan.py`/the basin lane-plan seam,
and previously a concurrent `git reset` wiped uncommitted work. Commit each slice promptly; rebase
before S5.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |
