# swimzh — agent guide

Typed data core answering "where can I go swimming in Zürich?" — **all** pools, indoor
(Hallenbäder) *and* outdoor (Freibäder/Seebäder), and possibly other cities in the future —
filtered by gender, age, location, and a date (now or future). (Much of the curated data and
scraping today is indoor-first, but that is a coverage gap, not a scope boundary.) See
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
- `src/swimzh/build/` + `src/swimzh/etl/` + `src/swimzh/storage/` — the atomic pipeline builder
  (`build`: WFS roster → identity spine → schedule/price/lane scrape → `compose`) writes the SQLite
  gold store; `find_swim_options` reads from `GoldRepository`.
- `apps/web/` — FastAPI service + minimal HTML UI over the gold DB (see below).
- `data/` — **ETL inputs**: `registry.yaml` (crosswalk: aliases, Baditicker/crowdmonitor keys, kind
  overrides), `calendar/*.yaml` (term dates), and `pools/*.yaml` — now a **thin crosswalk**
  (`facility_id` + basins carrying only `lane_plan_source`), **not** a source of truth. `catalog.json`
  is a WFS snapshot. Consumed by `swimzh build` only; never read at app runtime. Plus `sources.md`
  legal register.
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
# 1. Build a COMPLETE gold DB in ONE atomic pipeline — NETWORK-DEPENDENT (WFS + scrapers).
#    Runs the whole provider chain (roster → discover → schedule/price scrape → lanes → compose)
#    inside a temp-DB + swap: any provider failure aborts non-zero, prior gold content-unchanged.
uv run python -m swimzh.cli build --db gold.sqlite

# 2. (optional) Thin RE-LAYER commands — refresh one cadence onto an already-built store:
uv run python -m swimzh.cli scrape-gold   --db gold.sqlite   # re-run the schedule/price phase
uv run python -m swimzh.cli scrape-lanes  --db gold.sqlite   # re-run the Belegungsplan lane phase

# 2b. Every network command caches responses to disk per-tier (see below). Force a refetch:
uv run python -m swimzh.cli build --db gold.sqlite --refresh    # == SWIMZH_CACHE=refresh
SWIMZH_CACHE=off uv run python -m swimzh.cli build --db gold.sqlite   # bypass the cache entirely

