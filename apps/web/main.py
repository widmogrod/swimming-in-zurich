"""Composition root — the only module that imports concrete adapters.

Wiring happens in the lifespan context manager; dependencies are exposed via `app.state`
(read back through `apps.web.deps`). The swim data is loaded fail-fast at startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.web.api.health.router import router as health_router
from apps.web.api.swim.router import router as swim_router
from apps.web.api.ui.router import router as ui_router
from apps.web.config import Config
from apps.web.services.curated_store import CuratedSwimData


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Config.from_env()
    app.state.config = config
    app.state.swim_data = CuratedSwimData.load(config.data_dir)
    yield


app = FastAPI(title="Swimming in Zürich", lifespan=lifespan)
app.include_router(ui_router)
app.include_router(health_router)
app.include_router(swim_router)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    startup_config = Config.from_env()
    uvicorn.run("apps.web.main:app", host=startup_config.host, port=startup_config.port)
