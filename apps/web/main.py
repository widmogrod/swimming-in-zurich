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
from apps.web.services.gold_store import GoldSwimData
from apps.web.services.ports import SwimData
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.storage.sqlite_repo import load_catalog, open_db


def _require_gold_db(gold_db: Path) -> None:
    """Fail fast at startup when the gold store is missing — it is the single source of
    truth and must be built first."""
    if not gold_db.exists():
        raise RuntimeError(
            f"gold store {gold_db} not found; build it first (run `swimzh build --db {gold_db}`)"
        )


def _load_swim_data(config: Config) -> SwimData:
    """Serve facilities + calendar from the gold store (fail-fast if empty)."""
    return GoldSwimData.open(config.gold_db)


def _load_catalog(config: Config) -> tuple[PoolCatalogEntry, ...]:
    """Read the pool catalog from the gold store's `catalog` table (same store as `/swim`)."""
    return load_catalog(open_db(config.gold_db))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Config.from_env()
    _require_gold_db(config.gold_db)
    app.state.config = config
    app.state.swim_data = _load_swim_data(config)
    app.state.catalog = _load_catalog(config)
    yield


app = FastAPI(title="Swimming in Zürich", lifespan=lifespan)
app.include_router(ui_router)
app.include_router(health_router)
app.include_router(swim_router)
app.include_router(pools_router)
app.include_router(access_router)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    startup_config = Config.from_env()
    uvicorn.run("apps.web.main:app", host=startup_config.host, port=startup_config.port)
