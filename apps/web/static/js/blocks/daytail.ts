// daytail.ts — the phone's per-row "day tail".
//
// It is ribbonrender.ts with a COMPRESSED timescale and no axis CHROME: the same encoding the
// desktop board paints (thickness = public_lanes/lane_count about a mid-line, pinched
// where lanes are reserved, over a faint capacity sheath), squeezed from the board's
// 900px plot into whatever width a phone row happens to be.
//
// That sharing is the point. The tail exists so lane busyness is glanceable straight from
// the list, and it is only worth calling it "the same as the desktop" if it literally is
// the same renderer — otherwise the two drift the first time either is touched.
//
// The board's window is [06:00, 22:00]; the tail runs to 22:30 so a session that ends at
// 22:00 has somewhere to end rather than being clipped flush against the right edge.
//
// This module owns exactly three things the board does not: device-pixel scaling (the board
// canvases are laid out at their intrinsic size, a tail is laid out by CSS and must be
// rescaled on resize), the "now" cursor, which the board draws as a separate DOM line
// across all rows but a tail must carry itself, and the per-card HOUR MARKS.
//
// The marks exist because the phone has no shared hour header. The board paints one
// `board.ts::drawAxis` above every row; `phonebar.ts` carries the date and never the hours,
// so without marks a bar's horizontal position encodes a time nobody can read. The LABELS
// live in the DOM above the canvas (a lane stack fills 0.8 of the row, leaving ~4.6px of
// gutter — no type fits there); the canvas gets marks only, positioned by the same mapping
// the labels use (`tickPercent`), so the two cannot drift.

import { makeTimescale } from '../timescale.js';
import {
  drawRibbons,
  type CanvasEl,
  type Ctx2D,
  type Palette,
  type RenderRibbon,
  type Timescale,
} from './ribbonrender.js';

/** The tail's day window. Wider than the board's on the right — see the module note. */
export const TAIL_DAY0 = 6;
export const TAIL_DAY1 = 22.5;

/** CSS-px height of a tail. Matches the board's ROW_H so the encoding reads at the same
 *  scale on both surfaces (`maxHalf = h * 0.4` is relative, but the eye is not). */
export const TAIL_H = 46;

/** Cap the backing store: beyond 2x the extra pixels cost memory and buy nothing. */
export const MAX_DPR = 2;

/** tailTimescale(width) — the compressed [06:00, 22:30] mapping across `width` px. */
export function tailTimescale(width: number): Timescale {
  return makeTimescale(TAIL_DAY0, TAIL_DAY1, width);
}

/**
 * The hours the card LABELS, in the DOM strip above the canvas.
 *
 * Every three hours: six labels is what fits a 320px phone without the `HH:00` texts
 * touching, and it puts a mark inside every part of the window a session can fall in.
 */
export const STRIP_HOURS: readonly number[] = [6, 9, 12, 15, 18, 21];

/**
 * The hours the canvas MARKS — the labelled hours minus 06:00.
 *
 * The left edge of the plot IS 06:00, so a rule there paints on the canvas border and
 * reads as a frame rather than as a time.
 */
export const TICK_HOURS: readonly number[] = STRIP_HOURS.filter((h) => h !== TAIL_DAY0);

/** The tail's window rendered across a PLOT of exactly 100 — i.e. the same mapping in
 *  percent. Built once: it is a constant, and `tickPercent` is called per label per card. */
const PERCENT_SCALE = tailTimescale(100);

/**
 * tickPercent(hour) — where `hour` sits across the tail window, as a percentage.
 *
 * PURE, and no canvas: it is the DOM strip's positioning rule, and it must agree with the
 * canvas mapping or a label sits over the wrong bar.
 *
 * It goes through `tailTimescale` rather than re-deriving `lo`/`span` from `TAIL_DAY0` /
 * `TAIL_DAY1` by hand, because a hand-copied window is precisely the drift this module
 * exists to prevent: "percent" is just this scale with `PLOT = 100`, so the strip and the
 * canvas cannot disagree about the window even if the window changes. That the `PLOT`
 * factor cancels is also why the strip needs no layout measurement to line up.
 *
 * (`X` computes `((min - lo) / span) * PLOT` and the invariant divides by `PLOT` again, so
 * the two sides can differ by 1 ulp at some widths — X1 is a tolerance, not `===`.)
 */
export function tickPercent(hour: number): number {
  return PERCENT_SCALE.X(hour * 60);
}

/** How far a tick's notch reaches into the row's top and bottom gutters, in CSS px.
 *  Sized to the tightest gutter there is: a lane stack fills `0.8 * TAIL_H`, leaving
 *  4.6px, so a 4.5px notch reads on every variant without ever crossing a band. */
const TICK_NOTCH = 4.5;

