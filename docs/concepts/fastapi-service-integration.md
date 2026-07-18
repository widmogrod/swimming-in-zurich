# FastAPI service integration — recorded deviations

The web UI/API was scaffolded via `/dev:init fastapi` and follows the
`python-dev:fastapi-service` conventions (composition root in `main.py`, per-endpoint
`api/<ep>/{router,model,service}.py`, ports as `typing.Protocol`, all env in `config.py`,
thin routers). Two deliberate deviations from the default archetype, because this repo is a
single installable library (`swimzh`) with a `src/` layout and one QA chain:

1. **Location & imports.** The service lives at `apps/web/` (not a separate root project)
   and uses absolute imports rooted at `apps.web` (e.g. `from apps.web.api.swim.router
   import router`) instead of the archetype's flat top-level imports (`from api...`, `from
   config`). This keeps it inside the existing uv project and the single ruff/mypy/pytest/
   coverage chain (all extended to include `apps/`).

2. **No separate `pyproject.toml`.** `fastapi` + `uvicorn` are dev-group dependencies of the
   root project; the published wheel (`swimzh`) does not depend on them.

## Data source

`main.py` wires `CuratedSwimData` (a `SwimData` port implementation) that loads the curated
dataset at startup — offline, no network. Swapping to the SQLite gold store later is a second
adapter satisfying the same `SwimData` protocol; no endpoint/service change required.

## Run

```sh
uv run uvicorn apps.web.main:app --reload      # http://127.0.0.1:8000
```
Env (all in `apps/web/config.py`): `SWIMZH_DATA_DIR` (default `data`), `SWIMZH_HOST`,
`SWIMZH_PORT`.
