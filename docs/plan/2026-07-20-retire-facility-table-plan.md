---
type: plan
status: draft            # draft -> approved -> in-progress -> done
created: 2026-07-20
feature: retire-facility-table
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [B3]        # B3 drops the curation_status column + flips read-path semantics — the riskiest step
links: ["[[techdebt-remediation-roadmap]]", "[[data-layer-architecture]]", "[[gold-store]]", "[[layers-and-canonical-id]]", "[[delete-legacy-geo-pipeline]]", "[[2026-07-19-pool-identity-unification]]"]
---

# Plan B — Retire the `facility` table (from the read + enrichment paths)

## Context

Plan B of the [[techdebt-remediation-roadmap]] and the highest-value cut. pool-identity-unification
left the composed schedule blob in TWO places (`pool.facility_doc` and the `facility` table's `doc`),
with `/swim` still reading `facility` and `scrape-gold` leaving `pool.curation_status` stale. This
collapses to ONE blob behind ONE `PoolId`-typed write seam and makes `curation_status` a read-time
derivation so no writer can desync it. Retires debt #1, #4, #6a-blob, #7.

**Scope boundary (revised after review):** the `facility` table is still written by the legacy
`build-gold` pipeline (`pipeline.run → write_gold → write_facilities`), which [[delete-legacy-geo-pipeline]]
(Plan C) deletes. So Plan B retires the table from the **read path and the enrichment/offline-build
write paths** and leaves it write-only-dead; the **physical `DROP TABLE` + deletion of
`write_facilities`/`write_gold`/`etl.gold`** happens in Plan C once `build-gold` is gone. Attempting the
physical delete here would break `build-gold`, the offline build, and 5 test files.

**Depends on [[layers-and-canonical-id]] (Plan A)** — the `PoolId`-typed write side needs `PoolId` in a
low layer and the spine row DTOs in `storage`, else it re-cements `storage → build`.

## Design (signature altitude)

- **One write door for the blob.** `write_schedules(conn, keyed: tuple[tuple[PoolId, Facility], ...])`
  writes each facility blob to `pool.facility_doc` and is the *only* writer of that column. Today the
  seed's `write_pools` also writes `facility_doc` — B2 changes `write_pools` to write identity/roster
  only, so the single-writer guarantee actually holds. Typed on `PoolId` ⇒ an unreconciled write is
  unrepresentable (retires #7).
- **One read path.** `GoldRepository.load_all/get/count` and `GoldSwimStore` read `pool.facility_doc`
  (`WHERE facility_doc IS NOT NULL`); the app reads the `facility` table nowhere.
- **Status derived, never stored.** Drop the stored `pool.curation_status` column; a shared
  `is_curated(facility_doc)` helper derives it at read (blob present AND ≥1 basin with ≥1 rule) — the
  status can't disagree with the schedule fact it describes (retires #4 by construction). Verified the
  derivation reproduces the stored value exactly for all 57 pools (incl. NULL-blob → uncurated and
  blob-without-ruled-basin → uncurated).
- **Geo parity, not geo rescue (reworded).** All 4 curated pools already carry geo in their YAML, so
  the offline read path is not geo-less. But `build-gold` overwrites curated geo with WFS coords, and
  that overwrite never reaches `pool.facility_doc` today. B1 stamps the authoritative **committed
  catalog** (`catalog.json`, = WFS) geo onto the curated `Facility` before serialization, so
  `pool.facility_doc` carries the same coords an enriched deployment served — a parity fix (a ~50–500 m
  coordinate *shift* for 3 of 4 pools), a recorded behavior change, not a distance outage.

## Out of scope

- Full row-normalization of the schedule/price/basin blob into rows (#6a-rows) — keep the single blob.
- The physical `facility` `DROP TABLE` + `write_facilities`/`write_gold`/`etl.gold` deletion → Plan C.
- Deleting the legacy geo pipeline (Plan C) — but B1's offline geo stamp is C's prerequisite.

## Slices

- **B1 — Stamp authoritative geo before serialization.** *(M)* In `build/seed` + `build/compose`,
  stamp committed-catalog geo onto the curated `Facility` (`replace(facility, geo=entry.geo or
  facility.geo)`) so `pool.facility_doc` carries it.
  **Acceptance:** an OFFLINE parity test asserts the geo in `pool.facility_doc` for the 4 curated pools
  equals the committed `data/catalog.json` geo (compare against the committed catalog, NOT a live
  `build-gold` run); the ~3 curated pools whose YAML coords differ now serve catalog coords (recorded
  as a behavior change); QA green. **Load-bearing prerequisite for B2 and Plan C.**
  **Depends on:** Plan A

- **B2 — `write_schedules` seam; single-writer topology; flip reads.** *(L)* Add `write_schedules(conn,
  keyed)` writing `pool.facility_doc`. Change `write_pools` to write identity/roster columns only (NOT
  `facility_doc`). Route the offline builder (`etl/build.build_store`) to write curated blobs via
  `write_schedules` (stop its `write_facilities` call). Flip `GoldRepository.load_all/get/count` and
  `GoldSwimStore` to read `pool.facility_doc`.
  **Acceptance:** a parity test asserts `load_all()` off `pool.facility_doc` equals today's
  `facility`-backed `load_all()` for an offline build; `/swim` + `/pools/{id}` behave identically;
  `facility_doc` now has exactly one writer (`write_schedules`); QA green.
  **Depends on:** B1

- **B3 — Derive `curation_status` at read; drop the column.** *(M)* Remove the stored
  `pool.curation_status` column; derive via the shared `is_curated` helper at read for `/pools` + the
  roster.
  **Acceptance:** `/pools` reports the same curated/uncurated split as today (4/53); a NULL-blob pool
  derives `uncurated`; a blob-without-ruled-basin derives `uncurated`; build-twice → equal-rows
  determinism stays green; QA green. **[PAUSE for human review — schema change + read-path semantics.]**
  **Depends on:** B2

- **B4 — Route enrichment through the seam; migrate the facility-table tests.** *(M)* Route
  `scrape-gold`/`scrape-lanes` through `write_schedules` (they write `write_gold → facility` today).
  Migrate the tests that exercise the retired read/write surface — `tests/storage/test_sqlite_repo.py`,
  `tests/storage/test_gold_store_catalog_calendar.py`, `apps/web/tests/api/test_app_gold.py`,
  `tests/test_cli.py` (`load_catalog` sites) — to `pool.facility_doc`/`load_roster`. The `facility`
  table now has **only** the `build-gold` (`pipeline.run`) writer left; it stays until Plan C.
  **Acceptance:** `build → scrape-gold → scrape-lanes → serve` shows scraped schedules + lane plans via
  `pool.facility_doc` end-to-end (the B2→B4 enrichment gap is closed); no app/runtime read of the
  `facility` table remains; migrated tests green; QA green.
  **Depends on:** B3

- **B5 — Guards.** *(S)* Add: a **no-runtime-read-of-`facility`** grep-guard (no `FROM facility` in app
  runtime source — the table still exists for `build-gold` until Plan C, so this guards reads, not the
  table's existence); a single-writer guard (`write_schedules` the only writer of `pool.facility_doc`);
  a schema guard (no writable `curation_status` column); a consistency test (scrape a schedule onto a
  previously-uncurated pool → roster/`/pools` report `curated` and `/swim` serves it — fails on today's
  code).
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
  it can never desync. Determinism (build-twice-equal) + NULL-blob→`uncurated` + blob-without-rules→
  `uncurated` must stay green.
- **2026-07-20 — Review adjustments (pre-implementation).** A draft review found three blockers, now
  folded in: (1) the physical `facility` `DROP TABLE` + `write_facilities`/`write_gold`/`etl.gold`
  deletion CANNOT happen in B (the live `build-gold` pipeline still writes them) — moved to Plan C; B
  retires the table from the read + enrichment paths only. (2) The single-writer guard was
  unsatisfiable because the seed's `write_pools` also writes `facility_doc`; B2 now makes `write_pools`
  identity/roster-only so the guarantee holds. (3) The B1 geo claim was overstated ("geo only after
  build-gold / silently degrade distance") — geo is present via curated YAML; B1 is a **parity** fix
  (curated coords → committed-catalog coords), a recorded ~50–500 m shift for 3 of 4 pools, and its
  test compares against the committed `catalog.json` offline, not a live pipeline. B3 (derive-at-read)
  was verified correct against the stored computation — no change.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/retire-facility-table.md`.
