---
type: concept
name: techdebt-remediation-roadmap
status: proposed
updated: 2026-07-20
links: ["[[2026-07-19-pool-identity-unification]]", "[[data-layer-architecture]]", "[[gold-store]]"]
---

# Tech-debt remediation roadmap (post pool-identity-unification)

> Output of a 6-agent planning panel (simplify-by-deletion / modularity-layering / poka-yoke-enforcement
> -> anti-over-engineering + invariant-preservation scrutiny -> synthesis). **Proposed** — each plan below
> becomes a `/dev:plan` when the owner picks it up. Goals: simpler, modular, poka-yoke, preserving every
> already-won invariant.

> **Progress (2026-07-20):** Owner selected **A, B, C** (D, E stay backlog). Plans drafted, reviewed
> against the code, and adjusted ([[layers-and-canonical-id]], [[retire-facility-table]],
> [[delete-legacy-geo-pipeline]]).
> - **Plan A DONE** — debt **#5** (`Global` deleted), the `normalize`/`BASIN_KIND_WORDS` half of **#2**
>   (leaves → `core`/`domain`), and the id-unification half of **#7** (one `PoolId`); layering guard
>   (`tests/test_layering.py`) in place.
> - **Plan B DONE** — debt **#1** (app reads only `pool.facility_doc`; `write_schedules` the single
>   writer), **#4** (`curation_status` derived at read), **#7** (the write side is typed on `PoolId`),
>   #6a-blob duplication retired; four B5 guards lock it in. The `facility` table is now write-only-dead.
>   Discovered for C: **TWO** legacy `write_facilities` writers remain (`pipeline.run` + `build_store`).
> - **Plan C is next** — delete `build-gold`/`pipeline`/`raw` + `resolve_name`, and the now-dead
>   `facility` table + both `write_facilities` sites + `write_gold`/`etl.gold`.

## Executive summary

Fold the three proposals into one program that keeps Proposal 1's deletion backbone but swaps in Proposal 3's two strictly-simpler mechanisms (a single PoolId-typed write_schedules seam and derive-curation_status-at-read) and only the cheap subset of Proposal 2's layering (leaf relocations + a lightweight grep-guard), dropping the flagged over-engineering: the build->assemble rename, the full AST layer-DAG walker, promoting pyright to a second CI gate, the basin-hint-index consolidation, and any new build/pipeline seam wrapped around dead code. Sequence across five plans by risk/value. Plan A (layering leaves + one canonical PoolId) lands first because it is zero-behavior-change and is the unstated precondition for a PoolId-typed write side — without it, that type re-cements the wrong storage->build direction. Plan B then retires the facility table through one write seam onto pool.facility_doc, gated on a geo-stamp prerequisite so /swim distance survives, and drops the stored curation_status column so no writer can desync it. Plan C deletes the legacy geo pipeline as an explicit product decision (owner sign-off; rewrite the resolve_name cutover test first). Plan D adds partial-batch resilience to scrape while keeping ambiguous hints structurally fatal. Plan E clears the calendar pyright findings without adding a gate. Every already-won invariant (DB UNIQUE spine, single minter, grep-guard, three un-merged states, one gold DB, errors-as-values) is preserved; #6a/#6b/#6c/#9/#10 stay out of scope as additive structure off the simplicity critical path.

---

## swimzh tech-debt remediation roadmap

Backbone = Proposal 1's deletions, corrected for two verified honesty gaps (build-gold is tested, not dead; `resolve_name` backs the cutover test), with Proposal 3's simpler mechanisms swapped in and only the cheap slice of Proposal 2's layering. All claims below were grep-verified against the tree.

### 1. Debt inventory to remediation move

