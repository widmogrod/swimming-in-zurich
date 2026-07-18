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
uv run ruff check .
uv run pyright
uv run pytest
```
