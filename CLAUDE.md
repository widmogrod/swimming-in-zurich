# swimzh — agent guide

Typed data core answering "where can I go swimming in Zürich indoor pools?" filtered by
gender, age, location, and a date (now or future). See
[`docs/2026-07-18-initial-expectations.md`](docs/2026-07-18-initial-expectations.md) for
intent and design decisions, and `README.md` for orientation.

## Layout

- `src/swimzh/core/` — `provider/core`: `Ok`/`Err`/`Result`, the closed `ProviderError`
  union (errors are values, matched exhaustively), and the httpx wrapper.
- `src/swimzh/domain/` — pure domain: schedule **resolver** (the correctness core),
  eligibility, registry, query surface. No I/O.
- `src/swimzh/boundary/` — pydantic v2 DTOs (ingest boundary).
- `src/swimzh/providers/` — adapters returning `Result[..., ProviderError]` (`curated`,
  `geo_sport`; occupancy later).
- `src/swimzh/build/` + `src/swimzh/etl/` + `src/swimzh/storage/` — the single offline builder
  (`build_store`: seed → identity spine → curated blob) writes the SQLite gold store (pure
  functions); `find_swim_options` reads from `GoldRepository`.
- `apps/web/` — FastAPI service + minimal HTML UI over the gold DB (see below).
- `data/` — **ETL inputs** (the curated source of truth): pools/registry/calendar YAML +
  `catalog.json`, built into the gold DB by `swimzh build`; never read at app runtime. Plus
  `sources.md` legal register.
- `tests/` — mirrors `src/swimzh/`; `apps/web/tests/` mirrors the service.

## Web UI / API

`GET /swim?at=<ISO datetime>&gender=female|male|diverse&age=<int>&lat=&lon=&radius_km=&eligible_only=true`
returns eligibility-annotated options + statuses + warnings. Follows the
`python-dev:fastapi-service` conventions; deviations recorded in
`docs/concepts/fastapi-service-integration.md`.

Endpoints: `/swim` (query), `/pools` (list all ~57 pools from the catalog, `?kind=` filter),
`/access-types` (explanations), `/health`, `/` (UI: find tab + all-pools browser).

### Single source of truth: build a gold DB, then run against it

The app reads **only** one SQLite gold store — every endpoint (`/swim`, `/pools`,
`/access-types`) serves from it. No `apps/web/**` module reads `data/*.yaml` or
`data/catalog.json` at request/startup time (grep-asserted by a test). `SWIMZH_GOLD_DB` is
**required**: if the DB is missing or empty, startup **fails fast** with `run \`swimzh build …\``.

```sh
# 1. Build a complete, self-contained gold DB from committed inputs — OFFLINE, no network.
uv run python -m swimzh.cli build --db gold.sqlite

# 2. (optional) Enrich the same store with real scraped data (network):
uv run python -m swimzh.cli scrape-gold   --db gold.sqlite   # REAL schedules scraped per pool
uv run python -m swimzh.cli scrape-lanes  --db gold.sqlite   # per-basin Belegungsplan lane plans

# 3. Run the app against the DB (UI at /, API at /swim). Missing/empty DB -> clean
#    one-line fail-fast (no ASGI traceback). SWIMZH_RELOAD=0 disables auto-reload.
SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main   # http://127.0.0.1:8000
```

`python -m apps.web.main` is the clean dev entrypoint (preflights the store, then serves via
uvicorn). `uvicorn apps.web.main:app` still works and still fails fast without a DB, but reports
through uvicorn's lifespan traceback rather than the one-liner.

`swimzh build` is the **single offline builder**: it assembles the identity spine (the `pool`
table = the ~57-pool roster, plus its `pool_alias`/`pool_xref` crosswalk) + the `calendar`
singleton into one store from the committed inputs alone (offline, no network). The curated
schedule payload rides as a typed blob on the `pool` row (`facility_doc`); there is **no
`facility` table** and no stored `curation_status` (it is derived at read from that blob). Geo
comes from the committed `catalog.json` (WFS coordinates), stamped onto `facility_doc` at build
time — not a live WFS merge. The network commands (`scrape-gold`, `scrape-lanes`) **layer onto**
an already-built store. The curated data directory is supplied to the CLI/ETL via `--data`
(default `data/`); the **app never reads `data/`** — only the gold DB.

