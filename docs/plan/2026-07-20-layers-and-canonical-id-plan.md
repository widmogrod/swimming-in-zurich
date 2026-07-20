---
type: plan
status: in-progress      # owner-approved 2026-07-20; /dev:implement executing on main (worktree retired — see [[2026-07-19-pool-identity-unification]] Decisions)
created: 2026-07-20
feature: layers-and-canonical-id
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: []          # zero-behavior-change; no schema/read-path risk
links: ["[[techdebt-remediation-roadmap]]", "[[data-layer-architecture]]", "[[2026-07-19-pool-identity-unification]]"]
---

# Plan A — Right-size the layers + one canonical id

## Context

Plan A of the [[techdebt-remediation-roadmap]] (post pool-identity-unification). Lowest-risk,
**zero behavior change**, and the precondition for Plan B: a `PoolId`-typed write side would
otherwise re-cement the wrong `storage → build` dependency direction unless `PoolId` lives in a low
layer first. This plan fixes dependency direction, unifies the two id NewTypes into one, deletes the
vestigial `Global` variant, and fences the layering with a cheap grep-guard.

## Design (signature altitude)

- **Correct dependency direction** = `core → domain → storage → build → etl → apps`. Today
  `domain/registry` + `etl/silver` import `build.normalize` and `storage/sqlite_repo` imports
  `build.seed` (under `TYPE_CHECKING`) — backwards. Fix by pushing the shared *leaves* DOWN, not by
  moving consumers up.
