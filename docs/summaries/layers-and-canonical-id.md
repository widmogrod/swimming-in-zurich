---
type: summary
feature: layers-and-canonical-id
status: done
created: 2026-07-20
links: ["[[techdebt-remediation-roadmap]]", "[[data-layer-architecture]]", "[[retire-facility-table]]", "[[2026-07-19-pool-identity-unification]]"]
---

# Layers + one canonical id — dependencies point down, one PoolId, layering fenced

**What & why.** Plan A of the [[techdebt-remediation-roadmap]]: the lowest-risk, zero-behavior-change
cut that also unblocks Plan B. pool-identity-unification left two backwards dependencies
(`domain`/`etl` importing `build.normalize`; `storage` importing `build.seed` under `TYPE_CHECKING`)
and two id NewTypes (`FacilityId`, `PoolId`) for one concept. Plan A fixes direction, unifies the id,
deletes the vestigial `Global` variant, and fences the layering with a grep-guard.

## What exists now

- **Leaves pushed down:** `core/normalize.py` (A1) and `BASIN_KIND_WORDS` in `domain/models.py` (A2).
- **One id:** `PoolId = NewType("PoolId", str)` in `domain/models`; `FacilityId` erased across 18 files
  (A3). Trusted reconstruction routes through `domain.reconstruct_pool_id` (4 sites); minting from an
  external ref stays only in `build/reconcile` + `build/seed`, enforced by the (updated, falsifiable)
  minter grep-guard. Field/param names keep `facility_*` — type-only change.
- **Spine row DTOs in `storage/rows.py`** (A4) — `storage` imports nothing from `build`.
- **`Global` gone**, `SourceRef = Xref | Name | BasinHint` (A5); `assert_never` over the narrowed union
  is the exhaustiveness proof.
- **Layering enforced:** `tests/test_layering.py` fails if `domain`/`storage` import `swimzh.build`;
  allows `etl → build` (etl is above build). Anchored token match (docstring-trap-proof), proven
  falsifiable.

## Target layering (now guarded)

```
core → domain → storage → build → etl → apps
```
`domain`/`storage` point only downward; `build → storage`, `etl → build` are legitimate downward edges.

## Backlog (carried)

1. No-op `PoolId(str(...))` round-trip in `build/reconcile` (allowed minter; trivially collapsible).
2. The layering guard catches only absolute `swimzh.build` imports; could harden for relative imports
   and extend to `apps`/`core`.

Enables [[retire-facility-table]] (Plan B): a `PoolId`-typed `write_schedules` no longer re-cements
`storage → build`. See [[techdebt-remediation-roadmap]] for the full sequence and
[[2026-07-20-layers-and-canonical-id-plan]] for the ledger.
