---
type: summary
feature: single-source-of-truth
status: done
created: 2026-07-19
links: ["[[gold-store]]", "[[fastapi-service-integration]]", "[[2026-07-19-single-source-of-truth-plan]]"]
---

# Single source of truth — the app reads only the SQLite gold store

**What & why.** An audit found the app had *no* single source of truth: at startup it stitched
facility data from SQLite **or** `data/*.yaml` (by whether `SWIMZH_GOLD_DB` was set), the catalog
always from `data/catalog.json`, and the calendar always from `data/calendar/zurich.yaml` — even
in the "gold-backed" path. So `/swim` gave **different answers by mode** (the curated path had no
scraped notices or lane plans), and the gold DB wasn't self-contained. This feature restored the
original medallion intent: **ETL → one gold SQLite → the app reads only gold.**

## What exists now

- **Self-contained gold DB** — `storage/sqlite_repo.py` holds three tables: `facility` (JSON
  `doc`), `catalog` (row-per-entry + `doc`), `calendar` (single JSON `singleton` row). `open_db`
  creates all three idempotently. Codec: `storage/calendar_codec.py` (boundary `CalendarDTO`).
  Read/write: `write_catalog`/`load_catalog`, `write_calendar`/`load_calendar`.
- **One offline build** — `swimzh build --db gold.sqlite` (`etl/build.py::build_store`) assembles
  a complete DB from committed inputs with **no network**. `build-gold`/`scrape-gold`/`scrape-lanes`
  enrich the same store on top.
- **App reads only the DB** — `SWIMZH_GOLD_DB` required (default `gold.sqlite`), **fail-fast** on a
  missing/empty DB. `CuratedSwimData`, `services/curated_store.py`, `services/catalog_store.py`
  deleted. Catalog + calendar come from the DB's own tables.
- **Enforced invariant** — `apps/web/tests/api/test_single_source_of_truth.py` greps runtime
  `apps/web/**` and fails if any module reads `data/*.yaml` / `catalog.json` / `load_dataset`.

## Run flow

```sh
uv run python -m swimzh.cli build --db gold.sqlite            # offline, from committed data/ inputs
# optional enrichment (network): build-gold | scrape-gold | scrape-lanes  --db gold.sqlite
SWIMZH_GOLD_DB=gold.sqlite uv run uvicorn apps.web.main:app --reload
```

The committed `data/` files (`pools/*.yaml`, `registry.yaml`, `calendar/zurich.yaml`,
`catalog.json`) are the curated **source of truth** but are **ETL inputs**, not runtime reads.
`.sqlite` stays git-ignored (build-on-demand, no binary in git).

## Key decisions

- **Single store, not single table** — catalog (57 pools) and facilities (few, with schedules)
  stay separate tables in one file.
- **Build-on-demand, not a committed binary** — inputs are in git, so the DB is reproducible
  offline; no `.sqlite` in git.

## Backlog (tech debt carried out of this plan)

1. **Pyright** `reportPrivateUsage` (codec reads `ZurichCalendar` privates) — mypy strict is the
   enforced gate and green; fix by adding read accessors + `__eq__` to `ZurichCalendar`.
2. Offline `swimzh build` writes facilities **without geo** (geo comes from `build-gold`/
   `scrape-gold`; the `catalog` table has geo for all pools).
3. `etl/build.py` error branches uncovered; CLAUDE.md coverage-floor note stale (~91 vs ~95%).

See [[2026-07-19-single-source-of-truth-plan]] for the full ledger and dated divergences.
