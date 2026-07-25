---
type: plan
status: approved         # draft -> approved -> in-progress -> done
created: 2026-07-25
feature: typescript-migration
gates:
  qa: full               # ruff, mypy, pytest+coverage, CRAP (Python) + the new TS chain per slice
  review: adversarial    # dev:critic-reviewer must find no blocking issues
pause_after: [S1]        # the build+serve restructure is the riskiest step — verify the app still boots
links: ["[[typescript-build-pipeline]]", "[[fastapi-service-integration]]"]
---

# TypeScript migration — compiled TS UI with CRAP parity

## Context

The UI is ~8,500 LOC across **35 native-ES-module source files + 27 `node --test` suites** under
`apps/web/static/js/`, served **directly** with no build step (a deliberate choice, documented in
`apps/web/static/js/package.json` and `apps/web/tests/test_static_js.py`). The Python core has a
strict, gated QA chain (ruff, mypy, pytest+coverage, and the `scripts/crap.py` CRAP metric
`cc²·(1−cov)³ + cc`); the JS has only `node --test` with no types, no lint, and **no CRAP
equivalent** — so JS complexity/coverage risk is invisible to the gate.

This plan establishes a **compiled-TypeScript pipeline with QA parity**, then converts a single
pilot module end-to-end to prove it. Per the agreed approach it is **incremental**: after this
plan lands (toolchain + build + vitest + a TS-CRAP gate + one pilot module), the remaining 34
modules and 26 tests migrate **module-by-module in follow-up work** — out of scope here. Tooling
decisions (agreed): **npm** (chosen for zero new tooling; `pnpm` is also installed but not used),
**vitest** (mature V8 per-line coverage to feed CRAP), retrofitting the
`typescript-dev:qa-toolchain` conventions. Introduces the [[typescript-build-pipeline]] concept and
builds on [[fastapi-service-integration]].

## Design (signature altitude)

**Build + serve (the load-bearing change):**

- Source stays at `apps/web/static/js/` (minimal churn). A `tsconfig.json` with
  `rootDir: "apps/web/static/js"`, `outDir: "apps/web/static/dist"`, `allowJs: true`,
  `strict: true`, `module/target: ESNext`, `moduleResolution: "nodenext"` (an emitting ESM build of
  runnable modules with explicit `.js` specifiers — not a bundler-owned `noEmit` scenario) compiles
  the whole
  tree — `.ts` files AND still-`.js` files (`allowJs`) — into `apps/web/static/dist/`. ESM import
  specifiers keep the `./foo.js` extension (TS ESM convention) so they resolve identically in
  `dist/`.
- `apps/web/static/dist/` is a **build artifact** — git-ignored, never committed.
- **Every served entry module is repointed to `/static/dist/…`, not just `app.js`.** `grep -rn
  "/static/js" apps/web` finds **four** entry-point routers, all of which must move together (tsc
  `allowJs` emits the whole tree into `dist/`, so every module — and its transitive imports like
  `../timescale.js` — is present there):
  - `apps/web/api/ui/router.py` → `/static/dist/app.js`
  - `apps/web/api/gallery/router.py` → `/static/dist/components/gallery.js`
  - `apps/web/api/detail_preview/router.py` → `/static/dist/blocks/detail_preview.js`
  - `apps/web/api/board_preview/router.py` → `/static/dist/blocks/board_preview.js`
  The `/static` StaticFiles mount (`main.py:91`) already serves `static/dist/`, so no mount change.
  The five **script-tag string** assertions that pin these paths move in lockstep (`test_shell.py:39`,
  `test_design_system.py:237`, `test_gallery.py:112`, `test_board.py:45`, `test_detail_preview.py:43`)
  — they assert a substring of the router HTML, so they pass on the string change alone with **no
  build required at test time**.
- **The dev-cache no-store test is NOT repointed.** `test_gallery.py:70`
  (`test_dev_serves_static_assets_no_store`) does a LIVE `client.get(...)` and asserts `200` +
  `cache-control: no-store`. Repointing it to `/static/dist/app.js` would 404 under `uv run pytest`:
  `TestClient` builds via `create_app()`, which never runs the build preflight (that lives in
  `main()`), and `dist/` is git-ignored/unbuilt at test time. `no-store` is a **mount-wide** dev
  behavior, so the test keeps fetching an asset that exists at test time — the source `/static/js/app.js`
  (S1 renames no file, so the source stays mounted). Content-fetch tests of source modules
  (`test_honesty.py`, `test_design_system.py:219` → `/static/js/components/segmentedcontrol.js`) are
  likewise left as-is — those source files still 200 from the mounted tree.
