---
type: plan
status: draft            # draft -> approved -> in-progress -> done
created: 2026-07-20
feature: retire-facility-table
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [B3]        # B3 drops the curation_status column + flips read-path semantics — the riskiest step
links: ["[[techdebt-remediation-roadmap]]", "[[data-layer-architecture]]", "[[gold-store]]", "[[layers-and-canonical-id]]", "[[2026-07-19-pool-identity-unification]]"]
---

# Plan B — Retire the `facility` table

## Context

Plan B of the [[techdebt-remediation-roadmap]] and the highest-value cut: pool-identity-unification
left the composed schedule blob in TWO places (`pool.facility_doc` and the `facility` table's `doc`),
with `/swim` still reading `facility` and `scrape-gold` leaving `pool.curation_status` stale. This
collapses to ONE blob copy behind ONE `PoolId`-typed write seam, and makes `curation_status` a
read-time derivation so no writer can desync it. Retires debt #1, #4, #6a-blob, #7.

**Depends on [[layers-and-canonical-id]] (Plan A)** — the `PoolId`-typed write side needs `PoolId` in
a low layer and the spine row DTOs in `storage`, else it re-cements `storage → build`.

## Design (signature altitude)

- **One write door.** `write_schedules(conn, keyed: tuple[tuple[PoolId, Facility], ...])` writes each
  facility blob to `pool.facility_doc`. It is the *only* function that writes that column
  (single-writer guard). Typed on `PoolId` ⇒ an unreconciled write is unrepresentable (retires #7).
- **One read path.** `GoldRepository.load_all/get/count` and `GoldSwimStore` read `pool.facility_doc`
  (`WHERE facility_doc IS NOT NULL`); the `facility` table is deleted.
- **Status derived, never stored.** Drop the stored `pool.curation_status` column; a shared
  `is_curated(facility_doc)` helper derives it at read (blob present AND ≥1 basin with ≥1 rule). The
  status therefore can't disagree with the schedule fact it describes (retires #4 by construction).
- **Geo parity is a prerequisite.** Today full geo reaches the read path only after `build-gold`
  merges WFS coordinates; collapsing the table would drop that unless authoritative catalog/geo_sport
  geo is stamped onto the curated `Facility` *before* serialization. B1 does that first.

## Out of scope

- Full row-normalization of the schedule/price/basin blob into `schedule_rule`/`basin`/`price` rows
  (#6a-rows) — this plan retires the *duplication*, keeping the single blob.
- Deleting the legacy geo pipeline (Plan C) — but B1's offline geo stamp is C's prerequisite.

## Slices

- **B1 — Stamp authoritative geo before serialization.** *(M)* In `build/seed` + `build/compose`,
  stamp catalog(WFS)/geo_sport geo onto the curated `Facility` (`replace(facility, geo=entry.geo or
  facility.geo)`) so `pool.facility_doc` carries the geo the read path needs.
  **Acceptance:** a parity test asserts identical geo for the ~4 curated pools in `pool.facility_doc`
  vs what `build-gold` merges today; QA green. **Load-bearing prerequisite for B2/B4 and Plan C.**
  **Depends on:** Plan A

- **B2 — `write_schedules` seam + flip reads.** *(M)* Add `write_schedules(conn, keyed)` writing
  `pool.facility_doc`; flip `GoldRepository.load_all/get/count` and `GoldSwimStore` to read it.
  **Acceptance:** a parity test asserts `load_all()` off `pool.facility_doc` equals today's `facility`-
  backed `load_all()`; `/swim` and `/pools/{id}` behave identically; QA green.
  **Depends on:** B1

- **B3 — Derive `curation_status` at read; drop the column.** *(M)* Remove the stored
  `pool.curation_status` column; derive via the shared `is_curated` helper at read for `/pools` + the
  roster.
  **Acceptance:** `/pools` reports the same curated/uncurated split as today (4/53); a NULL-blob pool
  derives `uncurated`; build-twice → equal-rows determinism stays green; QA green.
  **[PAUSE for human review — schema change + read-path semantics.]**
  **Depends on:** B2

- **B4 — Route writers through the seam; delete the table.** *(M)* Route `scrape-gold`/`scrape-lanes`
  through `write_schedules`; DELETE the `facility` CREATE TABLE, `storage.write_facilities`,
  `etl/gold.write_gold`, and the dead `load_catalog`.
  **Acceptance:** no runtime SQL references a `facility` table; `scrape-gold`/`scrape-lanes` write only
  `pool.facility_doc`; the full build → scrape-gold → scrape-lanes flow is green end-to-end; QA green.
  **Depends on:** B3

- **B5 — Guards.** *(S)* Add: no-`facility`-table SQL grep-guard (`FROM facility`/`INTO facility`);
  single-writer guard (`write_schedules` the only writer of `pool.facility_doc`); schema guard
  (`_SCHEMA` has no `facility` table and no writable `curation_status` column); a consistency test
  (scrape a schedule onto a previously-uncurated pool → roster/`/pools` report `curated` and `/swim`
  serves it — fails on today's code).
  **Acceptance:** all four guards present and falsifiable; QA green.
  **Depends on:** B4

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

- **2026-07-20 — Open-question #4 resolved (owner picked B).** `curation_status` becomes derive-at-read
  (57 rows parse `facility_doc` — negligible latency); the stored CHECK-constrained column is dropped so
  it can never desync. Determinism (build-twice-equal) + the NULL-blob→`uncurated` case must stay green.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/retire-facility-table.md`.
