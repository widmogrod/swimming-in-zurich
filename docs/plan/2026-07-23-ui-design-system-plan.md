---
type: plan
status: done               # draft -> approved -> in-progress -> done
created: 2026-07-23
updated: 2026-07-23
feature: ui-design-system
branch: plan/ui-design-system
worktree: .claude/worktrees/plan-ui-design-system   # S0 ran via main-checkout relocation; S1+ switched to a real git worktree per the user's request (verifying subagents honour it — see [[dev-implement-subagents-write-to-main-not-worktree]])
base_branch: feat/new-ui
gates:
  qa: full                # ruff, format, mypy strict, pytest+coverage floor, CRAP (Python side unchanged)
  review: adversarial     # critic subagent must find no blocking issues
pause_after: [S0, S3]     # S0 lands the token layer + component contract; S3 lands the crown-jewel board↔Gantt time-axis alignment (Risk #3) — both get human review before more is built on top
links: ["[[flowing-water-ui]]", "[[lane-plan-url-binding]]", "[[fastapi-service-integration]]", "[[gold-store]]"]
---

# Plan — Rebuild the swim UI from a typed design system: tokens → components → blocks

## Summary (done 2026-07-23)

The `apps/web` UI is now a **typed, layered, no-build design system** (tokens → components →
blocks → shell) replacing the 1084-line four-tab embedded string. `GET /` serves a small `_SHELL`
that links `/static/{tokens,components,blocks}.css` and hydrates one unified **two-mode** app
(Day · all pools / Pool · the week) from the JSON API, on the shared time axis. Delivered across
6 gated slices (S0 via main-checkout relocation; S1–S5 in a real git worktree — the prior
"subagents write to main" learning proved stale and is now corrected):

- **S0** token layer (`tokens.css`, light/dark/`[data-theme]`) + pure JS core (`timescale`,
  `filterstate`) + `node --test` bridged into pytest.
- **S1** 12 primitives (SegmentedControl, DateStepper, Combobox, PlaceTypeahead, ChipGroup,
  Toggle, StatePill, EligibilityBadge, LengthLanesBadge, ProvenanceStamp, IconSet) as token-only
  CSS + ES-module factories, tested headless via a hand-written `_fakedom.js`; dev `/ui/gallery`
  behind `SWIMZH_DEV_UI`; `StaticFiles` `/static` mount.
- **S2** the canvas **RibbonBoard** + shared `timescale` + pure `ribbonmodel` + shared
  `eligibility` rule.
- **S3** the **LaneGantt** + **DetailPanel/BottomSheet** on ONE shared cursor — the board↔Gantt
  alignment and the public-lanes-at-cursor (not peak) headline, both guarded by falsifiable tests.
- **S4** IdentityHeader + FilterToolbar (one `FilterState`) + InsightBar + BoardLegend + live
  `api.js`; `/` becomes the unified app; four-tab model retired.
- **S5** responsive toolbar breakpoints + `:focus-visible`; honesty-invariant test sweep
  (unknown≠closed, three states never merged, busyness "not available yet", ?≠✕); the direct
  board↔Gantt DOM-equality contract; **legacy `_PAGE` + injection machinery deleted**
  (`ui/router.py` 1148→60 lines).

Every honesty invariant is preserved and test-guarded; the shared `timescale` is the single
anti-desync anchor; no `apps/web/**` `.py` reads `data/` at runtime; QA green throughout
(final: pytest 394 passed, coverage 95.68% ≥ 95, CRAP clean; 142 node tests). See the Ledger and
`docs/summaries/ui-design-system.md`. Remaining tech debt is small and logged (client-side
lap-only filter; `app.js` DOM wiring browser-only; a couple of paired source-string tests).

## Context

The live UI is a single 1084-line HTML string embedded in `apps/web/api/ui/router.py` (four
disjoint tabs, competing visual languages, duplicated legends). It was flagged as "inconsistent
and hard to navigate." A multi-round design exploration converged on one prototype — the
**"flowing water" unified view** (`scratchpad/demo_unified.html`, published as an Artifact): one
app with **two modes** (Day · all pools / Pool · the week) that share a flowing-ribbon board, a
side detail panel, a lane-by-lane Gantt on **one shared time axis**, an Apple-class toolbar, and a
metro-style legend. It already honours every product invariant (busyness = future "not available
yet"; unknown ≠ closed; three never-merged terminal states; eligibility ✓/?/✕; length·lanes badge;
provenance; absolute dates).

The prototype is a **monolithic proof**, not a maintainable codebase: ~2000 lines of inline CSS +
JS + mock data, ad-hoc class names, no reuse boundary. This plan decomposes it into a **typed
design system** (tokens → primitive components → composite blocks) that the real `apps/web` UI can
be rewritten against — replacing the embedded string in `ui/router.py` with a small, layered,
still-**no-build / self-contained** front-end served over the gold DB.