- The dev entrypoint (`python -m apps.web.main`) runs `npm --prefix apps/web/static/js run build`
  as a preflight before serving (fail-fast if the build errors), so a source edit is reflected.
- `tsconfig.dev.json` `extends` the emit config, `noEmit: true`, and **widens `include` to cover
  tests** — `tsc -p tsconfig.dev.json --noEmit` type-checks source AND tests at one strict level
  (the `qa-toolchain` invariant). The dev config may only widen `include`, never loosen strictness.

**Test + lint (npm scripts in `apps/web/static/js/package.json`):**

- `vitest` (+ `@vitest/coverage-v8`) with a `jsdom` environment for DOM-touching modules; V8
  coverage emits a per-line JSON (`coverage/coverage-final.json`) — the CRAP input.
- `eslint` (flat config, `typescript-eslint`) + `prettier` per the pack. Lint covers tests too.
  **Scoped to migrated files during the migration window:** eslint/prettier target `**/*.ts` only
  (via config `files`/`--ext` + a `.prettierignore` listing the legacy `.js`), because the ~60
  un-migrated `.js` files were never prettier-formatted (single-quoted imports vs prettier's default)
  and reformatting the user's in-flight `.js` is out of scope. Each module joins the lint/format
  scope as it converts to `.ts`; the legacy exclusions shrink to nothing when migration completes.
- Scripts: `build` (`tsc`), `type-check` (`tsc -p tsconfig.dev.json --noEmit`), `lint`, `fmt:check`,
  `test` (`vitest run --coverage`), `crap` (the new TS gate), `qa` (the chain in order).

**Two SEPARATE, self-contained QA chains (not one bridged into the other):**

- **Python chain** — `uv run pytest` keeps the existing `node --test` bridge (`test_static_js.py`)
  for the shrinking `.js` set. It stays **zero-npm-dependency**: `node` is present on CI runners and
  locally, and `node --test` needs no `node_modules`. No pytest test fetches the git-ignored `dist/`
  (see the no-store note above), so pytest never needs a build. As a module migrates, its test leaves
  the `node --test` set (moves to vitest); the bridge shrinks but is never deleted here.
- **TypeScript chain** — `npm run qa` (fmt:check → lint → type-check → vitest+coverage → crap_ts) is
  its own command and its **own CI job**, with `actions/setup-node` + `npm ci` so vitest/tsc/eslint
  have their deps. This avoids a hollow gate (bridging vitest into pytest would need `node_modules`
  the Python CI job lacks) and mirrors the `typescript-dev` pack's separate chain. CI runs both jobs;
  a failure in either fails the build.

**TS-CRAP parity (`scripts/crap_ts.mjs`):**

- Mirrors `scripts/crap.py` exactly: `crap = cc²·(1−cov)³ + cc`; flags a function only when
  `cc > min_complexity` AND `crap > threshold`; prints the top-N riskiest; exits 1 on any offender.
- **Complexity source**: `eslint` `complexity` rule set to `["warn", 0]` with `-f json` — `line` is a
  structured field, but the cc **number is embedded in the message string** ("…has a complexity of
  N…"), so `crap_ts` regex-extracts it. **Coverage source**: vitest's `coverage-final.json` — note it
  is **Istanbul-shaped** (`statementMap` spans + `s` hit-counts + `fnMap`), NOT coverage.py's
  executed/missing line sets, so `crap_ts` derives per-function covered/uncovered from the statement
  map + hit counts (per-function line span) rather than copying `crap.py`'s line-set logic verbatim.
- **Parity is FORMULA parity, not metric parity.** eslint's cyclomatic count and radon's differ
  algorithmically, so a TS function's cc need not equal the "same" Python function's. That is fine and
  intended: `[tool.crap-ts]` is calibrated to TS reality and ratchets independently — the shared thing
  is the `cc²·(1−cov)³ + cc` formula, offender rule, and report shape, not the raw numbers.
- Config lives beside the Python one — `[tool.crap-ts] threshold / min-complexity` in
  `pyproject.toml` (or a sibling json), calibrated to current TS reality, its own no-regression
  ratchet.
- Wired into the QA chain AFTER vitest (which writes the coverage JSON it reads), matching the
  "pytest before crap" ordering.

**Pilot module:** `urlstate.js` → `urlstate.ts` (a small, **pure**, freshly-committed, well-tested
leaf — the FilterState⇆query-string projection). It is the right pilot because it is a **true sink**:
its only importers are `app.js` (a source entry module that **no test loads** — nothing imports
`app.js`) and its own `urlstate.test.js`. So converting it to `.ts` breaks **no** remaining `.js`
`node --test` suite (none import it, directly or transitively), and at runtime `app.js` resolves
`./urlstate.js` from the compiled `dist/`. It converts in **S2, together with its test**
(`urlstate.test.js` → vitest `urlstate.test.ts`) — never split across slices. (`timescale` was
rejected as pilot: 6 `.js` test suites import it, so converting it first would red the bridge —
it migrates late, once its importers are TypeScript.) **S1 converts no file to `.ts`** (all modules
stay `.js` under `allowJs`); it only proves build+serve. So the pilot proves types + vitest + CRAP
once vitest exists, without ever leaving a slice red.

## Out of scope

- **Converting the other 34 source modules + 26 test suites.** The whole point of "incremental" —
  they migrate `.js → .ts` module-by-module in follow-up work, each a small vertical change on the
  pipeline this plan builds. Removing the `node --test` bridge / `static/js/package.json`'s current
  role happens when the last module lands, not here.
- **`clean-architecture` / eslint architecture-test project.** The UI has no ports/adapters layering
  to enforce; deferred.
- **Any Python / API / gold-store change.** This is a frontend build + QA change only. The one
  Python touch is the dev-entrypoint build preflight and the `ui/router.py` script-tag path.
- **CSS pipeline / bundling / minification / source maps for prod.** `tsc` emit only; no bundler.

## Slices

### S1 — Build + serve pipeline (no `.ts` conversion yet)

- **Goal**: the app is served from compiled output — `tsc` (`allowJs`, all modules still `.js`)
  emits `static/js` → `static/dist`, and every entry page loads its module from `/static/dist/…`
  and boots identically.
- **Touches**:
  - NEW `apps/web/static/js/tsconfig.json` + `tsconfig.dev.json`; `package.json` gains `typescript`
    dev-dep + `build`/`type-check` scripts.
  - **All four entry routers** → `/static/dist/…`: `apps/web/api/ui/router.py`,
    `apps/web/api/gallery/router.py`, `apps/web/api/detail_preview/router.py`,
    `apps/web/api/board_preview/router.py`.
  - **The five script-tag string assertions** (update the expected `/static/dist/…` substring):
    `test_shell.py:39`, `test_design_system.py:237`, `test_gallery.py:112`, `test_board.py:45`,
    `test_detail_preview.py:43`. **The no-store test (`test_gallery.py:70`) is NOT touched** (it
    live-fetches source `/static/js/app.js`, which still exists — see Design).
  - `apps/web/main.py` — run `npm --prefix apps/web/static/js run build` as a fail-fast preflight
    before uvicorn serve.
  - `.gitignore` — `apps/web/static/dist/`.
  - `.github/workflows/qa.yml` — add a **`ts-qa` job** (`actions/setup-node` + `npm --prefix
    apps/web/static/js ci` + `npm run build` + `npm run type-check`), separate from the existing
    Python `qa` job. (S2/S3 extend this job with lint/fmt/test/crap.)
  - **No source file is renamed to `.ts` in this slice.**
- **Acceptance**:
  - `npm --prefix apps/web/static/js run build` exits 0 and produces a complete `static/dist/` tree
    (`app.js`, `components/gallery.js`, `blocks/detail_preview.js`, `blocks/board_preview.js`, and
    every transitive import e.g. `timescale.js`).
  - `tsc -p tsconfig.dev.json --noEmit` passes (source only; tests excluded until S2).
  - Driving the running app (build + `SWIMZH_GOLD_DB=… python -m apps.web.main`) renders the board +
    DetailPanel and loads `/static/dist/app.js` (200) — verified end-to-end in a browser. A blank-SPA
    regression must be caught. The three preview/gallery pages also load their `/static/dist/…`
    module (200, no dangling-import 404).
  - `static/dist/` is git-ignored (not committed).
  - **`uv run pytest` is green with NO build step** — the five repointed tests assert a router HTML
    substring (no fetch of `dist/`), the no-store test still fetches existing source, and the
    `node --test` bridge is unchanged (no source became `.ts`). Full Python QA chain green.
  - The CI `ts-qa` job runs `npm ci` + `npm run build` + `npm run type-check` green (the build is
    exercised in CI even though pytest doesn't need it).
- **Depends on**: —

### S2 — vitest harness + the pilot module & test converted to TypeScript

- **Goal**: `urlstate` is authored in TypeScript and its test runs on vitest, type-checked at
  strict and emitting V8 coverage — while the other 26 suites keep running on the `node --test`
  bridge, all green.
- **Touches**:
  - `package.json` — `vitest` + `@vitest/coverage-v8` + `eslint`/`typescript-eslint` + `prettier`
    dev-deps; `test`/`lint`/`fmt:check` scripts; NEW `vitest.config.ts` (jsdom env available; the
    pilot is pure so `node` env suffices), `eslint.config.js`, `.prettierrc`, `.prettierignore`
    (legacy `.js`).
  - `apps/web/static/js/urlstate.js` → `urlstate.ts` (typed) **and** `urlstate.test.js` →
    `urlstate.test.ts` (vitest imports) **together**. Safe because `urlstate` is a true sink — its
    only importers are `app.js` (loaded by no test) and its own test — so no other `.js` `node --test`
    suite resolves `./urlstate.js`, and `app.js` resolves it from `dist/` at runtime.
  - `apps/web/tests/test_static_js.py` — **unchanged in mechanism**: it keeps running `node --test`
    for the remaining `.js` suites. `node --test` recursively discovers `*.test.js`, so the removed
    `urlstate.test.js` simply drops out of its set; no other `.js` suite is affected. Vitest is NOT
    bridged into pytest (it runs in the separate TS chain).
  - `.github/workflows/qa.yml` — extend the `ts-qa` job with `npm run lint`, `npm run fmt:check`,
    `npm run test` (vitest+coverage).
  - `tsconfig.dev.json` `include` now covers `*.test.ts`.
- **Acceptance**:
  - `npm --prefix apps/web/static/js run test` runs the `urlstate` vitest suite green and writes
    `coverage/coverage-final.json` (Istanbul-shaped) covering `urlstate.ts`.
  - `tsc -p tsconfig.dev.json --noEmit` type-checks `urlstate.test.ts` at full strictness (a
    deliberate type error in the test fails it — no `any`/`@ts-expect-error` escape).
  - `npm run lint` and `npm run fmt:check` — **scoped to `**/*.ts`** (legacy `.js` in
    `.prettierignore` / eslint ignores) — pass; running them does not flag the un-migrated `.js`.
  - `uv run pytest` is green: the `node --test` bridge now covers the remaining `.js` suites
    (**urlstate dropped, every import still resolving**), with NO npm dependency and no `dist/` fetch.
  - The app still builds and boots (`urlstate.ts` compiles into `dist/`; `app.js` imports it from
    there) — spot-checked in the browser.
  - Both CI jobs (Python `qa`, `ts-qa`) green.
- **Depends on**: S1.

### S3 — TS-CRAP gate at parity with Python

- **Goal**: a TypeScript CRAP gate using the identical formula, wired into the QA chain and
  calibrated, that can genuinely fail.
- **Touches**:
  - NEW `scripts/crap_ts.mjs` (or `.py` wrapper) — `cc²·(1−cov)³ + cc`, eslint-`complexity` JSON for
    cc + vitest `coverage-final.json` for coverage, same offender rule and top-N report as
    `crap.py`.
  - `pyproject.toml` — `[tool.crap-ts] threshold / min-complexity` (calibrated).
  - `package.json` — `crap` + `qa` scripts (chain in order: fmt:check → lint → type-check → test →
    crap).
  - `.github/workflows/qa.yml` — the `ts-qa` job runs the full `npm run qa` (crap last, after vitest
    writes coverage — mirroring pytest-before-crap).
  - `CLAUDE.md` — document the TS chain + its command order, that type-check + lint cover tests, the
    dist/serve model, and that the TS chain is a SEPARATE CI job from the Python `uv run pytest`.
- **Acceptance**:
  - `npm run crap` computes CRAP for every TS function from the two JSON inputs and exits 0 on the
    current pilot code; a synthetic high-complexity, low-coverage `.ts` function makes it exit 1 with
    that function named (proving it isn't a no-op) — then that fixture is removed.
  - The score for a known `urlstate.ts` function matches a hand-computed `cc²·(1−cov)³ + cc` within
    rounding (parity check against the formula).
  - `npm run qa` runs the full TS chain in order and is green; `CLAUDE.md` records the commands.
  - Python QA chain stays green.
- **Depends on**: S2 (needs the vitest coverage JSON).

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

- **2026-07-25 — approach fixed with the user before planning**: incremental (pipeline + CRAP +
  one pilot now; module-by-module migration later), **npm** (not pnpm), **vitest** (its V8 coverage
  feeds CRAP). The `/dev:init typescript` scaffolder is for NEW projects; this retrofits the
  `typescript-dev:qa-toolchain` conventions onto the existing tree plus a custom CRAP script (the TS
  pack has prettier/eslint/tsc/vitest but NO CRAP metric).

- **2026-07-25 — pre-approval review (plan-critic), 3 blocking fixes:**
  1. **Four entry routers, not one.** `grep -rn "/static/js" apps/web` finds `ui`, `gallery`,
     `detail_preview`, `board_preview` — and `detail_preview.js`/`board_preview.js` import
     `../timescale.js` (transitively), so repointing only `ui` would 404 those preview pages. **Fix:**
     S1 repoints **all four** routers to `/static/dist/…` at once (consistent artifact path).
  2. **Assertion tests pin the script path.** `test_shell.py:39`, `test_design_system.py:237`,
     `test_gallery.py:112`, `test_board.py:45`, `test_detail_preview.py:43` assert the exact
     `/static/js/…` string, so "Python QA stays green" was unsatisfiable without editing them. **Fix:**
     those five tests are now in S1 Touches and move to `/static/dist/…` in lockstep.
  3. **Pilot `node --test` incoherence.** Renaming `timescale.js` → `.ts` in S1 orphaned
     `timescale.test.js` (imports `./timescale.js`), failing the `node --test` bridge. **Fix:** S1
     converts **no** file to `.ts`; the pilot module **and its test** convert together in S2 (module
     `.ts` + test → vitest), so no slice is ever red.
  Non-blocking, incorporated: eslint's cc lives in the rule **message string** (regex-parsed, not a
  JSON field); "parity" is **formula** parity, not metric parity (documented in Design); `pnpm` is
  also installed (npm still chosen). Suggestion adopted: repoint all routers from S1's start rather
  than a per-router migration window.

- **2026-07-25 — pre-approval review round 2 (plan-critic), 2 blocking fixes:**
  1. **`timescale` is not an isolable pilot.** The import graph (`grep -rln "timescale.js"
     --include='*.test.js'` → 6 suites: `gantt`, `board_gantt_align`, `honesty`, `cursor`,
     `detailpanel`, and `board` transitively) shows it is the most-imported module; renaming it `.ts`
     in S2 would red the `node --test` bridge. **Fix:** pilot is now **`urlstate`**, a verified true
     sink — importers are only `app.js` (loaded by no test) and its own test — so no remaining `.js`
     suite resolves it and runtime resolves it from `dist/`. (`timescale` migrates late, after its
     importers are TS.)
  2. **Whole-tree `prettier --check .` / `eslint .` fails on ~60 never-formatted legacy `.js`.**
     **Fix:** lint/format are **scoped to `**/*.ts`** during the migration window (`.prettierignore`
     + eslint ignores for legacy `.js`); each file joins as it converts. S2 acceptance updated.
  Suggestions adopted: `moduleResolution: "nodenext"` (not `bundler`). (A round-2 suggestion to
  repoint the `no-store` test to `/static/dist/app.js` was accepted here but **reversed in the round-3
  pass below** — it would 404 at test time.) Round 2 exhausts the plan-critic budget; those fixes are
  self-verified against the real import graph (pilot isolation proven) rather than re-reviewed.

- **2026-07-25 — extra adversarial pass (user-requested `dev:critic-reviewer` on the plan), 2 blocking
  fixes about the build artifact at test/CI time:**
  1. **The no-store test would 404.** Round 2's repoint of `test_gallery.py:70` to `/static/dist/app.js`
     was wrong: it live-fetches, and `dist/` is git-ignored/unbuilt at pytest time (`TestClient` uses
     `create_app()`, bypassing `main()`'s build preflight). **Fix:** the no-store test is **not**
     repointed — it keeps fetching existing source `/static/js/app.js` (`no-store` is mount-wide). Only
     the five script-tag **string** assertions repoint (no fetch), so `uv run pytest` needs **no build
     step**.
  2. **CI had no Node/npm**, so the vitest gate would be hollow and the build unexercised. **Fix:** the
     two QA chains are kept **separate and self-contained** — the Python chain (pytest + `node --test`,
     zero-npm) is unchanged; a new **`ts-qa` CI job** (`setup-node` + `npm ci` + `npm run qa`) runs the
     TS chain (build/type-check/lint/fmt/vitest/crap). Vitest is NOT bridged into pytest.
     `.github/workflows/qa.yml` added to S1/S2/S3 Touches.
  Suggestions adopted: `coverage-final.json` is **Istanbul-shaped** (not coverage.py's line sets) —
  S3/Design tightened; `test_design_system.py:219` added to the source-fetch-left-as-is note. The four
  earlier-verified claims (pilot isolation, `.js`-extension discipline, four routers, crap_ts input
  feasibility) were re-confirmed sound. This pass was beyond the plan-critic budget, at the user's
  request; fixes self-verified against `main.py` / `.gitignore` / `qa.yml`.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/typescript-migration.md`.
