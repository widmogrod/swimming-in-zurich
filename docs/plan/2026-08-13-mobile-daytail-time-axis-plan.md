---
type: plan
status: in-progress      # draft -> approved -> in-progress -> done
created: 2026-08-13
feature: mobile-daytail-time-axis
branch: plan/mobile-daytail-time-axis
worktree: .claude/worktrees/plan-mobile-daytail-time-axis
base_branch: main
gates:
  qa: full               # BOTH chains: `uv run` python chain AND `npm --prefix apps/web/static/js run qa`
  review: adversarial    # critic subagent must find no blocking issues
  max_rounds: 2          # revise/retry rounds per gate before a slice is blocked
pause_after: ["S1", "S3"] # both change layout in ways no test can see — eyeball them in the app
links: ["[[day-tail-time-axis]]"]
---

# Mobile day tail — a per-card time axis (variant B)

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-13**

> in mobile view swimlines don't have time information so I don't know what availability is on which hour; explain me what you understand

> propose few ui variants and show me preview to choose from

> but for Hallenbad City · Schwimmerbecken time is not visible because of swimlines there

> prepare new variant

> Ruler, hailines, nowrecommended
> looks also nice, will ruler be sticky and look good on mobile devices with a notch?

> so i'm interested in refining those two options i mention

> I choose "Ticks in every tail"

> show me how it will look on real data, in list and expanded

> before making changes

> looks good, bu t one thing related to UX/ expanding card works when taping only on title but not swiming lines, and natural thing for me is to click on swimmign lines

## Context

The phone list (`blocks/poollist.ts`) ends every card with a "day tail" — the shared ribbon
renderer squeezed into the card's width by `blocks/daytail.ts`. Horizontal position encodes time
across a fixed `[06:00, 22:30]` window, but the tail is deliberately axis-less: its module header
says "ribbonrender.ts with a COMPRESSED timescale and no axis". On the desktop board that is
correct, because `board.ts::drawAxis` paints one shared hour header above every row. The phone has
no such header — `blocks/phonebar.ts` carries the *date*, never the *hours* — so a bar's position
is unreadable. The expanded state never had this problem: `blocks/gantt.ts:188-198` builds a
`.gantt__axis` with an `HH:00` tick every two hours.

Five treatments were mocked against a live `/swim` response and the owner chose **variant B —
ticks in every tail**: hour labels in a DOM strip per card, hour marks inside the canvas, no shared
chrome and nothing pinned. Two defects surfaced while mocking and are folded in, because both sit
under the axis work: the ribbon is not a tap target, and the "now" cursor disappears when now falls
outside the tail's window. Builds on [[day-tail-time-axis]].

## Design (signature altitude)

### Why the labels are DOM and the marks are canvas

A lane-stack ribbon fills `STACK_BOX = 0.8` of the row's 46px (a module-private const at
`ribbonrender.ts:299` — not importable, quoted here as a fact, not an API), leaving ~4.6px of
gutter; a hatched ribbon fills `0.48` (`ribbonrender.ts:254`), leaving ~12px. In-canvas hour labels
therefore read on hatched rows and collide with the bands on stacked ones — observed on Hallenbad
City · Schwimmerbecken. Labels go in the DOM, above the canvas, where the card can give them their
own 12px. The canvas gets marks only, and those marks are drawn **after** the ribbons: under an
opaque lane band a hairline is invisible.

### One mapping, two renderers

The strip is positioned in **percentages**, so it needs no layout measurement. Percentages align to
the canvas only if the two share a content box, and they do not by default: after S1 removes
`.plist__btn`'s inline padding, the canvas's 12px comes solely from `.plist__tail`
(`blocks.css:1206`), so a bare sibling strip would be 24px wider and every label would sit ~7% off —
about one hour of the window. **CSS contract**: one padded wrapper inside `btn` supplies the inline
padding for both, and neither child pads itself — one declaration, so the two cannot drift.

The DOM, stated exactly, because "siblings" is not what it is:

