"""Composition root — the only module that imports concrete adapters.

Wiring happens in the lifespan context manager; dependencies are exposed via `app.state`
(read back through `apps.web.deps`). All data is read fail-fast at startup from the single
gold SQLite store (built by `swimzh build`) — no curated `data/` files are read at runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from apps.web.api.access.router import router as access_router
from apps.web.api.health.router import router as health_router
from apps.web.api.pools.router import router as pools_router
from apps.web.api.swim.router import router as swim_router
from apps.web.api.ui.router import router as ui_router
from apps.web.config import Config
from apps.web.services.gold_store import GoldSwimStore
from apps.web.services.ports import SwimStore


def _missing_db_message(gold_db: Path) -> str:
    return (
        f"gold store '{gold_db}' not found — it is the app's single source of truth.\n"
        f"Build it first:  uv run python -m swimzh.cli build --db {gold_db}"
    )


def _require_gold_db(gold_db: Path) -> None:
    """Fail fast at startup when the gold store is missing — it is the single source of
    truth and must be built first."""
    if not gold_db.exists():
        raise RuntimeError(_missing_db_message(gold_db))


def startup_error(config: Config) -> str | None:
    """A human-readable reason the app cannot start (missing or empty gold store), or None.

    Used by the `python -m apps.web.main` entrypoint to report cleanly (one line, no
    traceback) before uvicorn starts. The lifespan below is the defense-in-depth net for
    other launch paths (`uvicorn apps.web.main:app`, `TestClient`)."""
    if not config.gold_db.exists():
        return _missing_db_message(config.gold_db)
    try:
        GoldSwimStore.open(config.gold_db)
    except RuntimeError as exc:  # empty / unreadable store
        return str(exc)
    return None


def _load_swim_data(config: Config) -> SwimStore:
    """Open the one gold store — facilities, roster, and calendar (fail-fast if empty).

    `/swim` and `/pools` both read this single store, joined on the canonical `pool.id`."""
    return GoldSwimStore.open(config.gold_db)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Config.from_env()
    _require_gold_db(config.gold_db)
    app.state.config = config
    app.state.swim_data = _load_swim_data(config)
    yield


app = FastAPI(title="Swimming in Zürich", lifespan=lifespan)
app.include_router(ui_router)
app.include_router(health_router)
app.include_router(swim_router)
app.include_router(pools_router)
app.include_router(access_router)


def main() -> None:  # pragma: no cover
    """Clean dev entrypoint: preflight the gold store, then serve.

    Reports a one-line, actionable error and exits 1 if the store is missing/empty —
    no ASGI traceback. Run: `SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main`."""
    import sys

    import uvicorn

    config = Config.from_env()
    error = startup_error(config)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    uvicorn.run("apps.web.main:app", host=config.host, port=config.port, reload=config.reload)


if __name__ == "__main__":  # pragma: no cover
    main()
