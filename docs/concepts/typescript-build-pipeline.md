---
type: concept
created: 2026-07-25
links: ["[[2026-07-25-typescript-migration-plan]]", "[[fastapi-service-integration]]", "[[2026-07-25-i18n-plan]]"]
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

## Conversion is closure-shaped, not file-shaped

The claim above that `./foo.js` specifiers "resolve identically before and after a file flips to
`.ts`" holds for the **compiled** output and for a `.ts` module importing a `.js` one. It does NOT
hold in the direction that matters when converting: the legacy suites run **uncompiled from
source**, so a still-`.js` module importing `./datefmt.js` gets `ERR_MODULE_NOT_FOUND` — that file
exists only in `dist/`.

So converting a module drags in every `.js` module that imports it, and their tests. Compute the
closure first, and note two ways it is bigger than a naive scan suggests:

- **Dynamic `await import()`** is invisible to a static `from '...'` scan (this hid
  `datestepper_tz.test.js`).
- **Type-checking reaches further than module resolution.** A converted caller cannot type-check
  against an untyped `.js` export — `no-unsafe-*` rejects the inferred `any`. The fix is a `.d.ts`
  beside the `.js` module (`filterstate.d.ts`, `blocks/cursor.d.ts`, `blocks/gantt.d.ts`,
  `components/_fakedom.d.ts`), which keeps it out of the conversion closure entirely.

The i18n S1 closure was 22 files: 11 modules + 11 suites.

## DOM types are structural

`domtypes.ts` declares the DOM surface the factories actually touch rather than using
`HTMLElement`. Every factory is duck-typed so the headless suites can pass `_fakedom.js`'s
FakeElement — that is why this codebase needs no jsdom — and typing them as `HTMLElement` would be
a lie the first test disproves. A real browser node is deliberately NOT assignable to `El`; it
crosses via one documented `asEl()` per boundary. Factories are generic in their element type
(`createBoard<T extends El>(el: T, …)`) so callers keep their concrete type instead of widening.

## What the CRAP gate does with entrypoints

`crap_ts.mjs` walks the source tree itself, so a `vitest.config.ts` coverage exclusion would
otherwise make a file *worse* (0%) rather than unscored. It now mirrors `crap.py`: a file **absent**
from `coverage-final.json` was deliberately excluded and is not scored, exactly as coverage.py's
`omit`/`# pragma: no cover` keeps a module out of `crap.py`'s view. A file that is *measured but
never executed* still appears (with an `(empty-report)` fnMap) and is still scored at 0%, so the
untested-module hole stays closed.

Only the four browser entrypoints are excluded — `app.ts` plus the three dev-only surfaces. The
pure transforms behind `app.ts` live in `appdata.ts` precisely so they stay measured.
