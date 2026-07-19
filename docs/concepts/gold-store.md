---
type: concept
name: gold-store
status: evolving
updated: 2026-07-19
links: ["[[2026-07-19-single-source-of-truth-plan]]"]
---

# Gold store

The SQLite database the app reads from — the "gold" tier of the medallion ETL. Built from the
committed curated inputs (`data/pools/*.yaml`, `data/registry.yaml`, `data/calendar/zurich.yaml`,
`data/catalog.json`) plus network enrichment (WFS geo, page scrapers, Belegungsplan PDFs).

**Today** it holds a single `facility` table (facilities as a JSON `doc` column, incl. schedules,
prices, notices, and lane plans) and is *optional* — the app falls back to reading the curated
YAML directly, and reads the catalog/calendar from files even when a gold DB is present. That
makes it not-self-contained and bypassable (see the audit in
[[2026-07-19-single-source-of-truth-plan]]).

**Target** (this plan): the gold store becomes the *single source of truth the app reads* — it
gains `catalog` and `calendar` tables, is built by one offline `swimzh build` command from the
committed inputs, and the app reads nothing else at runtime. The committed `data/` files are
demoted to ETL inputs. `.sqlite` stays git-ignored (build-on-demand, no binary in git).