| # | Debt | Move | Tag | Effort | Plan |
|---|------|------|-----|--------|------|
| 1 | Transitional `facility` table duplicates `pool.facility_doc`; `/swim` reads `facility` | Flip reads to `pool.facility_doc`; delete the table + its access layer | simpler + modular | L | B |
| 2 | Backward layer dep: `domain/registry` + `etl/silver` import `build.normalize`/`build.reconcile`; `storage` imports `build.seed` under TYPE_CHECKING | Push leaves DOWN: `normalize`->`core`, `BASIN_KIND_WORDS`->`domain`, spine row DTOs->`storage/rows.py`; fence with grep-guard | modular + poka-yoke | M | A |
| 3 | `scrape-gold` whole-batch abort on one unmatched WFS name | Split `resolve_all`->`ReconcileOutcome(resolved, unresolved)`; ambiguous stays fatal `Err`, benign misses reportable | poka-yoke | M | D |
| 4 | `scrape-gold` leaves `curation_status` stale (writes `facility`, not `pool`) | DROP the stored column; derive at read from `facility_doc` presence | poka-yoke | M | B |
| 5 | `Global` `SourceRef` variant emitted nowhere | Delete variant + its two match arms + test + doc bullet | simpler + poka-yoke | S | A |
| 6a | Full row-normalization of schedule/price/basin blob | **Leave as-is** — additive structure, not on the simplicity path; the blob-*duplication* half is retired by Plan B, which is the only part that pays now | — | — | — |
| 6b | Frozen snapshots + two-phase refresh/verify | **Leave as-is** — new capability, no current desync it fixes | — | — | — |
| 6c | Dagster/DAG orchestration | **Leave as-is** — critics flagged wrapping a new `build/pipeline` seam around code Plan C *deletes*; do not build it | — | — | — |
| 7 | `write_facilities` typed on `FacilityId`, not `PoolId` | Retire via B's `write_schedules(tuple[(PoolId, Facility)])` seam; unify `FacilityId`->one `PoolId` NewType in A (removes compose.py:118 round-trip) | all-three | M | A + B |
| 8 | Pyright `reportPrivateUsage`: `calendar_codec` reads `ZurichCalendar` privates | Public read surface + `__eq__` on `ZurichCalendar`; rewrite `to_dto` + tests. **Do NOT** promote pyright to a second CI gate (over-scope; mypy stays the one gate) | poka-yoke | S | E |
| 9 | `tests/build_stage/` breaks the tests<->src mirror (`build` reserved) | **Leave as-is**; if it bites, override `norecursedirs` in pyproject + a shadow-dir guard. **Reject** the `build`->`assemble` package rename (widest blast radius in any proposal for the lowest-value debt) | — | S (deferred) | — |
| 10 | `belegungsplan` GridSpec parses only City's PDF layout | **Leave as-is** — calibration debt needing real per-pool PDFs, not a structural refactor | — | — | — |

### 2. Follow-up plans (ordered by risk/value)