- **One id type.** `FacilityId` and `PoolId` are the same concept; collapse to a single
  `PoolId = NewType("PoolId", str)` in `domain/models`. Blast radius is wide (18 files: 9 `src/`, 9
  `tests/`) — a mechanical erase-and-repoint, not a local change. The minter grep-guard (only
  `build/reconcile` + `build/seed` may construct a `PoolId` from an external ref) must stay coherent;
  trusted *reconstruction* from persisted rows / validated DTOs routes through a tiny
  `reconstruct_pool_id(str) -> PoolId` boundary shim placed in `domain` (beside the relocated
  `PoolId`). Because the shim's body constructs a `PoolId`, **the grep-guard is explicitly updated** to
  add the shim's home to its `ALLOWED` set (option (a)); the guard is NOT left untouched. The three
  reconstruction call-sites are `storage/codec.py` (~124), `providers/curated.py` (~106 and ~133), and
  `domain/query.py` (~408) — all routed through the shim (query.py's site was missed in the first draft).
- **Enforced layering.** Target order `core → domain → storage → build → etl → apps`. Note `etl` is
  **above** `build`, so `etl → build` is a legitimate downward edge and MUST be allowed (`etl/scrape.py`
  and `etl/build.py` import from `build` and are not touched here). The wrong edges Plan A removes are
  `domain/** → build` and `storage/** → build`. A lightweight import-direction grep-guard (matching the
  `from swimzh.build` / `import swimzh.build` tokens, mirroring the existing "no `data/` reads at
  runtime" guard) forbids exactly those two — no AST DAG walker.

## Out of scope

- Retiring the `facility` table / the `PoolId`-typed `write_schedules` seam (Plan B).
- Deleting the legacy geo pipeline (Plan C).
- The `build`→`assemble` package rename and any full AST layer-graph tool (rejected as
  over-engineering).

## Slices

- **A1 — `normalize` → `core`.** *(S)* Move `build/normalize.py` → `core/normalize.py` (a zero-import
  leaf); repoint the four `src/` importers (`domain/registry`, `etl/silver`, `build/reconcile`,
  `build/seed`) AND the test importer (`tests/build_stage/test_normalize.py`); delete
  `build/normalize.py`.
  **Acceptance:** no module under `domain/**` or `etl/**` imports `swimzh.build.normalize`; QA green;
  behavior identical (normalize output byte-for-byte unchanged, asserted).
  **Depends on:** —

- **A2 — `BASIN_KIND_WORDS` → `domain`.** *(S)* Move the basin-kind word map beside `BasinKind` in
  `domain`; repoint `build/reconcile` + `etl/silver`.
  **Acceptance:** the map has one home in `domain`; both consumers import it from there; QA green.
  **Depends on:** —

- **A3 — Unify `FacilityId` → one `PoolId`.** *(M–L — 18 files)* Introduce/relocate the single
  `PoolId = NewType(...)` in `domain/models`; make `FacilityId = PoolId` a one-step alias, then erase
  `FacilityId` everywhere (9 `src/` files incl. `domain/query.py`, `domain/registry.py`,
  `etl/silver.py`, `storage/sqlite_repo.py`, `build/seed.py`, `build/compose.py`; 9 `tests/` files that
  import it from `domain.models`). Delete the `FacilityId(str(pool_id))` round-trip at
  `build/compose.py` (~118). Add the `reconstruct_pool_id` shim in `domain` and route the four trusted
  reconstruction sites through it: `storage/codec.py` (~124), `providers/curated.py` (~106, ~133), and
  `domain/query.py` (~408). Update the minter grep-guard to add the shim's home to `ALLOWED`.
  Field/param names keep their `facility_*` spelling (`PoolIdentity.facility_id`,
  `Registry.resolve_name() -> PoolId`) — renames are **out of scope** (state it, so the type/name
  mismatch isn't flagged in review).
  **Acceptance:** `grep -rn '\bFacilityId\b' src/ tests/` returns nothing; exactly one id NewType
  remains; the minter grep-guard passes (external-ref construction only in `build/reconcile` +
  `build/seed`; reconstruction only via the `ALLOWED` shim); mypy strict green; QA green.
  **Depends on:** —

- **A4 — Spine row DTOs → `storage`.** *(M)* Move `PoolSpine`/`PoolRow`/`PoolAliasRow`/`PoolXrefRow`
  from `build/seed` → `storage/rows.py`, typed on `domain.PoolId`; delete the
  `if TYPE_CHECKING: from swimzh.build.seed import PoolSpine` reverse edge at `sqlite_repo.py:29`.
  **Acceptance:** `storage/**` imports nothing from `swimzh.build`; `build/seed` imports the row DTOs
  from `storage`; QA green.
  **Depends on:** A3

- **A5 — Delete `Global` + fence the layering.** *(S)* Delete the `Global` `SourceRef` variant end to
  end (its `resolve()`/`_ref_label()` match arms in `build/reconcile.py`, its test in
  `tests/build_stage/test_reconcile.py`, the doc bullet); repoint any `tests/build_stage/*` imports of
  moved symbols (`PoolId`, `SourceRef`, `BASIN_KIND_WORDS`); add the import-direction grep-guard test.
  **Acceptance:** `Global` appears nowhere in `src/`; `assert_never` exhaustiveness still holds over the
  narrowed `Xref | Name | BasinHint` union; the new grep-guard fails if `domain/**` or `storage/**`
  imports `swimzh.build` (matched on `from swimzh.build` / `import swimzh.build` tokens), and **allows**
  `etl/** → swimzh.build` (a legitimate downward edge); QA green.
  **Depends on:** A1, A2, A4

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| 2026-07-20 | A1 | done | none — byte-identical git-tracked rename + 5 import repoints (4 src + 1 test) | concept docs (`data-layer-architecture`, `techdebt-remediation-roadmap`) still name `build/normalize.py` as the cleaning home — cosmetic doc-sync for a later pass | no |
| 2026-07-20 | A2 | done | none — `BASIN_KIND_WORDS` moved to `domain/models.py` (beside `BasinKind`); byte-identical map; bonus — `etl/silver.py` now imports nothing from `swimzh.build` (helps A5) | none | no |
| 2026-07-20 | A3 | done | repointed 3 `tests/build_stage/*` `PoolId` imports to `domain.models` (plan listed them under A5) — forced by moving `PoolId`'s canonical home + mypy `no_implicit_reexport`; simplified `build/seed.py` to `registry.get(pool_id)` (reuse the local minted id) | a now-no-op round-trip remains at `build/reconcile.py:184` (`PoolId(str(...))` on an already-`PoolId`; harmless, sits in an allowed minter — trivially collapsible in a later pass) | no |
| 2026-07-20 | A4 | done | repointed `tests/build_stage/test_seed.py` `PoolSpine` import to `storage.rows` (mypy `no_implicit_reexport`) — same forced-repoint pattern as A3 | none | no |
| 2026-07-20 | A5 | done | none in `src/` — `Global` deleted end-to-end (union narrowed to `Xref | Name | BasinHint`, `assert_never` still exhaustive); `tests/test_layering.py` guard added (forbids `domain`/`storage` → `build`, allows `etl` → `build`, docstring-trap-proof, proven falsifiable via a probe). The `Global`/`normalize` **doc** references were left for the orchestrator to reconcile at completion (docs are orchestrator-owned) | the layering guard matches only ABSOLUTE `swimzh.build` imports — a relative `from ..build` would slip past (harmless today: these layers use only absolute imports) | no |

## Decisions & divergences

- **2026-07-20 — Open-question #1 resolved (owner picked A/B/C).** Trusted id *reconstruction* from
  persisted rows / validated DTOs routes through a single `reconstruct_pool_id` boundary shim
  (option (a)) — the guard's allow-set gains exactly ONE entry (the shim's home in `domain`), not the
  three scattered call-sites, so "mint-from-external-ref only in `reconcile`/`seed`" stays legible.
- **2026-07-20 — Review adjustments (pre-implementation).** A draft review found three blockers, now
  folded in: (1) the layering guard must ALLOW `etl → build` (etl sits above build; `etl/scrape.py` +
  `etl/build.py` legitimately import `build`) — it forbids only `domain/**` and `storage/** → build`;
  (2) A3's minter-guard claim was under-analyzed — the shim's body constructs a `PoolId` so the guard
  IS updated (allow the shim's home), and `domain/query.py` (~408) is a fourth reconstruction site;
  (3) A3's blast radius is 18 files, resized to M–L with a `grep FacilityId` acceptance.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/layers-and-canonical-id.md`.
