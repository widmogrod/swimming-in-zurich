---
type: concept
name: gold-store
status: stable
updated: 2026-07-19
links: ["[[2026-07-19-single-source-of-truth-plan]]"]
---

# Gold store

The SQLite database the app reads from — the "gold" tier of the medallion ETL. Built from the
committed curated inputs (`data/pools/*.yaml`, `data/registry.yaml`, `data/calendar/zurich.yaml`,
`data/catalog.json`) plus network enrichment (WFS geo, page scrapers, Belegungsplan PDFs).

It holds three tables — `facility` (facilities as a JSON `doc` column, incl. schedules, prices,
notices, and lane plans), `catalog` (row-per-entry + `doc` JSON), and `calendar` (a single JSON
`singleton` row). It is the **single source of truth the app reads**: the composition root reads
facilities, catalog, and calendar exclusively from these tables and opens nothing under `data/`
at runtime. A missing DB fails fast (`SWIMZH_GOLD_DB` required; the file must exist).

Built by one offline command — `swimzh build --db gold.sqlite` — from the committed curated
inputs (`data/pools/*.yaml`, `data/registry.yaml`, `data/calendar/zurich.yaml`,
`data/catalog.json`), no network. Optional network enrichment (`build-gold` WFS geo,
`scrape-gold` page schedules, `scrape-lanes` Belegungsplan PDFs) layers on top of the same DB.
The committed `data/` files are ETL inputs, not runtime reads. `.sqlite` stays git-ignored
(build-on-demand, no binary in git).

This was the outcome of [[2026-07-19-single-source-of-truth-plan]] — before it, the gold store
was optional and bypassable (the app fell back to curated YAML and always read catalog/calendar
from files), which made it not-self-contained.
