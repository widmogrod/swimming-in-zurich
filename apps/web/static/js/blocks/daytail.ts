// daytail.ts — the phone's per-row "day tail".
//
// It is ribbonrender.ts with a COMPRESSED timescale and no axis: the same encoding the
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
// This module owns exactly two things the board does not: device-pixel scaling (the board
// canvases are laid out at their intrinsic size, a tail is laid out by CSS and must be
// rescaled on resize) and the "now" cursor, which the board draws as a separate DOM line
// across all rows but a tail must carry itself.

import { makeTimescale } from '../timescale.js';
import {
  drawRibbons,
  type CanvasEl,
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
  drawRibbons(ctx, ribbons, ts, pal, TAIL_H / 2, TAIL_H, opts.phase ?? 0);

  const cursor = opts.cursorMin;
  if (cursor == null) return;
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