Data sources:
- **ETL inputs (human/curated source of truth, committed in git):** `data/pools/*.yaml`,
  `data/registry.yaml`, `data/calendar/*.yaml`, and `data/catalog.json`. These are consumed by
  `swimzh build`/the ETL only — never read at app runtime. Regenerate the catalog from the WFS
  with `uv run python -m swimzh.cli build-catalog --out data/catalog.json`.
- **Single runtime source:** the gold `.sqlite` the app reads (git-ignored; build it, don't
  commit it). `/swim` schedules, `/pools` catalog, and the calendar all come from this one store.

The WFS has locations but not opening hours (`n.a.`). `scrape-gold` parses the timetable
JSON embedded in stadt-zuerich.ch pool pages (`providers/schedule_scraper.py`) — brittle,
best-effort (unparseable pages are skipped and reported), pinned by a saved-page fixture test.

`scrape-lanes` attaches per-basin Belegungsplan lane plans. The lane document is a **first-class
domain attribute** — `Basin.lane_plan_source` (url + optional `section`), authored in
`data/pools/*.yaml` on the owning basin (rides `facility_doc`, no gold DDL). The ETL is **driven
by the domain**: the fetch-set is a projection of the declared sources (no hardcoded URL list), and
reconciliation is a **deterministic URL-keyed join** in `etl/silver.py` (`ParsedPlan.basin_hint` is
not an identity key — a single-basin sheet binds by URL alone; a stacked multi-basin sheet routes
each section by its declared `section` token, failing safe to an audited `UnboundPlan` on any
zero/ambiguous match). **Extraction outcomes are first-class persisted state:**
`Basin.lane_plan: LanePlan | LanePlanUnavailable | None` — a parsed grid, a typed
`LanePlanUnavailable(cause: ProviderError)` for a declared source whose fetch/parse failed (scoped
to that basin — the facility still builds), or `None`. The command prints an honest audit to
stderr (`unbound` URLs/headers, per-basin `unavailable` causes, `unmatched section` alarms). See
`docs/concepts/lane-plan-url-binding.md`.

## Engineering conventions

This project follows the agentic-engineering conventions. When implementing code here,
consult these skills first:
- `python-dev:fastapi-service` — for anything under `apps/web/` (composition root, ports as
  Protocols, thin routers, env only in `config.py`).

Plans live in `docs/plan/`, durable decisions in `docs/concepts/` and `docs/entities/`.

## QA chain (run in this exact order)

