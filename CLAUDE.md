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
- `src/swimzh/etl/` + `src/swimzh/storage/` — medallion raw→silver→gold (pure functions)
  into the SQLite gold store; `find_swim_options` reads from `GoldRepository`.
- `apps/web/` — FastAPI service + minimal HTML UI over the swim data (see below).
- `data/` — curated YAML (pools, registry, calendar) + `sources.md` legal register.
- `tests/` — mirrors `src/swimzh/`; `apps/web/tests/` mirrors the service.

## Web UI / API

```sh
uv run uvicorn apps.web.main:app --reload      # http://127.0.0.1:8000  (UI at /, API at /swim)
```

`GET /swim?at=<ISO datetime>&gender=female|male|diverse&age=<int>&lat=&lon=&radius_km=&eligible_only=true`
returns eligibility-annotated options + statuses + warnings. Follows the
`python-dev:fastapi-service` conventions; deviations recorded in
`docs/concepts/fastapi-service-integration.md`.

Endpoints: `/swim` (query), `/pools` (list all ~57 pools from the catalog, `?kind=` filter),
`/access-types` (explanations), `/health`, `/` (UI: find tab + all-pools browser).

Data sources:
- **Catalog** (all pools, every category): committed `data/catalog.json`, generated from the
  WFS. Regenerate with `uv run python -m swimzh.cli build-catalog --out data/catalog.json`.
- **Schedules** (`/swim`): the `SwimData` port — `SWIMZH_GOLD_DB` (SQLite gold store) if set
  and present, else the curated dataset (offline default). Build gold with:
  ```sh
  uv run python -m swimzh.cli build-gold --db gold.sqlite
  SWIMZH_GOLD_DB=gold.sqlite uv run uvicorn apps.web.main:app --reload
  ```
Note: the WFS has locations but not opening hours (`n.a.`); schedules are curated/scraped.

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

- **Type checker**: `mypy .` (strict) is the canonical gate. `pyright` (strict) is also
  configured and passes; both agree. Either is fine locally; CI uses mypy.
- **Coverage floor**: `fail_under` in `[tool.coverage.report]` is a no-regression ratchet
  (currently 91, calibrated to real coverage of 91.91%). Raise it as coverage grows; never
  lower it without a reason.
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
