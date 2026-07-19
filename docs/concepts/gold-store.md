---
type: concept
name: gold-store
status: stable
updated: 2026-07-20
links: ["[[2026-07-19-single-source-of-truth-plan]]", "[[2026-07-19-pool-identity-unification]]", "[[data-layer-architecture]]"]
---

# Gold store

The SQLite database the app reads from — the "gold" tier of the medallion ETL. Built from the
committed curated inputs (`data/pools/*.yaml`, `data/registry.yaml`, `data/calendar/zurich.yaml`,
`data/catalog.json`) plus network enrichment (WFS geo, page scrapers, Belegungsplan PDFs).

Tables (after [[2026-07-19-pool-identity-unification]]):
- **`pool`** — the identity spine and roster: all ~57 pools under one canonical id
  (`id = slug(name)`), with a **derived** `curation_status` (`curated` iff ≥1 basin has ≥1 rule).
  This IS the registry. `/pools` reads it.
- **`pool_alias`** (`UNIQUE(norm)`) and **`pool_xref`** (`UNIQUE(namespace, ext_id)`) — every legacy
  short id / external namespace id (WFS feature id, crowdmonitor key) as a **value pointing at**
  `pool.id`. A second id claiming one pool is a write-time `IntegrityError` — the split-brain is
  unrepresentable. STRICT tables, FK `ON DELETE CASCADE`.
- **`facility`** — the curated+scraped schedule payload as a JSON `doc`, keyed by the canonical id
  (schedules, prices, notices, lane plans). `/swim` reads it, joined to `pool` on the canonical id.
  *(Transitional: the composed blob currently also lives on `pool.facility_doc`; collapsing the two
  is future work — see the plan's backlog.)*
- **`calendar`** — the Zürich calendar as a single JSON `singleton` row.

(The former separate `catalog` table was retired — its roster is the `pool` table.) It is the
**single source of truth the app reads**: the composition root reads facilities, roster, and
calendar exclusively from these tables and opens nothing under `data/` at runtime. A missing DB
fails fast (`SWIMZH_GOLD_DB` required; the file must exist).

Built by one offline command — `swimzh build --db gold.sqlite` — from the committed curated
inputs (`data/pools/*.yaml`, `data/registry.yaml`, `data/calendar/zurich.yaml`,
`data/catalog.json`), no network. Optional network enrichment (`build-gold` WFS geo,
`scrape-gold` page schedules, `scrape-lanes` Belegungsplan PDFs) layers on top of the same DB.
The committed `data/` files are ETL inputs, not runtime reads. `.sqlite` stays git-ignored
(build-on-demand, no binary in git).

This was the outcome of [[2026-07-19-single-source-of-truth-plan]] — before it, the gold store
was optional and bypassable (the app fell back to curated YAML and always read catalog/calendar
from files), which made it not-self-contained.