Order is load-bearing: **CRAP reads the `coverage.json` that pytest writes, so pytest MUST
run before crap** — otherwise the CRAP scores are stale.

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest                 # writes coverage.json; enforces coverage fail_under
uv run python scripts/crap.py # complexity²·(1−coverage)³ + complexity gate
```

### TypeScript UI chain (SEPARATE from the Python chain — its own CI job `ts-qa`)

The `apps/web/` UI is authored in TypeScript and **compiled** by `tsc` to git-ignored
`apps/web/static/dist/` (served at `/static/dist/…`; see [[typescript-build-pipeline]]). Its QA
chain runs from `apps/web/static/js/` and is **not** bridged into `uv run pytest` — the Python
chain keeps only the `node --test` bridge for still-`.js` modules (scoped to `**/*.test.js` since
Node 26's default discovery also matches `.test.ts`). Run in this order (crap LAST — it reads the
coverage `vitest` writes, mirroring pytest→crap):

```sh
npm --prefix apps/web/static/js run qa   # fmt:check → lint → type-check → test → crap
# or individually: npm run build | type-check | lint | fmt:check | test | crap
```

**Dev loop (IMPORTANT — the app serves compiled `dist/`, not source):** `uvicorn apps.web.main:app`
imports `app` via `create_app()` and **does NOT build** — only `python -m apps.web.main`'s `main()`
runs the `npm run build` preflight (once, at startup). And `--reload` watches `.py`, not `.ts`/`.js`.
So a UI edit is invisible until `dist/` is rebuilt. Use either:

```sh
# A) documented entrypoint — builds once, then serves (reload on unless SWIMZH_RELOAD=0)
SWIMZH_GOLD_DB=gold.sqlite SWIMZH_DEV_UI=1 uv run python -m apps.web.main
# B) live TS recompile in one terminal + your server in another
npm --prefix apps/web/static/js run watch   # tsc --watch: rebuilds dist/ on every save
SWIMZH_GOLD_DB=gold.sqlite SWIMZH_DEV_UI=1 uv run uvicorn apps.web.main:app --reload
```

`SWIMZH_DEV_UI=1` sets `cache-control: no-store` on `/static`, so the browser picks up a rebuilt
module on refresh instead of serving a cached one. `apps/web/static/dist/` is git-ignored — a fresh
checkout has no `dist/` until the first build (blank SPA / 404 on `/static/dist/app.js` otherwise).

- `type-check` (`tsc -p tsconfig.dev.json --noEmit`) and `lint` (eslint) both cover **tests** at
  full strictness. During the migration they are scoped to `**/*.ts`; legacy `.js` is ignored and
  joins as each module converts.
- **`scripts/crap_ts.mjs`** is the TS CRAP gate — the SAME formula as `scripts/crap.py`
  (`cc²·(1−cov)³ + cc`, offender when `cc > min-complexity` AND `crap > threshold`; `[tool.crap-ts]`
  in `pyproject.toml`). Parity is **formula** parity, not metric parity (eslint's cyclomatic count ≠
  radon's), so `[tool.crap-ts]` is its own ratchet. cc from eslint's `complexity` rule; per-function
  coverage from vitest's Istanbul `coverage-final.json` (`coverage.all: true` lists every source
  `.ts`; crap_ts scores a never-executed file — whose v8 `fnMap` is only `(empty-report)` — via a
  whole-file coverage fallback at 0%, so an untested high-complexity module can't hide).

- **Type checker**: `mypy .` (strict) is the canonical, enforced gate and is **green**.
  `pyright` (strict) is also configured but has **known, deferred debt** — remaining
  `reportPrivateUsage` findings in `tests/.../test_belegungsplan.py` and `storage/catalog_json.py`
  (tests/codecs that read domain private attrs). Do **not** assume pyright is clean; the QA gate is
  mypy. (The `storage/calendar_codec.py` findings were cleared by adding public read accessors to
  `ZurichCalendar`; the same treatment for the remaining files is a tracked backlog item.)
- **Coverage floor**: `fail_under` in `[tool.coverage.report]` is a no-regression ratchet
  (currently 95, calibrated to real coverage of 95.61% after Plan C deleted the legacy geo
  pipeline + `facility` table). Raise it as coverage grows; never lower it without a reason.
- **CRAP gate**: fails a function only when `cc > min-complexity (5)` AND `crap > threshold
  (30)`. Fix by adding tests or reducing complexity — do **not** raise the threshold to pass.

## Conventions

- Errors are typed values, never exceptions across provider boundaries; consumers `match`
  the `ProviderError` union and end with `assert_never` (strict-checked exhaustiveness).
- New provider error causes go inside the closed union (or `ProviderSpecific`), and must be
  classified in `retriable()` and `describe()` — the compiler will insist.
- Adapter tests: cassettes (`vcrpy`/`pytest-recording`, `block_network`) for recorded HTTP;
  `httpx.MockTransport` for timeouts/connection errors (no recorded interaction exists).
- All datetimes are tz-aware `Europe/Zurich`.