#### Plan A — "Right-size the layers + one canonical id"  (lowest risk, zero behavior change)
**Goal:** every dependency points down and one `PoolId` type exists, so B's PoolId-typed write side lands without cementing storage->build.
**Depends on:** nothing. **Must precede B** (self-flagged by Proposal 3: a PoolId-typed `write_schedules` deepens storage->build unless `PoolId` is relocated first).
- **A1** Move `normalize`->`core/normalize.py` (zero-import leaf); repoint the 4 importers (`domain/registry`, `etl/silver`, `build/reconcile`, `build/seed`); delete `build/normalize.py`.
- **A2** Move `BASIN_KIND_WORDS`->`domain` (beside `BasinKind`); repoint `build/reconcile` + `etl/silver`.
- **A3** Unify `FacilityId`->a single `PoolId = NewType(...)` in `domain/models`; one-step `FacilityId = PoolId` alias then delete; remove the `FacilityId(str(pool_id))` round-trip at `compose.py:118`. Decide the guard policy for the reconstruction sites (`codec.py:124`, `curated.py:106/133`) — see open questions.
- **A4** Move `PoolSpine`/`PoolRow`/`PoolAliasRow`/`PoolXrefRow` from `build/seed`->`storage/rows.py` typed on `domain.PoolId`; delete the `if TYPE_CHECKING: from swimzh.build.seed import PoolSpine` at `sqlite_repo.py:29`.
- **A5** Delete the `Global` variant end-to-end (#5); add the lightweight import-direction grep-guard (no `from swimzh.build` under `domain/**` or `etl/**`; `storage/**` imports nothing from `build`).
**Simpler/modular/poka-yoke:** one id type instead of two; storage<->build edge broken (storage imports nothing from build); the grep-guard makes the fixed direction falsifiable and cheap — no AST DAG walker.

#### Plan B — "Retire the facility table"  (highest value; touches the `/swim` read path)
**Goal:** one PoolId-typed schedule write seam onto `pool.facility_doc`; delete the duplicate `facility` table. Retires #1, #4, #6a-blob, #7.
**Depends on:** Plan A (PoolId in low layer + row DTOs relocated). **This plan alone owns the collapse** — no half-collapse across plans.
- **B1** Stamp authoritative catalog (WFS)/geo_sport geo onto the curated `Facility` before it is serialized into `facility_doc` (in `build/seed` and `build/compose`), via `replace(facility, geo=entry.geo or facility.geo)`; add a parity test asserting identical geo for the ~4 curated pools vs what `build-gold` merges today. **Load-bearing prerequisite** — without it, collapsing the table silently degrades `/swim` distance (geo is only fully present on the read path after `build-gold` today).
- **B2** Add `write_schedules(conn, keyed: tuple[tuple[PoolId, Facility], ...])` writing each blob to `pool.facility_doc`; flip `GoldRepository.load_all/get/count` and `GoldSwimStore` to read `facility_doc` (WHERE NOT NULL). Parity-test against today's `load_all`.
- **B3** DROP the stored `curation_status` column; derive at read from `facility_doc` presence via a shared `is_curated` helper (present + >=1 basin with >=1 rule -> curated). **[PAUSE for human review — schema change + read-path semantics.]**
- **B4** Route `scrape-gold`/`scrape-lanes` through `write_schedules`; DELETE the `facility` CREATE TABLE, `write_facilities`, `etl/gold.write_gold`, and the dead `load_catalog`.
- **B5** Add the new guards (no-`facility`-table SQL grep-guard; single-writer guard; no writable `curation_status` column).
**Simpler/modular/poka-yoke:** one blob copy instead of two; one write door typed on the grep-guarded `PoolId` (unreconciled writes are unrepresentable — retires #7); status derived from the same schedule fact it describes, so no writer can desync it (retires #4 by construction).

#### Plan C — "Delete the legacy geo pipeline"  (largest deletion; low CODE risk, PRODUCT decision)
**Goal:** collapse to the ONE offline builder the design already names.
**Depends on:** B1 (offline geo stamp) + **owner sign-off** (deleting `build-gold` removes live WFS geo refresh; it is tested, not dead code).
- **C1** Rewrite `tests/data/test_identity_crosswalk.py` (the lossless-cutover guard) off the alias table BEFORE deleting `resolve_name` — Proposal 1 missed that this test depends on `resolve_name`.
- **C2** Delete `etl/pipeline.py`, `etl/raw.py`, `silver.reconcile` (KEEP `attach_lane_plans`), `registry.resolve_name/resolve_geo_sport/resolve_crowdmonitor`, `cli.build_gold` + the `build-gold` subcommand, and fold `etl/build.build_store` into the offline `build` path; remove their now-dead tests.
- **C3** Update `CLAUDE.md`/`README`/`gold-store.md`/data-layer docs (geo now flows via committed `catalog.json` + `build-catalog`); build-once smoke + full QA (**pytest before crap** so the coverage floor recalibrates on the smaller surface; ratchet `fail_under` up if it rises).
**Simpler/modular/poka-yoke:** the parallel raw->silver->gold id path is gone; one builder, one geo provenance (committed, reviewable WFS `catalog.json`).

#### Plan D — "Resilient reconcile"  (small, deliberate policy change)
**Goal:** one unmatched WFS name no longer discards ~29 good scrapes, while ambiguous hints stay fatal.
**Depends on:** mostly independent; cleaner after B's single write seam. **Owner sign-off** (reverses the deliberate S4 whole-batch-abort).
- **D1** In `build/reconcile`, discriminate ambiguous (matches 2 pools -> hard `Err`, preserves never-attach-to-wrong-pool) from benign no-crosswalk miss; return `Result[ReconcileOutcome, ProviderError]` where `ReconcileOutcome(resolved, unresolved)` has a REQUIRED `unresolved` field.
- **D2** Rewire `cli.scrape_gold` to `compose(resolved)` + `write_schedules`, print `unresolved` to stderr, exit nonzero iff non-empty; tests for partial-success and ambiguous-stays-fatal.
**Poka-yoke:** the required `unresolved` field means a caller cannot silently swallow a miss; the dangerous case stays fatal by type.

#### Plan E — "Calendar pyright surface"  (tail, independent, optional)
**Goal:** clear the 12 `calendar_codec` `reportPrivateUsage` findings (#8) — findings only, not a new gate.
**Depends on:** nothing.
- **E1** Give `ZurichCalendar` a public read surface (`known_years`/`public_holidays`/`school_holidays`) + `__eq__` (confirm nothing uses a calendar as a dict key — a `Mapping` field makes a frozen dataclass unhashable); rewrite `storage/calendar_codec.to_dto` + its two tests to read the public surface.
**Poka-yoke:** encapsulation restored; do NOT promote pyright to a second enforced gate (mypy stays canonical per CLAUDE.md).

### 3. DELETE LIST (removed outright)
- `facility` CREATE TABLE in `sqlite_repo._SCHEMA` and every read of `facility.doc` (collapse to `pool.facility_doc`) — Plan B
- `storage/sqlite_repo.write_facilities` (superseded by `write_schedules`) — Plan B
- `etl/gold.py` (`write_gold` — only fed the facility table) — Plan B
- `storage/sqlite_repo.load_catalog` (dead: tests-only caller) — Plan B
- stored `pool.curation_status` column (derived at read) — Plan B
- `etl/pipeline.py`, `etl/raw.py`, `etl/silver.reconcile` (KEEP `attach_lane_plans`) — Plan C
- `domain/registry.resolve_name` / `resolve_geo_sport` / `resolve_crowdmonitor` — Plan C (after C1 rewrites the cutover test)
- `cli.build_gold` + the `build-gold` argparse subcommand; `etl/build.build_store` folded into `build` — Plan C
- `build/reconcile.Global` variant + its `resolve()`/`_ref_label()` arms + test + doc bullet — Plan A
- `build/normalize.py` (relocated to `core/normalize.py`, not truly gone) — Plan A
- the `FacilityId` NewType + the `FacilityId(str(pool_id))` round-trip at `compose.py:118` — Plan A
- the `if TYPE_CHECKING: from swimzh.build.seed import PoolSpine` reverse edge at `sqlite_repo.py:29` — Plan A
- the private reads `calendar._public/_school/_known_years` in `calendar_codec.py` + its two tests — Plan E

**Explicitly NOT deleted / NOT built:** the `build`->`assemble` package rename (#9), the full AST layer-DAG guard, a new `build/pipeline` orchestration seam (#6c), the basin-hint-index consolidation, and a second pyright CI gate — all flagged as over-engineering.

### 4. NEW GUARDS (make the fixes stick)
- **Import-direction grep-guard** (Plan A): no `from swimzh.build` under `domain/**` or `etl/**`, and `storage/**` imports nothing from `build` — mirrors the existing `data/`-at-runtime grep-guard; lightweight, not an AST walker.
- **Single canonical `PoolId`** in `domain` (Plan A): one NewType; construction still confined to `build/reconcile` + `build/seed` under the existing minter grep-guard (see open question on the codec/curated reconstruction carve-out).
- **No-`facility`-table SQL guard** (Plan B): assert no runtime SQL references a `facility` table (`FROM facility`/`INTO facility`).
- **Single-writer guard** (Plan B): `write_schedules` is the only function writing `pool.facility_doc`; `write_pools`/seed the only INSERT into `pool`/`pool_alias`/`pool_xref`.
- **Schema guard** (Plan B): `_SCHEMA` contains no `facility` table and no writable `curation_status` column — locks in derive-at-read.
- **Consistency test** (Plan B): scrape a schedule onto a previously-uncurated pool -> roster/`/pools` report `curated` and `/swim` serves it (fails on today's code).
- **`write_schedules` typed on `PoolId`** (Plan B): the type + minter grep-guard are the only door — an unreconciled write is unrepresentable (retires #7).
- **Geo-parity test** (Plan B1): `pool.facility_doc` geo == today's `build-gold` merge for the ~4 curated pools — guards `/swim` distance across the collapse.
- **`ReconcileOutcome` with required `unresolved`** (Plan D): benign misses cannot be silently ignored; ambiguous stays a typed fatal `Err`.
- **Rewritten crosswalk test** (Plan C1): lossless-cutover proven off the alias table, not `resolve_name`, before that method is deleted.

**Preserve as-won (do not weaken):** the `PoolId(` minter grep-guard (reconcile + seed only), DB `UNIQUE(norm)`/`UNIQUE(namespace, ext_id)` collision tests, build-twice->equal-rows determinism, errors-as-values/closed `ProviderError` + `assert_never`, the three un-merged states, one gold SQLite.

## Open questions (owner decisions)

1. Sole-minter guard vs FacilityId->PoolId merge: codec.py:124 and curated.py:106/133 reconstruct a canonical id from trusted persisted/DTO data — after unification these become `PoolId(...)` constructions the grep-guard polices. Do we (a) route them through a tiny `reconstruct_pool_id` boundary shim, or (b) extend the guard's ALLOWED set with an explicit comment? Option (a) keeps the guard strictly 'mint-from-external-ref only'; (b) is cheaper but dilutes the guard. Needs an owner call before Plan A3.
2. Deleting `build-gold` (Plan C) removes the only live WFS geo-refresh command — it is tested, not dead code. Confirm geo may permanently flow through the committed `catalog.json` + `build-catalog`, and that a future scheduled refresh (if ever wanted) returns as an additive `refresh` skin rather than a resurrected split-brain pipeline.
3. Plan D reverses the deliberate S4 'whole-batch abort is stronger than per-pool skip' decision. Confirm the owner accepts partial-success scrape given ambiguous hints stay structurally fatal (never-attach-to-wrong-pool preserved).
4. Plan B3 drops the `curation_status` CHECK-constrained column and derives at read (~57 rows parse `facility_doc`). Confirm acceptable for `/pools` latency and that build-twice-equal determinism + a NULL-blob->`uncurated` case stay green.
5. Plan E: is clearing only the calendar_codec findings enough for #8, or should catalog_json / test_belegungsplan privates also be cleared? Recommendation is to stop at calendar_codec and NOT add a pyright gate — confirm the owner does not want the second gate.