/**
 * drawTicks(ctx, ts, pal, h) — the hour marks, painted AFTER the ribbons.
 *
 * Order is the whole point: under an opaque lane band a hairline is invisible, so a mark
 * drawn first simply is not there on the rows that need it most. Each hour gets a
 * full-height rule at low alpha (legible in the gutters and through the translucent
 * sheath, never loud enough to read as a session boundary) PLUS a solid notch in the top
 * and bottom gutters, which no ribbon variant reaches — so the mark survives whatever the
 * row happens to paint.
 *
 * Colour comes from the resolved Palette, like every other fill in this renderer: no hex.
 */
function drawTicks(ctx: Ctx2D, ts: Timescale, pal: Palette, h: number): void {
  ctx.save();
  ctx.setLineDash([]);
  // `pal.hair || pal.axis`, exactly as `board.ts::drawRow` resolves the same hairline ink.
  // `Palette` is a `Record<string, string>`, so a mistyped key type-checks and would ship
  // an invisible (or default-black) rule; the fallback is the only thing standing between
  // that typo and a silently unmarked tail. No hex here either way.
  ctx.strokeStyle = pal.hair || pal.axis;
  ctx.lineWidth = 1;
  for (const hour of TICK_HOURS) {
    // Half-pixel offset: a 1px stroke centred on an integer x straddles two device
    // columns and renders as a 2px smudge.
    const x = Math.round(ts.X(hour * 60)) + 0.5;
    ctx.globalAlpha = 0.18;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, TICK_NOTCH);
    ctx.moveTo(x, h - TICK_NOTCH);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * tailBacking(width, dpr) — the backing-store size for a tail laid out at `width` CSS px.
 *
 * Pure so the scaling rule is testable without a canvas. A non-finite or absurd dpr
 * (some embedded webviews report 0) falls back to 1 rather than producing a zero-sized
 * canvas, which would silently render nothing at all.
 */
export function tailBacking(width: number, dpr: number): { w: number; h: number; scale: number } {
  const safe = Number.isFinite(dpr) && dpr > 0 ? Math.min(MAX_DPR, dpr) : 1;
  return {
    w: Math.max(1, Math.round(width * safe)),
    h: Math.max(1, Math.round(TAIL_H * safe)),
    scale: safe,
  };
}

export interface DayTailOpts {
  /** Laid-out width in CSS px. A width of 0 (an unattached or display:none row) is a
   *  no-op rather than an error — the caller redraws on resize. */
  width: number;
  devicePixelRatio?: number;
  /** Animates the waterline; pass 0 to freeze it under prefers-reduced-motion. */
  phase?: number;
  /** Minutes-of-day for the shared cursor, or null on a day that is not today. */
  cursorMin?: number | null;
  cursorColor?: string;
}

/**
 * drawDayTail(canvas, ribbons, pal, opts) — paint one row's day tail.
 *
 * Headless (no `getContext`) or unresolved palette → a no-op, exactly as the board's
 * `drawRow` does: the drawable LOGIC lives in ribbonmodel/poolrank and is tested there,
 * so a canvas-free environment loses nothing testable.
 */
export function drawDayTail(
  canvas: CanvasEl,
  ribbons: RenderRibbon[],
  pal: Palette | null,
  opts: DayTailOpts,
): void {
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;
  if (!ctx || !pal) return;
  const width = opts.width;
  if (!(width > 0)) return;

  const back = tailBacking(width, opts.devicePixelRatio ?? 1);
  if (canvas.width !== back.w || canvas.height !== back.h) {
    canvas.width = back.w;
    canvas.height = back.h;
  }
  ctx.setTransform(back.scale, 0, 0, back.scale, 0, 0);
  ctx.clearRect(0, 0, width, TAIL_H);

  const ts = tailTimescale(width);
  // Ribbons -> ticks -> cursor. Ticks are unconditional: `poollist` is the only caller of
  // this function, and the desktop board paints through `drawRibbons` + `board.ts::drawAxis`
  // instead, so an opt-in flag would be a branch with one always-true call site.
  drawRibbons(ctx, ribbons, ts, pal, TAIL_H / 2, TAIL_H, opts.phase ?? 0);
  drawTicks(ctx, ts, pal, TAIL_H);

  const cursor = opts.cursorMin;
  if (cursor == null) return;
  // A "now" outside the tail's window is NOT DRAWN — deliberately, rather than stroked
  // off-canvas. Before 06:00 the unclamped `ts.X(cursor)` is negative and the rule silently
  // vanished; clamping it to the edge would be worse still, asserting that now is 06:00.
  if (cursor < ts.lo || cursor > ts.hi) return;
  ctx.save();
  ctx.strokeStyle = opts.cursorColor || pal.axis;
  ctx.globalAlpha = 0.9;
  ctx.lineWidth = 2;
  const x = ts.X(cursor);
  ctx.beginPath();
  ctx.moveTo(x, 2);
  ctx.lineTo(x, TAIL_H - 2);
  ctx.stroke();
  ctx.restore();
}