Ground truth for every token/component below is the prototype's own CSS (`:root` custom
properties) and class inventory, and the real API surface (`/swim`, `/pools`, `/pools/{id}`,
`/access-types`). Nothing here invents data the store does not carry.

## Design (signature altitude)

**One token layer is the single source of visual truth; components consume tokens only; blocks
compose components only; the page composes blocks only.** No component reaches past its layer:

```
tokens.css        →  --color/--type/--space/--radius/--shadow/--motion  (light + dark)
components.css    →  primitives, styled purely through tokens (no raw hex, no magic px)
blocks.css        →  composites, layout of primitives (no new color, no raw hex)
app shell (HTML)  →  server-rendered skeleton; JS hydrates blocks from the JSON API
```

**Stay no-build and self-contained** (the project's standing ethos + the grep-asserted "no
`apps/web/**` reads `data/` at runtime"). We modularize *without* a bundler: static CSS files +
native ES modules under `apps/web/static/`, assembled by a thin server shell. If a build step is
ever wanted it can wrap this later, but the layering must not depend on one.

**The shared time-scale is a first-class module, not a coincidence.** The prototype's key
correctness property — a click at time *T* lands on the same x in the ribbon *and* the lane Gantt —
comes from one mapping `X(min) = (min − DAY0·60)/SPAN · PLOT`. In the rewrite this is a single
exported util (`timescale.js`) that both the board renderer and the Gantt renderer import. It is
the anti-regression anchor for the whole board.

---

## Part 1 — Design System (tokens)

Extracted verbatim from the prototype; promoted into `apps/web/static/tokens.css`. Every value is
a CSS custom property on `:root`, re-declared under `@media (prefers-color-scheme: dark)` **and**
`:root[data-theme="dark"|"light"]` (viewer toggle wins both directions).

### 1.1 Color
| Group | Tokens (light → dark) | Use |
|---|---|---|
| Ground | `--bg` #eef2f3→#0d1418 · `--surface` #fff→#111c22 · `--surface-2` #f6f9fa→#0f191e | page / card / inset |
| Ink | `--ink` #15242c→#e7eef1 · `--ink-2` · `--muted` · `--faint` | text ramp (4 steps) |
| Hairline | `--hair` · `--hair-2` | 1px borders / dividers only |
| Accent (single) | `--accent` #0e8ea0→#3fc2d4 · `--accent-ink` | interactive chrome, focus, links |
| Semantic — availability | `--accent`=open · `--best`/`--cursor` #0a84ff=opens-later/now · `--closed` #b0563f=closed-with-reason · `--unknown` #8a99a2=hours-not-listed | the 4 never-merged states |
| Eligibility | in #1a9d54 · check #b7791f · not-for-you #8a909c | ✓ / ? / ✕ — muted grey, **never alarm red**, ? never merged with ✕ |
| Lane split | `--lane-public-fill/-edge/-ink` (aqua = open to you) · `--lane-res-fill/-edge/-ink` (grey = held, owner named) | ribbon + Gantt |
| Support | `--chip` · `--envfill` (capacity sheath) · `--track` | chips / ghost / rails |

Discipline: **one saturated accent** repeats; every other hue is semantic and appears once.
In-fill text always uses the paired `-ink` token on its own tint (WCAG AA ≥4.5:1, dark inks
lightened). Lane state must not rely on hue alone — pair with label/owner text (CVD-safe).

### 1.2 Typography
`--f: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif`
(system stack — no webfont, so no CDN/CSP risk). Scale (from prototype, promote to `--fs-*`):

| Role | size / weight | Use |
|---|---|---|
| Title | 25 / 680 | screen H1 |
| Basin/headline | 19 / 660 | detail header, hero value |
| Body | 13.5–14 / 560 | controls, row labels |
| Caption | 11–12.5 / 600 | eyebrows (uppercase, +.06em), sub-lines |
| Micro | 10–10.5 | axis ticks, in-cell labels |

`font-variant-numeric: tabular-nums` (token `.tnum`) wherever times/counts align.

### 1.3 Spacing / radius / shadow / motion
- Space (8pt + 4px half-step): `--s1:4 --s2:8 --s3:12 --s4:16 --s5:24 --s6:32`.
- Radius: promote to `--r-sm:8 --r-md:10 --r-lg:16 --r-xl:18 --r-pill:999`.
- Shadow: `--shadow` (resting/card) · `--shadow-lg` (sheet/popover).
- **Control height**: `--ctl-h:36px` — the fix that made SWIMMER/AGE/DATE/PLACE align. Every
  interactive primitive is exactly `--ctl-h`.
- Motion: `.24–.28s cubic-bezier(.32,.72,0,1)` for the sheet; ribbon water animation on
  `requestAnimationFrame`. **All motion gated by `prefers-reduced-motion`** (freeze water, no
  slide).

### 1.4 Theming contract
`color-scheme: light dark` on `:root`; media query is the default signal; `[data-theme]` overrides
both ways. Components never hard-code a theme; they read tokens only. (One historical footgun:
missing `<meta charset="utf-8">` caused mojibake — the shell must declare it.)

---

## Part 2 — Primitive components

Each ships as `components.css` rules + (where interactive) one ES module exporting a factory
`create<Name>(el, {props, onChange})`. All are token-only, `--ctl-h` tall, keyboard-accessible,
theme-aware, and have explicit empty/disabled states.

| Component | Prototype origin | Variants / props | State it binds | A11y |
|---|---|---|---|---|
| **SegmentedControl** | `.seg`, `.modeseg` | items[], selected; `mode` variant (accent-ink) | view mode / gender | `role=group`, `aria-pressed`, arrow keys |
| **DateStepper** | `.datenav` | value(date), min/max; `todaytag` | selected day (absolute) | ‹/› buttons labelled, tabular label |
| **Combobox (searchable)** | `.combo*` | options[], value, filterFn; closed-badge | pool selection | listbox, type-filter, ↑↓/Enter/Esc |
| **PlaceTypeahead** | `.combo-input`+`.combo-pop` | presets[], "use my location" | place → lat/lon | select-on-focus, geolocation fallback |
| **ChipGroup** | `.seg.agechips` | items[] with representative value | age range | `role=group`, `aria-pressed` |
| **Toggle** | `.toggle`, `.sw` | checked, disabled+reason | lap-only / busyness(disabled) | native checkbox, visible focus |
| **StatePill** | `.pill` (open/sched/closed/unknown) | one of 4 availability states | day/session state | dot + word, never opacity-only |
| **EligibilityBadge** | `.elig`, `.eligtag` | in/chk/no; inline vs board-tag | ✓/?/✕ per session/row | title = reason; ? distinct from ✕ |
| **LengthLanesBadge** | `.badge` | length_m, lanes; degrade to "Teaching pool" | basin physicals | plain text, no faked N |
| **ProvenanceStamp** | `.prov`, `.illus` | source, valid_as_of, curated/illustrative | schedule trust | calm, one line |
| **Sheath/Ribbon tokens** | `.cellcanvas` fills | public/reserved/ghost/closed | lane split over time | (canvas; described in Part 3) |
| **IconSet** | inline SVG glyphs | wave/family/person/lock/water-drop | access families | `aria-hidden`, label carries meaning |

Retire the monospace glyph soup (`≈◇⌂WSX·`, `✓✗?`): access → plain word + one 12–13px line icon;
eligibility → EligibilityBadge word + colour.

---

## Part 3 — Blocks (composites)

Each block = a folder-level unit: `blocks.css` section + one ES module owning its DOM subtree and
its data fetch/derive. Blocks import primitives and the timescale util; they never define color.

1. **IdentityHeader** (`header.top`, `.brand`, `.datebox`) — logo/title + absolute date/week +
   theme toggle. Left-aligns and stacks on mobile.
2. **FilterToolbar** (`.toolbar`) — the global context spine: SegmentedControl(mode) + DateStepper
   (Day) / Combobox(pool) (Pool) + PlaceTypeahead + SegmentedControl(gender) + ChipGroup(age) +
   Toggle(lap) + Toggle(busyness, disabled). Emits one `FilterState`; drives every other block.
3. **InsightBar** (`.insight`) — mode-aware summary ("5 pools with curated hours nearby… best
   window 8/8 at Oerlikon 09:30–10:00" / "reliable public lanes around …").
4. **RibbonBoard** (`.stage`→`.boardcol`→`.boardcard`→`.grid` + `.cellcanvas`) — the hero. Sticky
   `RowLabel` column (pool/day + status dot + EligibilityBadge) × a horizontal-scroll canvas of
   flowing water-ribbons (thickness = public lanes, pinch on reserved, capacity sheath, ghost =
   unknown, dashed = closed) + the shared time cursor. Renderer split: `axis`, `rowlabel`,
   `ribbon` (canvas), `cursor`. Consumes `timescale`.
5. **LaneGantt** (`.gantt*`, `.gscroll`, `.gcursor`) — per-basin lane-by-lane plan on the **same
   timescale**: best-public band, per-lane public/reserved-with-owner segments, cursor synced to
   the board, live "T · N of M lanes public" readout.
6. **DetailPanel / BottomSheet** (`.detailcol`, `.detail`, `.fact(s)`, `.backdrop`) — facts block
   (StatePill, Public-lanes-at-cursor, LengthLanesBadge, distance, price, temp, EligibilityBadge,
   Busyness=future, Freshness) + LaneGantt + ProvenanceStamp. Sticky side panel ≥1060px; slide-up
   sheet + backdrop < 1060px.
7. **BoardLegend** (`.legend`, `.legrid`, `.glegend`) — metro-style: session-type swatches, the
   three terminal states, eligibility key, and the honesty note.
8. **StateBlocks** — closed-with-reason / hours-not-listed / no-pools empty states, each visually
   distinct (never a blank that reads as closed).

---

## Part 4 — Data → component mapping (no invented fields)

| API field | Component/block |
|---|---|
| `at`, place presets, `gender`, `age`, `radius_km`, `eligible_only` | FilterToolbar |
| `facility/_id`, `kind`, `basin`, `distance_km` | RowLabel, DetailPanel |
| `start`/`end`, `access`, `open_now` | RibbonBoard segments, StatePill |
| `lane_availability`, `lane_timeline.segments` (public/reserved/lane_count) | Ribbon thickness, Public-lanes-at-cursor, LaneGantt |
| `/pools/{id}` `lane_panels[].panel.day_view.strips[].segments[].owner` | LaneGantt per-lane |
| `length_m`, `lanes` | LengthLanesBadge |
| `price`, basin `nominal/measured_temp_c` (+ `physical_source`) | DetailPanel facts (null → "Not listed") |
| `eligible`+`reason` (derived from `access`×gender/age) | EligibilityBadge |
| `curated`, `source`, `valid_as_of` | ProvenanceStamp |
| `statuses` (closed/uncurated + detail) | StateBlocks, ghost/closed ribbons |
| **busyness / occupancy** | **NONE — render "not available yet" only. Never faked.** |

---

## Part 5 — Rewrite architecture (apps/web)

- **Files** (new, static, no-build): `apps/web/static/tokens.css`, `components.css`, `blocks.css`,
  `js/{timescale,filterstate,api,board,gantt,panel,toolbar,legend}.js` (native ES modules).
- **Shell**: `ui/router.py` returns a *small* HTML skeleton (`<meta charset>`, token/CSS links,
  block mount-points, `<script type="module" src=…>`) instead of a 1084-line string. It still
  serves nothing from `data/` — the grep-assert test
  (`apps/web/tests/api/test_single_source_of_truth.py::test_no_app_module_reads_curated_data_at_runtime`,
  which scans `.py` files only) stays green, and static CSS/JS under `apps/web/static/` cannot trip
  it.
- **Static serving is NET-NEW infrastructure** (today everything is inlined; there is no
  `StaticFiles` mount or `/static` anywhere in `apps/web`). This plan adds a `StaticFiles` mount at
  `/static` in the composition root serving `apps/web/static/`. Routes after this change: `/` (the
  shell), the existing JSON endpoints, `/static/*` (the new mount), and the **dev-only**
  `/ui/gallery`. Because a FastAPI route is always mounted once registered, `/ui/gallery` is
  registered **conditionally on a config flag** (`SWIMZH_DEV_UI`, read only in `config.py` per the
  fastapi-service convention) so it is absent in production.
- **Data**: JS hydrates blocks from the existing JSON endpoints (`/swim`, `/pools`, `/pools/{id}`,
  `/access-types`). No new endpoints required for parity; a future `/swim?week=` batch is optional
  (today the Pool mode assembles 7 calls, as the current planner does).
- **Follows** `python-dev:fastapi-service` conventions; deviations recorded in
  `docs/concepts/fastapi-service-integration.md`.
- **Testing**: keep the grep-assert (no `data/` at runtime). Add: a component-gallery route
  (`/ui/gallery`, dev-only) rendering every primitive/state for visual review; a small
  DOM-contract test that the shared `timescale` maps identically in board and Gantt (guards the
  alignment invariant). Playwright/visual-regression noted as future, not required for parity.

---

## Slices (vertical, each shippable & reviewable)

- **S0 — Token layer + component contract** *(pause here)*. Extract `tokens.css` (light+dark, the
  full table in Part 1) and the empty `components.css`/`blocks.css` layer files + the `timescale`
  and `filterstate` modules. Re-skin the *current* embedded UI to consume tokens (see Decisions —
  throwaway proof that the token set is complete). **Accept (mechanical):** the `_PAGE` HTML
  *structure* is unchanged — the diff touches only `<style>` contents / color literals, now
  `var(--…)` (no changes to tags/attributes outside `style`); `grep -nE '#[0-9a-fA-F]{3,8}|rgba\('`
  finds **zero** raw color literals outside `tokens.css`; `timescale` has a unit test (X(min) is
  monotonic and hits the exact endpoints at DAY0/DAY1) and `filterstate` has a unit test
  (merge + serialise/deserialise round-trip); QA green. *Human step at the pause:* screenshot
  review confirms visual equivalence (there is no automated visual-regression gate — see Decisions).
- **S1 — Primitives + gallery**. Build every Part-2 component as an isolated module + `components.css`
  section; add the dev `/ui/gallery` route rendering each with all states (incl. empty/disabled,
  light+dark). **Accept (mechanical):** the gallery route renders every Part-2 primitive in each
  documented state in both themes; a DOM test asserts each interactive primitive exposes its
  documented ARIA on the gallery DOM (`role`, and the right `aria-pressed`/`aria-selected`/
  `aria-disabled`) — axe-core or explicit attribute assertions; unit tests cover the key handlers
  (SegmentedControl/ChipGroup arrow-keys; Combobox ↑↓/Enter/Esc + type-filter; PlaceTypeahead
  select-on-focus + geolocation-fallback path); a grep asserts no `blocks/` import inside
  `components/` (layer rule).
- **S2 — RibbonBoard + timescale**. The canvas board block (axis, sticky RowLabel, ribbon renderer,
  cursor) driven by FilterState, consuming `timescale`. **Accept (mechanical):** against saved
  `/swim` fixtures, pure-JS unit tests assert the segment→render-state mapping (the pure logic
  isolated per Risk #2): `statuses[].status=="closed"` → dashed closed ribbon carrying `detail`;
  `status=="uncurated"` → dotted ghost ribbon; an option with `lane_timeline` → filled ribbon whose
  thickness = `public_lanes/lane_count` and pinches where `reserved_lanes>0`; an option lacking
  `lane_timeline` → "lane split not published" ribbon; `eligForAccess(access,gender,age)` ∈
  {in,chk,no} per the shared rule (women-only→male=no; adults-only<18=no; ?≠✕). Day + Pool modes
  render from those fixtures; a DOM test asserts the board's `.scrollx.scrollWidth > clientWidth`
  **while** `document.documentElement.scrollWidth == clientWidth` (contained, no page overflow);
  reduced-motion freezes the water RAF.
- **S3 — LaneGantt + DetailPanel/Sheet**. Per-basin Gantt on the shared axis, cursor-synced to the
  board; facts block with Public-lanes-**at-cursor** (not peak); bottom-sheet <1060px. **Accept:**
  click at T aligns Gantt cursor to T's gridline and both readouts match; owner names from
  `/pools/{id}`; provenance present.
- **S4 — Toolbar + Header + InsightBar + Legend; wire it together**. Compose the full page; retire
  the four-tab model. **Accept:** mode switch, date stepper, pool combobox, place typeahead +
  geolocation fallback, gender/age eligibility badges, lap-only — all live; absolute dates
  everywhere.
- **S5 — Responsive, a11y, honesty tests; retire the old string**. Phone breakpoints (stacked
  full-width toolbar, sheet), focus states, the timescale DOM-contract test, and the invariant
  checks (unknown≠closed, three states never merged, busyness "not available yet", ? never merged
  with ✕). Delete the legacy embedded HTML. **Accept:** full QA + adversarial review; old UI gone.

---

## Decisions

- **S0 re-skins the doomed embedded string** (which S5 deletes) to prove token completeness, even
  though S1's gallery also proves it. Kept deliberately: the re-skin is a *throwaway* proof that
  exercises the token set against real, dense, already-shipping markup **before any component
  exists**, catching missing tokens at S0 rather than after the gallery is built. Cost: one
  throwaway diff, reverted implicitly by S5. Alternative (gallery-only proof, no re-skin) was
  rejected because it would leave the S0 pause with nothing observable but a stylesheet.
- **Two human-review pauses (S0, S3), not one.** S0 gates the token layer + module contract; S3
  gates the board↔Gantt shared-time-axis alignment (Risk #3) — the single hardest correctness
  property — before S4 composes the full page on top.
- **No automated visual-regression gate** (Playwright/screenshot-diff) in this plan. Visual
  equivalence at S0 and look-and-feel at S4/S5 are confirmed by human screenshot review at the
  pauses. A visual-regression harness is a possible follow-up, explicitly out of scope here to
  avoid net-new CI infrastructure.
- **`filterstate.js` is authored in S0 but first *observed* in S2/S4.** To avoid shipping an
  unverified module at S0, its S0 acceptance includes a merge + round-trip unit test (above).

### Implementation decisions & divergences — S0 (2026-07-23)

- **Ambiguity #1 resolved → server-side token injection (Option a).** `ui/router.py` reads
  `apps/web/static/tokens.css` at import and inlines it into the page's single `<style>` via a
  `/* __TOKENS__ */` marker. Zero structural HTML change; reading a `static/` asset at runtime does
  not trip `test_no_app_module_reads_curated_data_at_runtime` (it scans `.py` only, for `data/`
  inputs). The `StaticFiles` mount + `<link>` stays deferred to the slice that adds `<link>`-served
  assets. Confirmed net-new: S0 needs no mount.
- **Ambiguity #2 resolved → `node --test` bridged into pytest.** JS unit tests live at
  `apps/web/static/js/*.test.js` (+ `package.json` `{"type":"module"}` so node & the browser agree
  on ESM); `apps/web/tests/test_static_js.py` shells out to `node --test` so `uv run pytest` / the
  QA gate cover them (7/7 pass). **Node is now a QA-gate dependency** — the bridge `skipif`s when
  node is absent, so CI must provision Node or the JS tests silently skip (carry into S1+/CI setup).
  Node 26 quirk: `node --test <dir>` positional fails `MODULE_NOT_FOUND`; run `node --test` with
  `cwd` set to the js dir (bridge already does this; reuse in S1+).
- **Divergence (ratified): ruff per-file-ignore.** Added `"apps/web/tests/test_static_js.py" =
  ["S603"]` to `[tool.ruff.lint.per-file-ignores]`. Critic-adjudicated legitimate and minimally
  scoped (S603 only, not S607, because `shutil.which("node")` returns an absolute path): pinned
  binary, fixed args, no shell, no untrusted input — mirrors the existing `scripts/** =
  ["S603","S607"]` precedent. **Orchestrator ratified.**
- **Compat tokens are throwaway.** To keep S0 visually equivalent (the human screenshot gate),
  `tokens.css` carries a clearly-commented "S0 re-skin compatibility tokens … retired at S5" block
  reproducing the *legacy* palette (`--tint-*`, `--link`, `--elig-*`, `--sched`, `--good/warn/temp-*`)
  rather than re-colouring the UI to the prototype palette now. **Carry to S1/S5:** the names
  `--elig-in/-out/-unk` are claimed here with the legacy alarm-red `#b91c1c`; S1's real
  EligibilityBadge wants the muted Part-1 values (`#1a9d54`/`#b7791f`/`#8a909c`) — S5 retirement must
  swap the *values* under those names.
- **Critic nit (carry):** the `str.replace` injection silently no-ops if the `/* __TOKENS__ */`
  marker is ever removed (all `var(--…)` would break) with no test guarding a token *definition* in
  the rendered page — S1 should add that assertion or make a missing marker raise. **[done in S1:
  the router now RAISES on a missing marker, + `test_index_page_carries_an_injected_token_definition`.]**

### Implementation decisions & divergences — S1 (2026-07-23)

- **Worktree isolation now works.** S1 ran in a real git worktree (`.claude/worktrees/plan-ui-design-system`)
  per the user's request; verified the slice-implementer wrote only into the worktree, main checkout
  stayed clean. The prior learning ([[dev-implement-subagents-write-to-main-not-worktree]]) is **stale**
  as of 2026-07-23 — the tooling was fixed. S0 was done via main-checkout relocation; S1+ via worktree.
- **ARIA/DOM/key testing with zero JS-DOM deps → hand-written `_fakedom.js`.** Factories derive their
  document from `el.ownerDocument` (fallback `globalThis.document`); tests pass a minimal
  `FakeDocument`/`FakeElement` that backs `setAttribute`/`getAttribute`/`addEventListener`/`dispatch`
  with a real map and invokes handlers with a synthetic event — so a genuine ARIA/key regression fails
  a test (critic-verified non-tautological). Key-nav is also factored into pure `keynav.js`. No jsdom,
  no npm deps. Gallery renders client-side; its mount×state×theme structure is asserted server-side.
- **`--elig-*` collision resolved → new `--badge-in/-chk/-no`** carry the muted Part-1 values
  (`#1a9d54`/`#b7791f`/`#8a909c`); the S0 throwaway `--elig-*` (alarm-red) is left for S5 to retire.
- **Divergence (accepted): `create_app()` factory** in `main.py` (Design showed a module-level `app`).
  Needed to conditionally register the dev route per flag and keep it per-flag testable; `app =
  create_app()` preserves the ASGI entrypoint and still fails-fast on a missing gold DB (critic-verified).
- **Divergence (accepted): broadened `tokens.css` theme selectors** to also match `[data-theme=…]`
  (not only `:root[…]`) — additive, values unchanged, enables the gallery's simultaneous light+dark panels.
- **`StaticFiles` mount at `/static`** added (net-new infra per Part 5); serves `apps/web/static/` only
  (css/js; no data/secrets — critic-verified). Dev-only `/ui/gallery` gated by `SWIMZH_DEV_UI` (read only
  in `config.py`); absent (404) when off.
- **Carry to later slices (critic nits, non-blocking):** (1) cross-check Python `_COMPONENTS` against JS
  `REGISTRY` from one source; (2) pin a negative-offset TZ in the datestepper test; (3) extend the
  hex-grep to scan the gallery router's inline `<style>`. Real bug fixed in S1: `datestepper.js` date
  math via `Date.UTC` (not `toISOString()` on a local date) — reuse the UTC-parse pattern in the S2/S3
  board/gantt date utils.

### Implementation decisions & divergences — S2 (2026-07-23)

- **Shared timescale is genuinely the single scale.** `board.js` routes every plot-x through the S0
  `timescale.X(...)` and accepts an injected `opts.timescale` instance so S3's Gantt passes the SAME
  object — critic-verified no local minute→pixel math. This is the anti-desync anchor for the S3 pause.
- **`eligForAccess` mirrors the domain, not the prompt's literal "else in."** `SchoolReserved`/
  `ClubReserved` → `no` (domain `access.py` returns `allowed=False`); `WomenOnly` diverse/unset → `chk`
  (domain says "confirm with venue") — honours the `?≠✕` invariant. Public/Lane/Family/unknown → `in`.
  One shared `eligibility.js` now; S3 panel + S4 toolbar MUST reuse it (do not re-parse `access`).
- **Overflow-containment gated by a CSS-contract test** (no layout engine in the gate): asserts the
  board grid column is `minmax(0,1fr)` (and a bare `1fr` is absent), scroll cell `overflow-x:auto`,
  track `width:max-content`. Would fail on a revert to the page-overflow bug. The true visual/browser
  check is the human step at the S3 pause.
- **Divergence (accepted): `--fam-*` access-family tokens** — 12 `var()` aliases over the existing
  palette (no raw hex, single `:root` decl); provisional hues (esp. `--fam-women: var(--closed)` reuses
  red) flagged for the S5 palette pass. The ribbon fill (hue) is a separate channel from the
  EligibilityBadge (`--badge-*` grey) so no eligibility/availability invariant is merged now.
- **Divergence (accepted): dev `/ui/board` route** (own package) under the existing `SWIMZH_DEV_UI`
  flag; row status shown as a compact dot (not `StatePill`, which stays for S3's panel).
- **Carry to S3 (critic nits + tech debt):** wire the shared horizontal scroll + time cursor across
  rows and into the Gantt (the alignment work); drop `board.js`'s inline 900px track width so
  `max-content` governs (or record the fixed-plot intent); reuse `accessFamily`/`eligForAccess` and the
  UTC date pattern.

### Implementation decisions & divergences — S3 (2026-07-23)

- **The alignment is guaranteed by two falsifiable tests** (critic-confirmed at the S3 pause):
  (a) a gantt-local-scale regression fails — `gantt.js` throws without an injected `timescale`, and a
  two-scale test (PLOT 900 vs 500) asserts different cursor-x so an internal fixed scale can't pass;
  (b) a peak-driven-headline regression fails — the panel headline + lit pips are asserted at a
  below-peak minute (T where `publicAt`=5 vs peak 8) against the real fixture. The shared pure
  `cursor.js` (`publicAt`/`cursorX`) is the single source both the board readout and the panel headline
  consume.
- **Divergence (accepted): net-new `blocks/cursor.js`** (Part 5 lumped this under gantt/panel) — the
  pure `publicAt`/`cursorX` leaf, extracted for dependency-free testability. `blocks/detailpanel.js`
  (Part 5 named it `panel.js`) — naming only.
- **Divergence (accepted): dev `/ui/detail` route** (own package) rather than extending `/ui/board`;
  gated by `SWIMZH_DEV_UI`.
- **Facts-block honesty preserved** (critic-verified): Busyness → "Not available yet"; price null →
  "Not listed"; temp with nominal/measured note; provenance stamp present; eligibility via shared
  `eligibility.js`.
- **Carry to S4/S5:** on a LIVE board→panel click, the selected board row (`/swim` `lane_timeline`
  aggregate) must resolve to the SAME basin's `/pools/{id}` `day_view` (per-lane) so "board readout ==
  panel headline" holds on real data. S5 owns the direct board↔gantt DOM-equality contract test and
  consolidating the duplicated `hhmmToMin`.

### Implementation decisions & divergences — S4 (2026-07-23)

- **`/` now serves the unified two-mode app** (`_SHELL`: charset + linked `/static` stylesheets +
  block mounts + `<script type=module src=/static/js/app.js>`). The four-tab model is retired
  (`data-tab=` absent from live `/`, asserted). One `FilterState` (S0 `filterstate.js`) drives every
  block; `app.js` wires FilterState→refetch/rerender, a board→panel click resolving to the SAME
  basin's `/pools/{id}` day_view via the shared `timescale`/`cursor` (S3 identity, critic-verified);
  absolute dates only (no "today" literal).
- **Divergence (accepted): legacy `_PAGE`/`_RENDERED_PAGE` kept as DEAD code** (unserved) so the diff
  stays reviewable and S5 owns the removal. ~45 legacy `/`-content tests were retargeted to read
  `_RENDERED_PAGE` directly (critic-verified: not coverage-masking — the live invariants are covered
  by the 128 node block/component tests + `test_shell.py`). **S5 deletes `_PAGE`, `_RENDERED_PAGE`,
  the `_TOKENS_CSS`/marker injection machinery, `test_ui.py`, and the retargeted design-system check.**
- **Fail-fast preserved** (critic-verified): startup still raises on a missing/empty gold DB; the
  static shell doesn't bypass it (`/` never serves without a DB).
- **Carry to S5 (critic nits + tech debt):** `openPanel` currently takes `lane_panels[0]` — on a
  multi-basin facility this may not be the clicked row's basin; confirm the board↔panel basin
  identity in S5's invariant sweep. Toolbar double-mount → an in-place `setPools()`. `lapOnly` emits
  state but doesn't yet filter ribbons (no `/swim` lap param — client-side filter deferred).

## Risks & mitigations

1. **No-build modularity drift** — without a bundler, import graphs can rot. *Mitigate:* flat
   `static/js` with explicit imports; the layer rule (tokens→components→blocks→shell) is lint-checkable
   by a grep test (no hex outside tokens; no cross-layer import).
2. **Canvas testability** — ribbons are drawn, not DOM. *Mitigate:* keep all *logic* (segment→public
   count, timescale, eligibility) in pure JS modules unit-testable without canvas; the canvas is a
   thin draw layer.
3. **Time-axis coupling regressions** — the alignment is the crown jewel. *Mitigate:* single
   `timescale` module + the S5 DOM-contract test asserting board-x == gantt-x for sampled minutes.
4. **Honesty invariants eroding under refactor** — *Mitigate:* S5 invariant tests are gates, not
   nice-to-haves; ProvenanceStamp/StateBlocks/Busyness-future are components, so they can't be
   silently dropped.
5. **Scope** — this is a UI rewrite, not a data change; the Python domain/gold store is untouched.
   Keep the diff inside `apps/web/**` + `docs/**`.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|---|---|---|---|---|---|
| 2026-07-23 | S0 | done | server-side token injection (Option a); `node --test` bridged into pytest; ruff S603 per-file-ignore added & ratified | throwaway compat tokens in `tokens.css` (retired at S5); `--elig-*` value-collision to fix at S5; token-injection has no marker-present test (add S1); Node is a CI/gate dependency | yes |
| 2026-07-23 | S1 | done | `create_app()` factory (composition root) for per-flag route registration; headless `_fakedom.js` for zero-dep JS DOM/ARIA tests; real `--badge-in/-chk/-no` eligibility tokens (collision avoided, S0 compat block untouched); broadened `tokens.css` `[data-theme]` selectors (additive) | Python `_COMPONENTS` vs JS `REGISTRY` are two hand-kept lists, only JS-side agreement pinned; datestepper test doesn't pin process TZ; hex-grep doesn't scan the gallery router's inline `<style>` | yes |
| 2026-07-23 | S2 | done | shared `timescale.js` consumed by the board (critic-verified, no re-derive); pure `ribbonmodel.js` mapping; shared `eligibility.js` (School/Club→no, mirrors domain; WomenOnly diverse/unset→chk); `--fam-*` access-family token aliases; dev `/ui/board` route; overflow-containment via CSS-contract test | per-row `.board__scrollx` not yet scroll-synced (S3 does shared scroll + time cursor); `board.js` inline `track.style.width=900px` overrides the `max-content` CSS the contract test asserts; `--fam-women` reuses closed-red hue (S5 palette polish); canvas pixel output unverified until browser check | yes |
| 2026-07-23 | S3 | done | net-new pure `blocks/cursor.js` (`publicAt`/`cursorX` leaf); `blocks/detailpanel.js` (plan named it `panel.js`); dev `/ui/detail` route; alignment proven by cursor-x equality (two-scale non-tautology) + below-peak readout tests (critic-confirmed both regressions caught) | `cursor.js` duplicates board's 2-line `hhmmToMin` (drift surface, consolidate later); `board.js` inline 900px track width left (redundant == intrinsic, S2 carry); direct board↔gantt DOM-equality contract deferred to S5 (Risk #3); `pool_oerlikon.json` carries full 87-entry roster (unused) | yes |
| 2026-07-23 | S4 | done | new `_SHELL` served at `/` (four-tab model retired; legacy `_PAGE` kept as dead code for S5); one `FilterState` drives every block; live `api.js` (Day + 7-call week + `/pools/{id}`); S3 board→panel identity wired via shared `timescale`/`cursor`; absolute dates (no "today" literal) | ~45 legacy `/`-content tests retargeted to read the dead `_RENDERED_PAGE` string (S5 deletes both + the token-injection machinery); toolbar double-mount after `/pools` resolves; lap-only emits `FilterState` but doesn't filter ribbons yet (no `/swim` lap param); `openPanel` takes `lane_panels[0]` — multi-basin basin-identity to confirm in S5 | yes |
| 2026-07-23 | S5 | done | legacy `_PAGE`/`_RENDERED_PAGE`/token-injection + `test_ui.py` DELETED (router 1148→60 lines); S0 compat tokens retired (`--fam-women` given own `--women` hue); responsive toolbar breakpoints + `:focus-visible` (fixed a broken theme-toggle focus ring); honesty-invariant sweep (node + Python); board↔gantt DOM-equality contract test (falsifiable); all F nits landed (openPanel per-basin, dropped inline track width, consolidated hhmmToMin, TZ-pinned datestepper test, gallery inline-style hex-grep, Python↔JS component cross-check) | stale comment in `tokens.css` referencing the now-deleted compat block; `test_honesty.py` asserts served-JS source strings (paired with node behavioural tests) | no |
