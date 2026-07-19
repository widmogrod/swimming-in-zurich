---
type: plan
status: draft            # draft -> approved -> in-progress -> done
created: 2026-07-19
feature: single-source-of-truth
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial     # critic subagent must find no blocking issues
pause_after: [S1]        # the gold schema change is riskiest — human review before rewiring the app
links: ["[[gold-store]]"]
---

# Plan — Single source of truth: the app reads only the SQLite gold store

## Context

An audit (2026-07-19) found the app has **no single source of truth**: at startup it stitches
three sources — facility data from **SQLite *or* `data/*.yaml`** (chosen by whether
`SWIMZH_GOLD_DB` is set), the pool **catalog always from `data/catalog.json`**, and the
**calendar always from `data/calendar/zurich.yaml`** (read even in the "gold-backed" path). So
the gold DB is not self-contained, and `/swim` gives **different answers by mode**: the default
`CuratedSwimData` path has the curated pools but **no scraped notices and no lane plans** (those
exist only in a built gold store). This is the drift from the original medallion design
("ETL → one gold SQLite → app reads gold").

Goal: the app reads **only** the gold SQLite. The committed `data/` files
(`pools/*.yaml`, `registry.yaml`, `calendar/zurich.yaml`, `catalog.json`) stay in git as the
**human/curated source of truth — but as ETL *inputs*, not runtime reads**. Builds on
[[gold-store]], the existing `storage/sqlite_repo.py`, `etl/*`, and the app's
`apps/web/services/*` adapters.

## Design (signature altitude)

**Gold DB becomes self-contained** — three tables in one store (`storage/sqlite_repo.py`):
- `facility` (exists today; facilities incl. schedules/prices/notices/lane-plans as the `doc` JSON).
- `catalog` (NEW) — one row per `PoolCatalogEntry` (pool_id, name, kind, lat, lon, url, …).
- `calendar` (NEW) — the Zürich calendar (public holidays + school-holiday ranges + known years),
  as a small table or one JSON blob row keyed `singleton`.

**Repository surface** (`GoldRepository` / write side):
- `write_catalog(conn, entries)` / `load_catalog(conn) -> tuple[PoolCatalogEntry, ...]`.
- `write_calendar(conn, calendar)` / `load_calendar(conn) -> ZurichCalendar`.
- (existing `write_facilities` / `load_all` / `get` unchanged.)

**One offline build** (`etl` + CLI): `swimzh build --db gold.sqlite` assembles a **complete,
self-contained** gold DB from the committed inputs, **no network required** — curated facilities
(`load_dataset(data/)`), the committed `data/catalog.json`, and `data/calendar/zurich.yaml` →
`facility` + `catalog` + `calendar` tables. The network commands (`scrape-gold`, `scrape-lanes`,
and geo enrichment) **layer onto** an already-built store, unchanged.

**App reads only the DB** (`apps/web`):
- `config`: `SWIMZH_GOLD_DB` is **required** (default path e.g. `gold.sqlite`); startup **fails
  fast** with "run `swimzh build`" if it is missing/empty.
- `GoldSwimData.open(gold_db)` — calendar now from `load_calendar(conn)`, **no `data_dir`
  read**; facilities from `load_all`.
- `load_catalog` reads the `catalog` **table**, not `data/catalog.json`.
- **Delete** the `CuratedSwimData` runtime adapter and the `_load_swim_data` curated fallback —
  curated YAML is now consumed only by `swimzh build`.

**Invariant:** after this change, no module under `apps/web/` reads `data/*.yaml` or
`data/*.json` at request/startup time — grep-assertable. The committed `data/` files are ETL
inputs; the gold DB is the single runtime source of truth.

## Out of scope

- Committing a prebuilt binary `gold.sqlite` to git (rejected — build-on-demand from committed
  inputs instead; `.sqlite` stays git-ignored).
- Merging `catalog` and `facility` into one table / one "pool universe" — they stay two tables in
  the one store (57 known pools vs the few with schedules); "single source" means single *store*,
  not single table.
- Changing the medallion raw/silver layers, the scrapers, or the lane-reservation model.
- The concurrent `ux-usability-pass` work (different feature; keep working trees separate).

## Slices

### S1 — Gold DB holds catalog + calendar (riskiest; pause after)

- **Goal**: the gold store persists facilities **and** the catalog **and** the calendar; prove by
  round-tripping all three through one DB.
- **Touches**: `storage/sqlite_repo.py` (add `catalog` + `calendar` tables; `write_catalog`/
  `load_catalog`/`write_calendar`/`load_calendar`); a small calendar codec (reuse the
  `boundary`/`catalog_json` patterns; `Decimal`/`date` already round-trip). No app change yet.
- **Acceptance**: a test writes facilities + catalog (from `data/catalog.json`) + calendar (from
  `data/calendar/zurich.yaml`) into one `:memory:` DB and reads all three back equal; schema
  additions are backward-compatible (`CREATE TABLE IF NOT EXISTS`).
- **Depends on**: —

### S2 — `swimzh build` produces a complete offline gold DB

- **Goal**: one command builds a self-contained gold DB from committed inputs, no network.
- **Touches**: `etl/` (a `build_store(data_dir, db) ` assembling facility+catalog+calendar) + a
  `build` CLI subcommand; `etl/pipeline.py`/`build-gold` reused for facilities.
- **Acceptance**: `swimzh build --db tmp.sqlite` (offline, MockTransport/none) yields a DB whose
  `load_catalog`==57 entries, `load_calendar` covers 2026, and `load_all` has the curated
  facilities; `scrape-gold`/`scrape-lanes` still enrich it afterward (existing tests green).
- **Depends on**: S1.

### S3 — App reads only the gold DB; delete the YAML/JSON runtime fallbacks

- **Goal**: every app data read comes from the gold DB; the curated-YAML runtime path is gone.
- **Touches**: `apps/web/config.py` (require `SWIMZH_GOLD_DB` + fail-fast), `main.py`
  (`_load_swim_data` → gold only), `services/gold_store.py` (calendar from DB), remove
  `services/curated_store.py` + `services/catalog_store.py` (read table instead); update the
  app tests to build a gold DB fixture.
- **Acceptance**: a grep-assertable test proves no `apps/web/**` module opens `data/*.yaml`/
  `catalog.json` at runtime; `/swim`, `/pools`, `/access-types` all serve from one DB fixture;
  missing DB → clear fail-fast error. `/swim` and `/pools` read the same store.
- **Depends on**: S2.

### S4 — Docs + run flow

- **Goal**: the run story is "build once, then run against the DB".
- **Touches**: `CLAUDE.md`, `README.md`, `data/sources.md` (mark files as ETL inputs), the app run
  instructions (`swimzh build` → `SWIMZH_GOLD_DB=gold.sqlite uvicorn …`).
- **Acceptance**: docs describe the single-source-of-truth flow; `make qa` green.
- **Depends on**: S3.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

- **Build-on-demand, not a committed binary.** The inputs (`catalog.json`, `calendar.yaml`,
  `pools/*.yaml`) are already committed, so `swimzh build` can produce a complete gold DB
  **offline** — no network, no binary artifact in git. The app requires the DB to exist (fail
  fast); scrapers/geo are enrichment on top.
- **Single store, not single table.** Catalog (all pools) and facilities (few, with schedules)
  stay separate tables; "single source of truth" = one SQLite file the app reads.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/single-source-of-truth.md` (what EXISTS now, not what was intended).