```
button.plist__btn
  └ div.plist__plot          padding-inline: var(--s3)   ← the ONLY inline padding
      ├ div.plist__ticks     no padding
      └ div.plist__tail      no padding (loses its own)
          └ canvas
```

`.plist__tail` **stays**. It is the only thing `blocks.css:1207`
(`.plist__tail canvas { display: block; width: 100% }`) matches, and that rule is what makes the
canvas fill its box; hoisting the canvas straight into `.plist__plot` would leave it laid out at its
*attribute* width — the backing store, up to `2 × dpr` px — which `tailWidth()` then reads back
through `clientWidth` (`poollist.ts:118-123`) and feeds into the next paint. That is the same
misalignment this contract exists to prevent, arriving through the DOM instead of the padding.

Note in passing: a `<div>` inside a `<button>` is invalid per HTML's phrasing-content model. It is
inert here because the tree is built with `createElement`/`appendChild` and never parsed — recorded
so it is not re-litigated later.

```ts
// daytail.ts — pure, no canvas
export const STRIP_HOURS: readonly number[];    // [6, 9, 12, 15, 18, 21] — the labelled hours
export const TICK_HOURS: readonly number[];     // STRIP_HOURS minus 06 — the left edge needs no mark
export function tickPercent(hour: number): number;   // 0..100 across [TAIL_DAY0, TAIL_DAY1]
```

Invariant **X1**: for every hour and any width `w`, `tickPercent(h)` equals
`tailTimescale(w).X(h * 60) / w * 100` **to within a float tolerance** — both sides in percent. The
tolerance is not slack: `X` computes `((min - lo) / span) * PLOT`, so the two sides differ by 1 ulp
at some widths. Measured on the real hour set, 320 and 390 (iPhone SE, iPhone 12-14) mismatch under
`===` at hour 21 while 340/375 pass — a strict-equality test would go red on correct code at the two
most common phone widths.

### Drawing order and the out-of-window cursor

`drawDayTail` becomes: ribbons → ticks → cursor. Ticks are drawn **unconditionally**: `poollist` is
the only caller (`grep drawDayTail` → `daytail.ts`, `poollist.ts:22,102`, its own test), and the
desktop board paints through `drawRibbons` + `board.ts::drawAxis` instead, so an opt-in flag would
be a branch with one always-true call site. Each tick is a full-height rule at low alpha plus a
~4.5px notch in the top and bottom gutters, so it reads whatever the ribbon does.

The cursor branch today computes `const x = ts.X(cursor)` with no bounds check (`daytail.ts:108`).
When now is outside `[06:00, 22:30]` — before 06:00, which is exactly the reported screenshot —
the line is drawn off-canvas and silently vanishes. Invariant **X2**: a cursor outside the window
is **not drawn at all**, and that is a deliberate no-op rather than an off-canvas stroke.

### The tap target

`poollist.ts:166-175` runs `card.appendChild(btn)` and only then appends `tailBox` to the card, so
the ribbon sits outside the button the click handler is bound to. The strip and the tail move
**inside** `btn`; `.plist__more` stays outside it (a `<button>` may not contain interactive content,
and the expanded body holds the scrollable, focusable Gantt).

Two consequences to respect.

**Width.** `poollist.tailWidth()` measures `canvas.clientWidth`. Today the canvas sits inside
`.plist__tail`, itself padded `var(--s1) var(--s3) var(--s3)` (`blocks.css:1206`, `--s3: 12px`), so
the canvas is already 12px in from each edge of the card's content box — it does **not** span the
full width, and must not start to. `.plist__btn` adds its own 12px inline padding (`blocks.css:1154`)
which, once the tail is inside the button, would stack to 24px and shrink every plot. Invariant
**X3**: *total inline padding around the canvas is unchanged at 12px per side.* This is a layout
fact and the suite has no layout engine (FakeElement has no `clientWidth`; `tailWidth()` falls back
to 340; no test parses `blocks.css`), so X3 is verified by eye at the `pause_after` S1 gate —
named here so no one mistakes it for something a green suite proved.