# 3. Run the app against the DB (UI at /, API at /swim). Missing/empty DB -> clean
#    one-line fail-fast (no ASGI traceback). SWIMZH_RELOAD=0 disables auto-reload.
SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main   # http://127.0.0.1:8000
```

`python -m apps.web.main` is the clean dev entrypoint (preflights the store, then serves via
uvicorn). `uvicorn apps.web.main:app` still works and still fails fast without a DB, but reports
through uvicorn's lifespan traceback rather than the one-liner.

`swimzh build` is **one atomic pipeline command** (`cli.build`): WFS roster (`fetch_roster`) →
identity spine + thin crosswalk (`build_store`, the `pool` table = ~57-pool roster + its
`pool_alias`/`pool_xref` crosswalk + the `calendar` singleton) → schedule + price scrape and
reconcile (`_compose_schedules`) → lane discovery/fetch/attach (`_attach_lanes`) → `compose`. The
whole chain runs inside **one** temp-DB + `os.replace` swap (`storage/atomic.py`): the store commits
only if every phase completed, so a mid-chain provider failure aborts non-zero and leaves the prior
gold **content-unchanged** — never a partial store. It is therefore **network-dependent** (the WFS
roster + the page scrapers). `scrape-gold` / `scrape-lanes` are **thin re-layer commands** driving
the same extracted phase functions (per-cadence refresh onto an already-built store). The facility
payload rides as a typed blob on the `pool` row (`facility_doc`); there is **no `facility` table**.
The `--data` dir (default `data/`) supplies only the thin crosswalk; the **app never reads `data/`**.

**Provider HTTP disk cache — a dev/build accelerator, never a source of truth.** The build is
network-bound (a cold run is minutes), so every provider response is cached to
`.cache/swimzh/<tier>/<host>/<key16>.json` — **git-ignored**, one human-readable JSON file per entry
(`cat`/`jq` it to see exactly what a site returned; only the Belegungsplan PDFs are base64, text
content-types stay inline). A warm build makes **zero** network calls. The seam is an httpx
**transport** (`core/httpcache.py`: `CacheStore` + `DiskCacheTransport`), so `HttpClient` and all five
providers are untouched — providers know nothing about the cache (grep-asserted by a test).

TTL is **our** policy, keyed off each provider's volatility (`core/cache_tiers.py`, the whole table in
one place): `geo_sport` 14d, `page_provider` 7d, `price_scraper` 7d, `belegungsplan` 3d,
`schedule_scraper` 12h, `baditicker` 2m. `HttpClient.get` stamps the tier + TTL onto
`request.extensions` from its `source=`, which is why **`cli.py` builds one `HttpClient` per source**
over one shared transport and threads the source-matched client into each *provider call* — a phase is
not source-atomic (`_compose_schedules` fans out to price *and* schedule; `_attach_lanes` to discovery
*and* lanes), so both take two clients. A single shared client would silently collapse every request
to one tier; a build-level test guards all five `(source, tier, ttl)` triples.

Escape hatches: `--refresh` / `SWIMZH_CACHE=refresh` forces a refetch, `SWIMZH_CACHE=off` is
behaviourally today's no-cache path, and clearing is `rm -rf .cache/swimzh[/<tier>]`. The **web
runtime wires the cache OFF** (Baditicker has its own in-process 2-min TTL). The cache is *not* the
gold DB (still the only runtime source of truth) and *not* the test-fixture store (the `vcrpy`
cassettes stay the checked-in contract). Caveat: passing an explicit transport disables httpx's env
proxy mounts, so `HTTP(S)_PROXY` is no longer honoured. See
[[2026-07-31-provider-http-disk-cache-plan]].

**Curation model — three-state `ScheduleFreshness`, not a boolean.** A pool's schedule state is
derived at read from its `facility_doc` blob (`storage/codec.schedule_freshness`, replacing the old
`is_curated` boolean): **`scraped`** (≥1 basin carries a rule), **`awaiting_scrape`** (scrapeable —
a WFS-`indoor` stadt-zuerich pool, incl. a `thermal` display-override like Käferberg — but no
schedule yet), **`no_source`** (not scrapeable, e.g. `schulschwimmanlage-hardau` — one of the 14
Schulschwimmanlagen with no page of their own — or an outdoor/lake pool). A schedule-less pool is a
first-class honest state on `/pools` (`freshness`), `/swim` (status), and the UI's three ghost
states — **never rendered as "closed"**.

**Which pools get scraped: `etl/scrape.declared_sources`** — a conjunction of `kind ∈ {indoor,
thermal, school}`, having a URL, and **no other roster entry sharing that URL**. The last test is
what makes school pools safe to admit: 14 entries (13 *"ohne öffentliches Schwimmen"* plus
`schulschwimmanlage-borrweg`) all point at the generic `hallenbaeder.html`, and under fail-fast
scraping that one unparseable overview would abort every build 14 times over. The predicate selects
**11** pools (7 indoor/thermal + 4 school), pinned offline against `data/catalog.json`. Note
`domain/catalog.freshness_of` deliberately does **not** include `school` in its kind test — only 4
of 18 are declared sources, and `Facility` carries no URL to distinguish them; the 4 carry rules
and so report `scraped` from the blob itself.

Data sources — **everything authoritative is SOURCED**; `data/` carries no source-of-truth facts:
- **Sourced (WFS roster + scrapers):** identity, geo, address, basin physicals, schedules, prices,
  closures — all extracted by providers, composed into `facility_doc`. Regenerate the catalog
  snapshot with `uv run python -m swimzh.cli build-catalog --out data/catalog.json`.
- **Thin crosswalk (facts on no page, committed in git):** `data/pools/*.yaml` per-basin
  `lane_plan_source` (url + optional `section`) URL→basin binding, and `data/registry.yaml`
  (aliases, Baditicker/crowdmonitor keys, kind overrides). Guarded by
  `tests/etl/test_pool_yaml_allowlist.py` (top-level keys ⊆ {`facility_id`, `basins`}; basin ⊆
  {`basin_id`, `name`, `lane_plan_source`}).
- **Single runtime source:** the gold `.sqlite` the app reads (git-ignored; build it, don't
  commit it). `/swim` schedules, `/pools` catalog, and the calendar all come from this one store.

The WFS has locations but not opening hours (`n.a.`). The schedule phase parses the timetable JSON
embedded in stadt-zuerich.ch pool pages (`providers/schedule_scraper.py`) — brittle, pinned by a
saved-page fixture test. Under the atomic build it is **fail-fast**: an unparseable declared page
aborts the build (a benign unresolved *extra* scrape name is the one non-fatal miss, exit 1).

The lane phase attaches per-basin Belegungsplan lane plans. `Basin.lane_plan_source` (url + optional
`section`) is the thin-crosswalk binding, carried through `compose` onto the scraped basins so it
survives the schedule scrape. The fetch-set is **discovered** (the page provider emits Belegungsplan
links; the lane provider fetches them), and each authored binding is validated against discovery
(`authored − discovered` → `UndiscoveredSource`). Reconciliation is a **deterministic URL-keyed
join** in `etl/silver.py` (a single-basin sheet binds by URL alone; a stacked multi-basin sheet
routes each section by its declared `section` token, failing safe to an audited `UnboundPlan` on any
zero/ambiguous match). A failed declared lane source is **fatal** to the build (no per-basin
`LanePlanUnavailable` hole is persisted any more — the DTO survives only for old-blob round-trip).
See `docs/concepts/lane-plan-url-binding.md`.

**Accepted limitation (flat scrape).** The schedule scraper emits **one synthetic basin**
(`Hauptbecken`) per pool — it cannot split the flat timetable per basin. So a scraped pool's
schedule lives on that synthetic basin while its carried `lane_plan_source` + physicals ride the
named crosswalk basin; the two never coexist. Consequence: the **per-basin lane-availability panel
is inert for scraped pools** — it renders only where genuine per-basin data exists (the illustrative
fixtures / a future per-basin schedule source). Owner-accepted 2026-07-31 (the flat-endpoint cost);
`freshness` — not `provenance.curated` — is the schedule signal.

## Internationalization (pl / en / de / it / fr)

Plan: [`docs/plan/2026-07-25-i18n-plan.md`](docs/plan/2026-07-25-i18n-plan.md). **S1 is done** (the
runtime + the `Intl` layer); the catalog itself is still a seed.

- **`plurals.ts` is the load-bearing file.** `Plural<L>` is a record keyed by the CLDR categories
  *that locale* uses, so a `pl` message missing `many` is a **`tsc` error**, not a silent fallback
  that reads as broken grammar. This is the whole reason the runtime is hand-rolled rather than
  vendored: we own the catalog types. `PLURAL_CATEGORIES` is itself asserted against
  `Intl.PluralRules` so it can never drift from CLDR and lie to the compiler.
- **`i18n.ts` owns `resolveLocale()` — the single locale seam.** Locale lives in a cookie (the only
  channel the server can read, and the shell must emit `<html lang>`); localStorage is a mirror.
  No other module may read that cookie. Adding `/{locale}/` URL prefixes later must be a change
  here and nowhere else.
- **`datefmt.ts` owns every date/number/unit rendering.** Formatting locales are regional:
  `en → en-GB`, `de → de-CH`, `fr → fr-CH`, `it → it-CH`. Bare `en` means **en-US** and would flip
  every date to month-first. Two counter-intuitive facts pinned by tests: Polish takes a *genitive*
  month (`23 lipca`) and lowercases weekday/month names, so no lookup table can do it; and **de-CH
  and it-CH use a DOT decimal separator**, unlike de-DE/it-IT — only fr-CH and pl use a comma.
- **Never re-parse a formatted date.** Use `dayParts()` (`Intl.formatToParts`) and compose. The old
  `formatLabel(...).split(' ')` assumed three space-separated tokens and failed silently elsewhere.
- **Units bypass the catalog**: `Intl.NumberFormat` with `style:'unit'` gets plurals and fractions
  right per locale, so there is no message to get wrong. Only domain nouns (pool, lane, day) need
  catalog plurals.
- Catalogs are **`.ts` modules, not JSON** — `tsc` emits only `.js`, so a JSON catalog would never
  reach `dist/`, and the compile-time guarantees need a module the checker sees.

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
Node 26's default discovery also matches `.test.ts`). Migration state: **23 `.js` modules + 15
`node --test` suites remain**; everything the i18n runtime touches is TypeScript on vitest. Run in this order (crap LAST — it reads the
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
- **A `.js` module cannot import a `.ts` one.** The legacy suites run UNCOMPILED from source under
  `node --test`, so `./foo.js` resolves only if `foo.js` exists on disk — a `.ts` module is `.js`
  only inside `dist/`. Converting a module therefore drags in every `.js` file that imports it,
  *and* their tests (which must move to vitest). Compute that closure before starting, and include
  **dynamic** `await import()` — a static-import scan misses it. Type-checking reaches further
  still: a converted caller cannot type-check against an untyped `.js` export, so give the
  still-`.js` module a `.d.ts` (see `filterstate.d.ts`, `blocks/cursor.d.ts`, `blocks/gantt.d.ts`,
  `components/_fakedom.d.ts`) rather than converting it too.
- **DOM types are structural, not `HTMLElement`** — see `domtypes.ts`. Every component factory is
  duck-typed so the headless suites can hand it `_fakedom.js`'s FakeElement instead of a browser
  node; that is why the tests need no jsdom. Real DOM crosses in via one documented `asEl()` per
  boundary. Factories are generic in their element type (`<T extends El>`) so a caller keeps its
  concrete type instead of widening to `El`.
- **`scripts/crap_ts.mjs`** is the TS CRAP gate — the SAME formula as `scripts/crap.py`
  (`cc²·(1−cov)³ + cc`, offender when `cc > min-complexity` AND `crap > threshold`; `[tool.crap-ts]`
  in `pyproject.toml`). Parity is **formula** parity, not metric parity (eslint's cyclomatic count ≠
  radon's), so `[tool.crap-ts]` is its own ratchet. cc from eslint's `complexity` rule; per-function
  coverage from vitest's Istanbul `coverage-final.json` (`coverage.all: true` lists every source
  `.ts`; crap_ts scores a never-executed file — whose v8 `fnMap` is only `(empty-report)` — via a
  whole-file coverage fallback at 0%, so an untested high-complexity module can't hide).
  A file **absent** from `coverage-final.json` is a different case: it was deliberately excluded in
  `vitest.config.ts` and is **not scored**, exactly as `crap.py` never sees a module that
  coverage.py `omit`s or `# pragma: no cover`s. Only the four browser entrypoints (`app.ts` and the
  three dev-only surfaces) are excluded — narrow that list, never widen it: a new *rule* belongs in
  a measured module, which is what `appdata.ts` exists for.

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
