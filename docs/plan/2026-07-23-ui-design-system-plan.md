---
type: plan
status: approved           # draft -> approved -> in-progress -> done
created: 2026-07-23
updated: 2026-07-23
feature: ui-design-system
branch: plan/ui-design-system
base_branch: main
gates:
  qa: full                # ruff, format, mypy strict, pytest+coverage floor, CRAP (Python side unchanged)
  review: adversarial     # critic subagent must find no blocking issues
pause_after: [S0, S3]     # S0 lands the token layer + component contract; S3 lands the crown-jewel board↔Gantt time-axis alignment (Risk #3) — both get human review before more is built on top
links: ["[[flowing-water-ui]]", "[[lane-plan-url-binding]]", "[[fastapi-service-integration]]", "[[gold-store]]"]
---

# Plan — Rebuild the swim UI from a typed design system: tokens → components → blocks

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
