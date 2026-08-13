---
type: summary
created: 2026-07-25
links: ["[[typescript-build-pipeline]]", "[[2026-07-25-typescript-migration-plan]]"]
---

# TypeScript migration — what exists now

The `apps/web/` UI is on a **compiled-TypeScript pipeline with CRAP parity**, migrating
incrementally. See [[typescript-build-pipeline]] for the durable conventions.

## Build + serve

- Source lives in `apps/web/static/js/`; `tsc` (`tsconfig.json`, `allowJs`, `strict`,
  `module`/`moduleResolution` `nodenext`, `target es2022`) compiles the whole tree — `.ts` AND
  still-`.js` modules — to **git-ignored `apps/web/static/dist/`**. ESM `./x.js` specifiers are
  preserved, so files resolve identically before/after a `.js → .ts` flip.
- All four served entry routers point at `/static/dist/…` (`ui`, `gallery`, `detail_preview`,
  `board_preview`). `apps/web/main.py`'s `main()` runs `npm run build` as a fail-fast preflight before
  serving (NOT in `create_app()`, so `TestClient` never builds). `uv run pytest` needs no build — the
  path-assertion tests check router HTML substrings, and the no-store test fetches existing source.

## QA — two separate chains

- **Python**: `uv run pytest` keeps the `node --test` bridge (`apps/web/tests/test_static_js.py`),
  scoped to `**/*.test.js` (Node 26's default glob also matches `.test.ts`). Zero npm dependency.
- **TypeScript**: `npm --prefix apps/web/static/js run qa` = `fmt:check → lint → type-check → test →
  crap`, its own `ts-qa` CI job (`setup-node` + `npm ci`). `type-check` (`tsconfig.dev.json`) and
  eslint cover tests at full strictness; both scoped to `**/*.ts` during migration (legacy `.js`
  ignored). `scripts/crap_ts.mjs` is the CRAP gate — same formula as `scripts/crap.py`
  (`cc²·(1−cov)³ + cc`, `[tool.crap-ts]` 30/5), cc from eslint's `complexity` rule, per-function
  coverage from vitest's Istanbul `coverage-final.json`. `coverage.all: true` + a whole-file
  fallback (for v8's `(empty-report)` fnMap on untested files) mean an untested high-complexity
  module scores 0% and cannot hide. Parity is **formula** parity, not metric parity.

## Migrated so far

- **`urlstate.ts`** (+ `urlstate.test.ts` on vitest) — the pilot. Pure FilterState⇄query projection,
  strict-typed (local `UrlFilterState`/`UrlStateContext`/`FilterPatch`), 100% statement coverage.

## Remaining (follow-up, module-by-module)

The other 34 source modules + 26 `node --test` suites are still `.js`. Each migrates as a small
vertical change: rename `.js → .ts`, add types, move its test to vitest (`.test.ts`) — it then joins
the lint/format/type-check/vitest/CRAP scope and drops out of the `node --test` bridge. Retiring the
bridge + the legacy-`.js` lint/format ignores happens when the last module lands.
