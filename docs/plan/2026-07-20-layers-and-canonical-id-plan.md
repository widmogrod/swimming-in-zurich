---
type: plan
status: draft            # draft -> approved -> in-progress -> done
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
  `PoolId = NewType("PoolId", str)` in `domain/models`. The minter grep-guard (only `build/reconcile`
  + `build/seed` may construct it from an external ref) is preserved; trusted *reconstruction* from
  persisted rows / validated DTOs (`storage/codec.py`, `providers/curated.py`) routes through a tiny
  `reconstruct_pool_id(str) -> PoolId` boundary shim so the guard stays strictly "mint-from-external-
  ref only" (open-question #1 resolved to option (a)).
- **Enforced layering.** A lightweight import-direction grep-guard test (mirroring the existing
  "no `data/` reads at runtime" guard) — no AST DAG walker.

## Out of scope

- Retiring the `facility` table / the `PoolId`-typed `write_schedules` seam (Plan B).
- Deleting the legacy geo pipeline (Plan C).
- The `build`→`assemble` package rename and any full AST layer-graph tool (rejected as
  over-engineering).

## Slices

- **A1 — `normalize` → `core`.** *(S)* Move `build/normalize.py` → `core/normalize.py` (a zero-import
  leaf); repoint the four importers (`domain/registry`, `etl/silver`, `build/reconcile`, `build/seed`);
  delete `build/normalize.py`.
  **Acceptance:** no module under `domain/**` or `etl/**` imports `swimzh.build.normalize`; QA green;
  behavior identical (normalize output byte-for-byte unchanged, asserted).
  **Depends on:** —

- **A2 — `BASIN_KIND_WORDS` → `domain`.** *(S)* Move the basin-kind word map beside `BasinKind` in
  `domain`; repoint `build/reconcile` + `etl/silver`.
  **Acceptance:** the map has one home in `domain`; both consumers import it from there; QA green.
  **Depends on:** —

- **A3 — Unify `FacilityId` → one `PoolId`.** *(M)* Introduce/relocate the single
  `PoolId = NewType(...)` in `domain/models`; make `FacilityId = PoolId` a one-step alias then remove
  the alias and its uses; delete the `FacilityId(str(pool_id))` round-trip at `build/compose.py:118`;
  add the `reconstruct_pool_id` shim and route the trusted reconstruction sites (`storage/codec.py`,
  `providers/curated.py`) through it.
  **Acceptance:** exactly one id NewType remains; the minter grep-guard still passes (construction from
  external refs only in `build/reconcile` + `build/seed`; reconstruction only via the shim); mypy
  strict green; QA green.
  **Depends on:** —

- **A4 — Spine row DTOs → `storage`.** *(M)* Move `PoolSpine`/`PoolRow`/`PoolAliasRow`/`PoolXrefRow`
  from `build/seed` → `storage/rows.py`, typed on `domain.PoolId`; delete the
  `if TYPE_CHECKING: from swimzh.build.seed import PoolSpine` reverse edge at `sqlite_repo.py:29`.
  **Acceptance:** `storage/**` imports nothing from `swimzh.build`; `build/seed` imports the row DTOs
  from `storage`; QA green.
  **Depends on:** A3

- **A5 — Delete `Global` + fence the layering.** *(S)* Delete the `Global` `SourceRef` variant end to
  end (its `resolve()`/`_ref_label()` match arms, its test, the doc bullet); add the import-direction
  grep-guard test.
  **Acceptance:** `Global` appears nowhere in `src/`; `assert_never` exhaustiveness still holds over the
  narrowed `SourceRef` union; the new grep-guard fails if `domain/**` or `etl/**` imports `swimzh.build`
  or if `storage/**` imports `swimzh.build`; QA green.
  **Depends on:** A1, A2, A4

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

- **2026-07-20 — Open-question #1 resolved (owner picked A/B/C).** Trusted id *reconstruction* from
  persisted rows / validated DTOs routes through a `reconstruct_pool_id` boundary shim (option (a)),
  keeping the minter grep-guard strictly "mint-from-external-ref only" rather than diluting its allow-set.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/layers-and-canonical-id.md`.
