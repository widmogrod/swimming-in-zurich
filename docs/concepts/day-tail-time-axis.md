---
type: concept
created: 2026-08-13
updated: 2026-08-14
links: ["[[2026-08-13-mobile-daytail-time-axis-plan]]", "[[mobile-daytail-time-axis]]"]
---

> **As-built 2026-08-14.** Shipped as described. Two details this doc did not anticipate:
> the strip and the canvas coincide because one `.plist__plot` wrapper owns the single inline
> padding (`.plist__tail` survives inside it, because `.plist__tail canvas { width: 100% }` is the
> only thing keeping the canvas off its attribute width); and `tickPercent` is
> `tailTimescale(100).X(hour * 60)` rather than a hand-derived window, so "one mapping" is
> structural rather than merely asserted.

# The day tail's time axis — why the labels are DOM and the marks are canvas

The phone's day tail (`blocks/daytail.ts`) is the desktop ribbon renderer on a compressed
timescale. Position encodes time across `[TAIL_DAY0, TAIL_DAY1]` = `[06:00, 22:30]`, but the tail
shipped without any way to read that position: the desktop's hour header lives in
`board.ts::drawAxis`, and the phone has no equivalent — `phonebar.ts` carries the date, not the
hours.

**The axis is split across two renderers, and that split is forced by geometry.** A lane-stack
ribbon fills `ribbonrender.STACK_BOX = 0.8` of the row's `TAIL_H = 46px`, leaving ~4.6px of gutter;
a hatched (hours-published, lane-split-unknown) ribbon fills `0.48` and leaves ~12px. So in-canvas
hour labels read fine on hatched rows and collide with the bands on stacked ones. Labels therefore
live in a DOM strip above the canvas; the canvas carries marks only.

Two rules keep the two halves honest:

- **One mapping.** The strip positions its labels with `tickPercent(hour)` — pure, percentage-based,
  needing no layout measurement — and `tickPercent` is asserted against
  `tailTimescale(w).X(hour * 60) / w`. Neither half may compute its own hour geometry.
- **Marks paint last.** Ticks are drawn *after* the ribbons, never before: under an opaque lane
  band a hairline is simply invisible, which fails precisely on the rows carrying the most
  information. Each mark is a low-alpha full-height rule plus a notch in the top and bottom gutters,
  so it reads whatever the ribbon does.

A related invariant belongs to the same surface: the "now" cursor is drawn only when now falls
inside the window. Drawing `ts.X(cursor)` unclamped puts the line off-canvas before 06:00 or after
22:30 — present in the code, invisible on screen, and indistinguishable from a bug.

Hour labels render through `datefmt.formatHour`, not `String(h).padStart(2, '0')`, because
`datefmt.ts` owns every date and number rendering in this codebase. It returns the same `HH:00`
shape `gantt.ts` renders, so a collapsed card and its expanded panel cannot label the same hour
differently. The formatter forces `hourCycle: 'h23'`: schedule strings arrive from the API as
`"06:00"`, so a locale-chosen `6 AM` axis would contradict the verdict text directly above it.
`gantt.ts` still uses the raw `padStart` form — known debt, not a precedent.

One more thing the axis work must not break: the canvas sits **inside** the card's button, so the
ribbon is tappable, and it is therefore `aria-hidden`. The button takes its accessible name from the
card's heading; a canvas `aria-label` there would name every row twice.
