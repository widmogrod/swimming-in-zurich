---
type: concept
created: 2026-07-25
links: ["[[2026-07-25-typescript-migration-plan]]", "[[fastapi-service-integration]]"]
---

# TypeScript build pipeline (compiled UI with CRAP parity)

The UI is authored in TypeScript under `apps/web/static/js/` and **compiled** by `tsc` to
`apps/web/static/dist/` (a git-ignored build artifact). The FastAPI `/static` mount serves the
compiled output; the page loads `/static/dist/app.js`. `tsc` uses `allowJs`, so during the
incremental migration still-`.js` modules compile alongside `.ts` ones into the same `dist/` — ESM
import specifiers keep the `./foo.js` extension so they resolve identically before and after a file
flips to `.ts`. The dev entrypoint (`python -m apps.web.main`) runs the build as a fail-fast
preflight before serving.

Two tsconfigs, one strictness: `tsconfig.json` emits (`strict`, excludes tests); `tsconfig.dev.json`
extends it, `noEmit`, and widens `include` to type-check **tests too** — the dev config may only
widen `include`, never loosen a flag.

QA parity with the Python core (which runs ruff/mypy/pytest+coverage/`scripts/crap.py`): the TS
chain is prettier → eslint → `tsc -p tsconfig.dev.json --noEmit` → vitest (V8 coverage) →
**`scripts/crap_ts.mjs`**. The CRAP script mirrors `scripts/crap.py` exactly —
`crap = cc²·(1−cov)³ + cc`, offender when `cc > min_complexity` AND `crap > threshold` — fed by
eslint's `complexity` rule (cyclomatic complexity per function) and vitest's `coverage-final.json`.
Run vitest before crap (it writes the coverage the gate reads), just as pytest precedes crap.

Runners coexist during migration: `node --test` (via `apps/web/tests/test_static_js.py`) for the
shrinking `.js` set, vitest for the growing `.ts` set — both invoked from `uv run pytest`. Neither is
retired until the last module is TypeScript.