**Accessible name.** `poollist.ts:138` names the `h3` with `ranked.row.label` and `:173-174` gives
the canvas `role="img"` + the *same* `aria-label`. A `<button>` computes its name from its contents,
so moving the canvas inside it would announce every pool name twice, on all ~58 rows. The canvas
becomes `aria-hidden="true"` in the same move; the button keeps its name from the heading.

### Hour labels go through `datefmt`

```ts
// datefmt.ts
export function formatHour(hour: number, locale: Locale = DEFAULT_LOCALE): string;  // 6 -> "06:00"
```

`gantt.ts:194` formats its axis with `String(hour).padStart(2, '0') + ':00'`, bypassing
`datefmt.ts` — which per CLAUDE.md owns every date/number rendering. The new strip must not copy
that bypass. It returns the **same `HH:00` shape the Gantt renders**, so the collapsed strip and the
expanded axis cannot read differently for the same hour. The formatter forces `hourCycle: 'h23'`:
every schedule string the app renders comes from the API as `"06:00"`, so a locale-chosen `6 AM`
axis would contradict the verdict text directly above it.

## Out of scope

- Any shared/pinned ruler (variants A, D, D2) — the owner chose B. `phonebar.ts` is not touched.
- The scrub readout (variant C) and per-card span captions (variant E).
- Retro-fitting `gantt.ts` onto `formatHour`. It is the reason `formatHour` exists, but changing
  the Gantt's axis is a separate, wider blast radius; note it as debt.
- `phoneNowMin()` (`app.ts:474`) reads `new Date().getHours()` — machine-local, not
  `Europe/Zurich`, against the project's tz-aware convention. Real, unrelated, and left alone.
- The desktop board. It does not call `drawDayTail` at all (it paints via `drawRibbons` +
  `drawAxis`), so nothing in this plan can reach it.

## Slices

### S1 — The ribbon is the tap target

- **Goal**: tapping the bars opens the card, exactly as tapping the title does.
- **Touches**: `blocks/poollist.ts` (`buildCard` — `tailBox` moves inside `btn`; canvas gains
  `aria-hidden`), `apps/web/static/blocks.css` (`.plist__btn`'s inline padding moves onto
  `.plist__head` and `.plist__meta` — and **only** those two: `.plist__verdict` and `.plist__fair`
  nest inside `.plist__text` inside `.plist__head` (`poollist.ts:135-160`) and would double-indent),
  `blocks/phonelist.test.ts`.
- **Acceptance**:
  - a new test asserts `tailBox.parentNode === btn` for a built card. `El`/`FakeElement` expose
    `parentNode`, **not** a node-level `contains` (that exists only on `ElClassList`,
    `domtypes.ts:17`), and `_fakedom.js:107` `dispatch` does not bubble — so parentage is the
    assertable form of "a tap on the tail reaches the button";
  - `.plist__more` is NOT inside `btn` — asserted, so the Gantt never nests in a button;
  - the canvas carries `aria-hidden="true"` and the `h3`'s text appears exactly once inside `btn`
    — asserted as those two facts, so "no row announces its pool name twice" is checked, not just
    asserted in prose. The canvas keeps its now-inert `role="img"` / `aria-label`, so
    `phonelist.test.ts:50-56` (`each card carries a day tail canvas labelled with its pool`) passes
    unchanged;
  - the existing `tapping a card expands it, and tapping again collapses` and `the expanded card
    reports its state to assistive tech` tests pass unchanged.
- **Verified by eye at the pause gate (X3)**: total inline padding around the canvas is still 12px
  per side, so no tail rescaled. Not machine-checkable — see the Design note.
- **Depends on**: —

### S2 — Marks in the canvas, and an honest cursor

- **Goal**: hour marks that survive a lane stack, and a cursor that is either correct or absent.
- **Touches**: `blocks/daytail.ts` (`STRIP_HOURS`, `TICK_HOURS`, `tickPercent`, `drawTicks`, the
  cursor bounds check), `blocks/daytail.test.ts`, `testutil.ts` (hoist a recording 2D context),
  `blocks/board_render.test.ts` (its local `recordingCtx` becomes the import). `testutil.ts` is
  coverage-measured and fully exercised by both suites, so the hoist carries no CRAP risk — do
  **not** answer a surprise there by widening `vitest.config.ts`'s exclude list.
