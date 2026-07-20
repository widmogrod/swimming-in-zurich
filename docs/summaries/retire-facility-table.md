---
type: summary
feature: retire-facility-table
status: done
created: 2026-07-20
links: ["[[techdebt-remediation-roadmap]]", "[[gold-store]]", "[[data-layer-architecture]]", "[[layers-and-canonical-id]]", "[[delete-legacy-geo-pipeline]]"]
---

# Retire the facility table — one blob, one write door, status derived

**What & why.** Plan B of the [[techdebt-remediation-roadmap]]: pool-identity-unification left the
composed schedule blob duplicated (`pool.facility_doc` + the `facility` table's `doc`), the app
reading the `facility` table, and `scrape-gold` leaving `pool.curation_status` stale. Plan B
collapses to one blob behind one `PoolId`-typed write door, reads only `pool.facility_doc`, and
derives `curation_status` so it can't desync. Retires debt #1, #4, #6a-blob, #7.

## What exists now (verified live: build → scrape-gold → scrape-lanes → serve)

- **`write_schedules(conn, keyed)`** — the single writer of `pool.facility_doc`, typed on `PoolId`
  (an unreconciled write is unrepresentable). `write_pools` writes identity/roster only.
- **One read path** — `GoldRepository`/`GoldSwimStore` read `pool.facility_doc WHERE NOT NULL`; no
  runtime `FROM facility`.
- **`curation_status` derived at read** from one `is_curated(facility_doc)` rule (NULL blob → uncurated;
  else ≥1 basin with ≥1 rule). Stored column + CHECK dropped.
- **Enrichment on the read path** — `scrape-gold`/`scrape-lanes` write via `write_schedules`; City
  serves curated schedule + lane plan + merged scraped price; scraped-only pools auto-derive `curated`.
- **Authoritative geo** — offline build stamps committed-catalog(WFS) coords into `facility_doc`
  (3 curated pools' `/swim` distance shifted to the more-accurate coords — recorded behavior change).
- **Four falsifiable guards** (B5): no runtime facility read; single `facility_doc` writer; no writable
  `curation_status` column; curation-can't-desync consistency test.

## Still standing (Plan C removes)

The `facility` table physically exists, written by legacy `etl/pipeline.run` (build-gold) AND
`etl/build.build_store` (two `write_facilities` sites), read by no runtime path.
[[delete-legacy-geo-pipeline]] deletes `build-gold`, both writers, and the table.

## Backlog

1. Two `write_facilities` sites + the geo-parity test's `SELECT doc FROM facility` → Plan C.
2. `PoolRow.facility_doc` is now an in-memory carrier only — collapsible.
3. Two B5 line-based guards would miss newline-split SQL (harmless today).

See [[2026-07-20-retire-facility-table-plan]] for the full ledger (B4 took one revision round — the
scrape-gold reroute is now mutation-guarded).
