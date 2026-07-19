# swimming-in-zurich (`swimzh`)

A typed, offline-tested Python library that answers one question well:

> *Given who I am (gender, age), where I am, and a date/time (now or future) — where can I
> go swimming in a Zürich indoor pool, when, under what access rules, and at what price?*

Existing apps solve *live occupancy*; none answer the **eligibility + schedule + price** question
for a **future date**. That gap is the point of this project.

## Status

Early. Building the **library core + tests first** (no UI yet). See:

- [`docs/2026-07-18-initial-expectations.md`](docs/2026-07-18-initial-expectations.md) — intent, data landscape, decisions.
- The implementation plan (in the owner's Claude plan file).

## Design in one breath

- Errors are **values**, not exceptions: hand-rolled `Ok/Err` with a **closed, standardised
  `ProviderError` union** that consumers match **exhaustively** (`assert_never`, pyright `--strict`).
- The hard core is the **schedule resolver**: recurring rules + Zürich calendar overlays
  (school-term/holiday, public holidays) + closures + one-off exceptions → the schedule for a
  concrete date. This is what makes **future-date** answers correct.
- **Provenance on every answer** (`valid_as_of`, `curated|scraped`); *closed* ≠ *unknown*.
- Medallion `raw → silver → gold` (SQLite) as **pure functions**; Dagster wraps them later.

## Develop

```sh
uv sync --extra dev
make qa          # ruff lint + format-check, mypy strict, pytest+coverage floor, CRAP gate
```

`make qa` runs the chain in the load-bearing order (pytest before CRAP). The enforced type
gate is **mypy strict** (green); `pyright --strict` is also configured but carries known,
deferred debt — see `CLAUDE.md`.

## Run the app

The app reads a **single source of truth**: one SQLite gold store. Build it once from the
committed inputs (offline, no network), then run the web app against it.

```sh
# 1. Build a complete, self-contained gold DB from the committed data/ inputs (offline).
uv run python -m swimzh.cli build --db gold.sqlite

# 2. (optional) enrich it with real / geo-merged schedules (network):
uv run python -m swimzh.cli build-gold   --db gold.sqlite   # curated pools + WFS geo
uv run python -m swimzh.cli scrape-gold  --db gold.sqlite   # real scraped schedules
uv run python -m swimzh.cli scrape-lanes --db gold.sqlite   # per-basin lane plans

# 3. Serve it (UI at /, API at /swim). A missing/empty DB fails fast with a one-line
#    "build it first" message (no traceback); SWIMZH_RELOAD=0 disables auto-reload.
SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main
```

(`uv run uvicorn apps.web.main:app` also works and still refuses to start without a DB —
it just reports via uvicorn's ASGI traceback rather than the clean one-liner.)

The files under `data/` (pools/registry/calendar YAML + `catalog.json`) are **ETL inputs** —
the curated source of truth, built into the gold DB by `swimzh build`. The app never reads
`data/` at runtime; the gold `.sqlite` (git-ignored) is the only runtime source.

### Use cases

| I want to… | Command |
|---|---|
| Try it offline (curated pools only, no network) | `swimzh build --db gold.sqlite` |
| Get real schedules + lane plans (network) | `build` then `scrape-gold` + `scrape-lanes` on the same `--db` |
| Refresh geo / merge WFS locations (network) | `build-gold --db gold.sqlite` |
| Regenerate the pool catalog from the WFS | `build-catalog --out data/catalog.json` (an ETL input; then re-`build`) |
| Serve the UI + API | `SWIMZH_GOLD_DB=gold.sqlite python -m apps.web.main` (clean fail-fast; `SWIMZH_RELOAD=0` to disable reload) |
| Ask "where can I swim now/later?" | `GET /swim?at=<ISO>&gender=female\|male\|diverse&age=<int>&lat=&lon=&radius_km=&eligible_only=true` |
| Browse all ~57 pools | `GET /pools?kind=indoor` · access rules at `/access-types` |

(All CLI commands are `uv run python -m swimzh.cli <cmd>`. Enrichment layers onto an
already-built DB; re-run any step to refresh that layer.)