- **Acceptance**:
  - `tickPercent(h)` is within `1e-10` of `tailTimescale(w).X(h * 60) / w * 100` for every hour in
    `STRIP_HOURS`, at widths **320, 375 and 390** — 320 and 390 chosen deliberately because they are
    the ulp cases (X1);
  - **ordering**: against a `lanestack` fixture with `sheath: true` and lane strips — pinned in the
    criterion because the four ribbon painters emit different ops, and the hatched painter emits its
    own `moveTo` per hatch line (`ribbonrender.ts:271`) while the `status` painter emits no
    `fillRect` at all — the last `fillRect` index is **less** than the first tick `moveTo` index.
    Ticks are identified by coordinate (`moveTo(x, 0)`), not by being the first `moveTo`, so the
    assertion cannot be satisfied by a ribbon's own path ops;
  - **cursor** as a differential, since ticks now stroke too and a raw stroke count says nothing:
    the stroke count with `cursorMin: 860` is exactly one greater than with `cursorMin: null`, and
    `300` (05:00) and `1400` (23:20) each give the same count as `null` (X2);
  - the recorder follows `board_render.test.ts:40-72` but must also accept `setTransform`, which
    `daytail.ts:96` calls first; it is hoisted into `testutil.ts`, not copied;
  - `drawDayTail` is still a no-op headless.
- **Depends on**: —

### S3 — The hour strip on every card

- **Goal**: the labels the user actually reads, above every tail.
- **Touches**: `datefmt.ts` + `datefmt.test.ts` (`formatHour`), `blocks/poollist.ts` (build the
  strip inside the `.plist__plot` wrapper, above the canvas), `apps/web/static/blocks.css`
  (`.plist__ticks`, `.plist__plot`, and `.plist__tail` loses its inline padding to the wrapper),
  `blocks/phonelist.test.ts`.
- **Acceptance**:
  - `formatHour(6)` returns exactly `"06:00"` in all five locales — the same shape `gantt.ts:194`
    renders, pinned as a literal so the collapsed strip and expanded axis cannot drift; a test pins
    `hourCycle: 'h23'` via `resolvedOptions()`, not via output — `datefmt.ts:28-37` already maps
    `en → en-GB`, which yields `"06:00"` anyway, so no output literal can tell a correct
    implementation from one that omits the option;
  - every card carries one strip with `STRIP_HOURS.length` labels, each positioned by `tickPercent`
    and formatted by `formatHour` (asserted, not eyeballed);
  - the DOM matches the contract above, asserted as parentage: `strip.parentNode === plot` and
    `canvas.parentNode === tailBox && tailBox.parentNode === plot`. `.plist__tail` survives, so
    `blocks.css:1207` keeps matching and the canvas keeps `width: 100%`;
  - the strip is inside `btn` — it must not punch a dead gap in the tap target S1 just created;
  - the strip is `aria-hidden` — six loose numbers per card would flood a screen reader on a 58-row
    list;
  - both QA chains green, CRAP gate not regressed.
- **Verified by eye at the pause gate**: a label sits over its hour on a real card. Alignment is a
  layout fact and no test parses `blocks.css` — same honesty as X3.
- **Depends on**: S1 (the button owns the tail), S2 (`tickPercent`).

## Accepted drift

Findings the user has knowingly blessed, so `/dev:present` folds them into a
count instead of re-listing them every run. See [[accepted-drift]]. Ships empty:
rows are added by the human, or pasted from what `/dev:present` prints — never
by the command itself.

**Append-only, like the ledger.** Rows are added, never edited or deleted; a row
that stops applying is reported as stale, not removed.

`kind` is the bare word — `DROP`, `SUB`, `INV` — never the rendered symbol
(`− DROP`). `key` is `intent:+<n>`, an offset counted from the
`## Intent (verbatim)` heading line (offset 0), never a file line number.
`+ ADD` findings have no Intent phrase to anchor and cannot be accepted.

| kind | key | why | date |
|------|-----|-----|------|

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

