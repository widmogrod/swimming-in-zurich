---
type: summary
feature: ui-design-system
status: done
created: 2026-07-23
links: ["[[flowing-water-ui]]", "[[fastapi-service-integration]]", "[[gold-store]]", "[[single-source-of-truth]]"]
---

# UI design system — the swim UI as tokens → components → blocks

**What & why.** The old `apps/web` UI was a single 1084-line HTML string in `api/ui/router.py` (four
disjoint tabs, competing visual languages) — "inconsistent and hard to navigate". A design
exploration converged on a **"flowing water" unified view** (two modes: Day · all pools /
Pool · the week, sharing a ribbon board + a lane-by-lane Gantt on ONE time axis). This rebuild
decomposes that into a **typed, layered, no-build design system** so the UI is maintainable.

## What exists now

**Layers** (strict — nothing reaches past its layer; grep-enforced):
`static/tokens.css` (the ONLY place raw colour lives) → `static/components.css` + JS factories →
`static/blocks.css` + block modules → the `_SHELL` served at `/`, hydrated by `static/js/app.js`.

- **Tokens** (`static/tokens.css`): colour (single accent; 4 never-merged availability states;
  `--badge-*` eligibility ✓/?/✕ muted, never alarm-red; `--lane-public/-res`; `--fam-*` access
  families incl. own `--women`), system-font scale, 8pt space, radii, `--shadow*`, `--ctl-h:36px`
  (every control), motion. Light + `@media(prefers-color-scheme:dark)` + `[data-theme]` overrides.
- **Primitives** (`static/js/components/*` + `_fakedom.js` headless test DOM): SegmentedControl,
  DateStepper, Combobox, PlaceTypeahead, ChipGroup, Toggle, StatePill, EligibilityBadge,
  LengthLanesBadge, ProvenanceStamp, IconSet. Token-only, `--ctl-h` tall, keyboard/ARIA-tested.
- **Blocks** (`static/js/blocks/*`): RibbonBoard (canvas water-ribbons; thickness = public/total,
  pinch on reserved, ghost = unknown, dashed = closed), LaneGantt, DetailPanel/BottomSheet,
  FilterToolbar, IdentityHeader, InsightBar, BoardLegend, StateBlocks.
- **Shared cores**: `timescale.js` (the ONE `X(min)` mapping — the anti-desync anchor both board and
  Gantt import), `cursor.js` (`publicAt`/`cursorX`), `eligibility.js` (`eligForAccess`/`dayEligibility`,
  mirrors the domain: School/Club→no, Women diverse/unset→chk), `filterstate.js`, `api.js`.
- **Serving**: `create_app()` in `main.py` mounts `StaticFiles` at `/static`; `/` returns `_SHELL`
  (charset + linked stylesheets + block mounts + `app.js` module) and still fails-fast on a missing
  gold DB. Dev-only `/ui/gallery`, `/ui/board`, `/ui/detail` gated by `SWIMZH_DEV_UI` (read only in
  `config.py`). No `apps/web/**` `.py` reads `data/` at runtime (grep-assert green).

## Load-bearing invariants (each test-guarded)

- **board↔Gantt alignment**: a click at time T lands both cursors on T's gridline and drives the
  board readout AND the panel headline from the SAME `publicAt(basin,T)`. `board_gantt_align.test.js`
  asserts `board.cursorX(T) === gantt.cursorPlotX(T)` under one injected `timescale` and DIVERGES under
  two — a self-derived scale fails. The panel headline is **cursor-driven, not peak** (below-peak-minute
  test).
- **honesty** (`honesty.test.js` + `test_honesty.py`): unknown(uncurated) ≠ closed; the three terminal
  states never merge; Busyness renders "not available yet" and is never faked; eligibility ? never
  merges with ✕. Provenance stamp + `valid_as_of` on every schedule; price null → "Not listed".
- **absolute dates** everywhere (no hardcoded "today"; UTC date math in `datestepper.js`, TZ-pinned test).

## Testing model

No JS test runner existed; JS is tested with Node's built-in `node --test` (zero-dep, headless via
`_fakedom.js`), **bridged into `uv run pytest`** by `apps/web/tests/test_static_js.py` so the QA gate
covers it. **Node is therefore a CI/gate dependency.** Overflow-containment and responsive/sheet
behaviour (no layout engine in the gate) are gated by **CSS-contract tests** that assert the
guaranteeing rules (`minmax(0,1fr)`, `overflow-x:auto`, the `@media` stack rules); the true visual
check is a human/browser step (done at the S3 pause + final `/` render).

## Known tech debt (small, logged in the plan Ledger)

- `lapOnly` emits `FilterState` but doesn't yet filter ribbons (no `/swim` lap param) — client-side
  filter deferred. `app.js` DOM wiring is browser-only (its pure helpers are unit-tested). A couple of
  `test_honesty.py` assertions check served-JS source strings, paired with the behavioural node tests.
  `--fam-*` hues are functional but a deeper palette polish is possible.

See `docs/plan/2026-07-23-ui-design-system-plan.md` (full design, Ledger, per-slice Decisions).
