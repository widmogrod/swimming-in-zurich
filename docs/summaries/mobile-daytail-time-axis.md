---
type: summary
feature: mobile-daytail-time-axis
plan: "[[2026-08-13-mobile-daytail-time-axis-plan]]"
status: done
updated: 2026-08-14
links: ["[[day-tail-time-axis]]", "[[ux-mobile-direction-fusion-e]]", "[[lane-stack-board]]", "[[typescript-build-pipeline]]"]
---

# The phone's day tail, made readable

## The reported bug

> "in mobile view swimlines don't have time information so I don't know what availability is on
> which hour"

The tail encoded time by horizontal position across a fixed `[06:00, 22:30]` window and shipped no
way to read it. On the desktop that is fine — `board.ts::drawAxis` paints one shared hour header
above every row — but the phone has no such header: `phonebar.ts` carries the *date*, never the
*hours*. The expanded card never had the problem, because `gantt.ts` builds its own `.gantt__axis`.

## What exists now

**Per card, two halves of one axis.** Six labels (`06:00`…`21:00`) in a DOM strip above the canvas;
a full-height rule plus a notch in each gutter at 09/12/15/18/21 inside it. The split is forced by
geometry, not taste — a lane-stack ribbon fills `STACK_BOX = 0.8` of the 46px row and leaves ~4.6px
of gutter, which no label fits in, while a hatched ribbon leaves ~12px. That asymmetry is why
in-canvas labels read on most rows and collided on Hallenbad City · Schwimmerbecken.

**Marks paint last.** `drawDayTail` runs ribbons → ticks → cursor. Drawn first, a hairline vanishes
under an opaque lane band — failing on exactly the rows carrying the most information. The order is
pinned by a test against a recording 2D context, not assumed.

**One mapping.** `tickPercent(hour)` is `tailTimescale(100).X(hour * 60)`; the canvas uses
`tailTimescale(width)`. The `PLOT` factor cancels, so strip and canvas share one window with no
measurement and no second hand-derived constant. Their content boxes are made to coincide by a
single `.plist__plot` wrapper that owns the only inline padding:

```
button.plist__btn
  └ div.plist__plot          padding-inline: var(--s3)   ← the ONLY inline padding
      ├ div.plist__ticks     aria-hidden
      └ div.plist__tail      keeps padding-block; `.plist__tail canvas { width: 100% }`
          └ canvas           aria-hidden
```

`.plist__tail` must survive: it is the only selector matching that `width: 100%` rule, without which
the canvas lays out at its *attribute* width (the backing store, up to 2× dpr) — which `tailWidth()`
then reads back through `clientWidth` and feeds into the next paint.

Those `div`s inside a `<button>` are invalid HTML — a button takes phrasing content only, and
building the tree with `createElement` does not change that. It is pre-existing (the button already
wrapped `.plist__head` and `.plist__meta`) and merely widened here; what it costs, and why fixing it
is its own piece of work, is [[card-button-content-model]].

**Two defects fixed on the way.** The ribbon is now inside the card's button, so tapping the bars
opens the card; it previously did nothing, because `poollist.ts` appended the tail to the card
*after* closing the button. And the "now" cursor is drawn only inside the window — it was computing
`ts.X(cursor)` unclamped, so before 06:00 it stroked off-canvas: present in the code, invisible on
screen, indistinguishable from a bug.

## Three things this paid for beyond its brief

- **`--focus-ring-inset`** (`tokens.css`). The tap-target move destroyed the card's keyboard focus
  ring: `--focus-ring` is purely *outset*, `.plist__card` clips with `overflow: hidden`, and the one
  visible sliver had been living in padding this work deleted — with `outline: none` on the same
  selector, that left **no** focus indication. An inset ring paints inside the button's own padding
  box, which no ancestor clip can reach. Available to any other control nested in a clipping card;
  not audited for other sites.
- **`recordingCtx` in `testutil.ts`** (was local to `board_render.test.ts`, now shared, plus
  `setTransform`). Canvas draw *order* is assertable for both surfaces.
- **`datefmt.formatHour`** — the hour label `gantt.ts:194` still open-codes as
  `String(hour).padStart(2, '0') + ':00'`. Same `HH:00` shape, so a collapsed strip and its expanded
  panel cannot label an hour differently.

## Limits, honestly

Three layout facts are **eyeball-verified**, not gated: the 12px inline padding around the canvas,
strip-to-mark alignment, and that the focus ring is visible. This suite has no layout engine
(`FakeElement` has no `clientWidth`) and no test parses `blocks.css`; the plan routed all three to a
human gate rather than to a test pretending to prove them. Marks also round to `Math.round(x) + 0.5`
while labels are exact, so up to 0.5px of slack exists by construction.

The `hourCycle: 'h23'` pin guards the **constant**, not the call site: inlining the options at
`formatHour` keeps the suite green until a locale defaulting to `h12` is added. It is asserted
against `en-US` — the only tag that can tell — and that foreign tag carries a "do not tidy this
away" note in two places.

Cost accepted: a 12px strip on ~58 rows is roughly one extra phone screen of scroll.

## Two lessons worth carrying

**`resolvedOptions()` cannot guard an `Intl` option whose value matches the locale's default.** The
plan prescribed exactly that and it was a tautology — all five `FORMAT_LOCALE` tags default to
`h23`, so the assertion passed with the option deleted. Only a locale that defaults differently can
falsify it.

**Never write `expect(nodeA).toBe(nodeB)` in a `FakeElement` suite.** A red identity assertion makes
vitest deep-diff both trees through their `parentNode` back-references: one failure took 262 seconds
to serialize and read exactly like a hung suite. Compare as booleans (`a === b` → `toBe(true)`) with
a `parentNode?.className` alongside for a readable diagnosis.
