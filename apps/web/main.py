"""Composition root — the only module that imports concrete adapters.

Wiring happens in the lifespan context manager; dependencies are exposed via `app.state`
(read back through `apps.web.deps`). All data is read fail-fast at startup from the single
gold SQLite store (built by `swimzh build`) — no curated `data/` files are read at runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from apps.web.api.access.router import router as access_router
from apps.web.api.health.router import router as health_router
from apps.web.api.pools.router import router as pools_router
from apps.web.api.swim.router import router as swim_router
from apps.web.api.ui.router import router as ui_router
from apps.web.config import Config
from apps.web.services.gold_store import GoldSwimStore
from apps.web.services.ports import SwimStore

_STATIC_DIR = Path(__file__).resolve().parent / "static"


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


def create_app(config: Config | None = None) -> FastAPI:
    """Build the ASGI app. The composition root: the only place adapters are wired
    and the only place routers are registered.

    `config` defaults to `Config.from_env()`. The dev-only `/ui/gallery` route is
    registered ONLY when `config.dev_ui` is set, so it is absent in production
    (a route is always mounted once included — the flag gates the include itself).

    The gold store is resolved LAZILY in the lifespan (env read at startup, not at
    import), so the module-level `app` picks up `SWIMZH_GOLD_DB` set after import
    (e.g. by the test fixtures). Route registration, by contrast, must happen now,
    at build time — so `dev_ui` is read here."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = config or Config.from_env()
        _require_gold_db(cfg.gold_db)
        app.state.config = cfg
        app.state.swim_data = _load_swim_data(cfg)
        # Live water-temperature provider (OPTIONAL, fail-open). No real Baditicker adapter is
        # wired yet — that lands in a later slice behind config; until then the app runs with
        # `None`, which `/pools/{id}` reports as `TempUnavailable("live temperature not
        # configured")`. Tests override `app.state.temperature` with an in-memory fake.
        app.state.temperature = None
        yield

    app = FastAPI(title="Swimming in Zürich", lifespan=lifespan)
    # Static design-system assets (tokens/components CSS + ES modules) — net-new
    # infra this slice adds; first consumer is the dev gallery.
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(ui_router)
    app.include_router(health_router)
    app.include_router(swim_router)
    app.include_router(pools_router)
    app.include_router(access_router)
    if (config or Config.from_env()).dev_ui:
        # Dev: never let the browser cache the design-system assets, so an edit to a
        # CSS/JS module is seen on the next reload instead of a stale cached module
        # (ES modules are cached aggressively otherwise). Production keeps default caching.
        @app.middleware("http")
        async def _no_cache_static(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            response = await call_next(request)
            if request.url.path.startswith("/static/"):
                response.headers["Cache-Control"] = "no-store"
            return response

        from apps.web.api.board_preview.router import router as board_preview_router
        from apps.web.api.detail_preview.router import router as detail_preview_router
        from apps.web.api.gallery.router import router as gallery_router

        app.include_router(gallery_router)
        app.include_router(board_preview_router)
        app.include_router(detail_preview_router)
    return app


app = create_app()


_JS_DIR = _STATIC_DIR / "js"


def _build_static_assets() -> None:  # pragma: no cover
    """Compile the TS/JS UI (`static/js` → `static/dist`) before serving, so a source
    edit is reflected in what the browser loads. Fail fast if the build errors — a stale
    or missing `dist/` would serve a blank SPA. Not run in `create_app()` (the test path):
    `TestClient` serves the source `/static/js` tree, and `dist/` is a git-ignored artifact."""
    import subprocess

    subprocess.run(  # noqa: S603
        ["npm", "--prefix", str(_JS_DIR), "run", "build"],  # noqa: S607
        check=True,
    )


def main() -> None:  # pragma: no cover
    """Clean dev entrypoint: build the UI, preflight the gold store, then serve.

    Reports a one-line, actionable error and exits 1 if the store is missing/empty —
    no ASGI traceback. Run: `SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main`."""
    import sys

    import uvicorn

    _build_static_assets()
    config = Config.from_env()
    error = startup_error(config)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    uvicorn.run("apps.web.main:app", host=config.host, port=config.port, reload=config.reload)


if __name__ == "__main__":  # pragma: no cover
    main()
