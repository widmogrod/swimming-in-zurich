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
- `src/swimzh/providers/` — adapters returning `Result[..., ProviderError]` (`curated`
  today; `geo_sport`, occupancy later).
- `data/` — curated YAML (pools, registry, calendar) + `sources.md` legal register.
- `tests/` — mirrors `src/swimzh/` (`tests/core/`, `tests/domain/`, …).

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