**2026-08-13 — variant B over a shared ruler.** Five treatments were mocked on live data. A shared
pinned ruler (A/D) reads better per-pixel and costs less vertical space, but `phonebar.ts` documents
that only ONE element may be pinned — two at `top:0` stack and overpaint, which once hid the filter
row outright — so a second sticky bar was a design conflict, and folding the ruler into the existing
pinned bar (D2) couples it to `phonebar.ts` and to `env(safe-area-inset-*)`. B is self-contained and
touches no pinned surface. Owner chose B knowing its cost: a 12px strip on ~58 rows is roughly one
extra phone screen of scroll.

**2026-08-13 — labels DOM, marks canvas.** Forced by geometry, not taste: `STACK_BOX = 0.8` leaves
~4.6px of gutter on a lane-stack row, which no label fits in. First observed as a collision on
Hallenbad City · Schwimmerbecken.

**2026-08-13 — pre-approval review (dev:plan-critic), seven blocking findings taken.** The
substantive ones: (a) `DayTailOpts.ticks` was **deleted** — `poollist` is the only caller of
`drawDayTail`, the board paints elsewhere, so the flag was a branch with one always-true call site
and the "the board must not gain marks" rationale was simply false; (b) moving the canvas inside the
button would have made every row announce its pool name **twice** (`h3` and the canvas `aria-label`
carry the same `row.label`), so the canvas gains `aria-hidden` in S1 — an a11y regression the plan
had reasoned about for the strip but not for the canvas it was moving; (c) the padding move was
listed onto `.plist__verdict`/`.plist__fair`, which nest inside `.plist__head` and would have been
double-indented; (d) X3 was written as a testable criterion, but the suite has no layout engine —
restated as an explicit eyeball at the S1 pause gate rather than something a green suite pretends to
prove; (e) X1 was stated in mismatched units (percent vs ratio) between the Design and its criterion;
(f) `btn.contains(tailBox)` is not an API that exists on `El`/`FakeElement` — the criterion is now
`parentNode`; (g) `STACK_BOX` is module-private, quoted as a fact rather than an importable symbol.
S2 (`formatHour`) was folded into the strip slice on the critic's suggestion — a five-line formatter
with no caller until then did not warrant its own gate cycle. Not taken: nothing.

**2026-08-13 — pre-approval review, round 2: three more blocking findings taken.** (a) The
draw-order criterion was **not decidable** as written: the four ribbon painters emit different ops,
and the hatched painter emits its own `moveTo` per hatch line (`ribbonrender.ts:271`) — so "first
`moveTo` after last `fillRect`" would have gone red against a *correct* implementation on the very
variant the design is built around, while the `status` painter emits no `fillRect` at all, making it
vacuous. Now: a pinned `lanestack` fixture, ticks identified by coordinate, and the cursor asserted
as a differential stroke count (ticks stroke too, so a raw count proves nothing). (b) X1's `===`
was **wrong at the two most common phone widths** — `X` recomputes `(a*w)/w`, which differs by 1 ulp;
320 and 390 mismatch at hour 21 where 340/375 pass. Verified independently before accepting. Now a
tolerance, with those widths named so the ulp case is actually exercised. (c) The claim that
percentages "cannot drift from the canvas" was **unproven and false by default**: once S1 strips
`.plist__btn`'s padding, a bare sibling strip is 24px wider than the canvas and every label lands
~7% — about one hour — off. Now a stated CSS contract (one padded `.plist__plot` wrapper) plus an
eyeball gate, and `pause_after` gained S3.

**2026-08-13 — the cursor defect is a bounds check, not missing wiring.** An earlier reading of this
work claimed the "now" rule never draws because `cursorMin` arrives null. That was wrong:
`app.ts:474-478` supplies a real `nowMin` on today and `poollist.ts` threads it through. The actual
fault is `daytail.ts:108` computing `ts.X(cursor)` unclamped, so a now outside `[06:00, 22:30]`
strokes off-canvas. Recorded because the wrong mechanism would have produced the wrong fix.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/mobile-daytail-time-axis.md` (what EXISTS now, not what was intended).
