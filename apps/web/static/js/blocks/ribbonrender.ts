// ribbonrender.ts — the SHARED ribbon renderer.
//
// Extracted from board.ts so the desktop board and the phone day tail paint from ONE
// implementation and cannot drift. The encoding is the whole point of the design:
//
//   thickness = public_lanes / lane_count   about a mid-line at maxHalf = h * 0.4
//   pinched to 0.72x                        wherever reserved_lanes > 0
//   over a faint capacity sheath            the full envelope, so thickness reads as a
//                                           FRACTION rather than an unscaled number
//
// Everything here is a pure function of (ctx, ribbon, timescale, palette, box): no DOM,
// no layout, no colour of its own (fills arrive via the resolved Palette). The caller
// owns the canvas, its size and its device-pixel scaling — which is exactly what lets a
// 900px desktop plot and a ~340px phone tail share this code with only a different
// Timescale and height.

import { hhmmToMin } from './cursor.js';
import { t, type MessageKey } from '../i18n.js';
import type { El } from '../domtypes.js';
/** A ribbon read STRUCTURALLY — only the fields the renderer paints. Deliberately
 *  looser than ribbonmodel's `Ribbon` so both it and board.ts's local row type satisfy
 *  it; the renderer must not care which producer built the spec. */
export interface RenderRibbonSegment {
  start: string;
  end?: string;
  thickness?: number | string;
  pinched?: boolean;
  [k: string]: unknown;
}

export interface RenderRibbon {
  kind?: string;
  variant?: string;
  family?: string;
  sheath?: boolean;
  dash?: string;
  detail?: string | null;
  label?: string;
  start?: string;
  end?: string;
  segments?: RenderRibbonSegment[];
  [k: string]: unknown;
}

/** Canvas fills resolved at runtime from the `.fam-*` classes (blocks.css -> tokens.css). */
export type Palette = Record<string, string>;

/** The shared timescale (timescale.js) — the ONE X(min) mapping the Gantt also uses. */
export interface Timescale {
  X(min: number): number;
  inverse(x: number): number;
  DAY0: number;
  DAY1: number;
  PLOT: number;
  lo: number;
  hi: number;
  span: number;
}

/** The 2D context surface the renderer uses (null headless). */
export type Ctx2D = CanvasRenderingContext2D;

/** A canvas node — real or the headless stand-in whose getContext returns null. */
export interface CanvasEl extends El {
  width: number;
  height: number;
  getContext?(id: string): Ctx2D | null;
}

/** `doc.createElement('canvas')` yields a structural `El`; this is the one documented
 *  narrowing to the canvas surface (the headless fake has no getContext, hence optional). */
export function asCanvas(el: El): CanvasEl {
  return el as CanvasEl;
}

function setDashes(ctx: Ctx2D, style: string): void {
  if (style === 'dashed') ctx.setLineDash([9, 6]);
  else if (style === 'dotted') ctx.setLineDash([2, 5]);
  else ctx.setLineDash([]);
}

/**
 * closureLabel(status) — the human reason a pool is shut. A public holiday names
 * ITSELF; an unrecognised or untranslatable one falls back to the German name,
 * which is still true — never a blank.
 */
export function closureLabel(status: {
  detail?: string | null;
  closure_code?: string | null;
  detail_params?: Record<string, string>;
}): string {
  const code = status.closure_code;
  if (!code) return status.detail ?? '';
  const params = status.detail_params ?? {};
  // A public holiday names ITSELF: render the holiday, not the generic word. An
  // unrecognised or untranslatable one (Berchtoldstag) falls back to the German name,
  // which is still true — never a blank.
  if (code === 'public_holiday' && params.holiday) {
    const hk = `holiday.${params.holiday_code ?? 'unknown'}` as MessageKey;
    return t(hk, params);
  }
  const key = `closure.${code}` as MessageKey;
  return t(key, params);
}

// Paint the row's terminal state ON the plot (plan FIX 1), the way the prototype's
// drawClosed/drawGhost do — so state reads without a legend. Closed → a dashed rule +
// dot + "Closed · <detail>" (its reason kept); uncurated → a dotted envelope +
// "Hours not listed". The text is a token colour (pal.*), never a raw hex.
function drawStatusRibbon(
  ctx: Ctx2D,
  r: RenderRibbon,
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
) {
  ctx.save();
  if (r.variant === 'closed') {
    const x0 = 8;
    ctx.strokeStyle = pal.closed;
    ctx.lineWidth = 1.5;
    ctx.globalAlpha = 0.8;
    setDashes(ctx, 'dashed');
    ctx.beginPath();
    ctx.moveTo(x0, mid);
    ctx.lineTo(ts.PLOT - 8, mid);
    ctx.stroke();
    setDashes(ctx, 'solid');
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(x0, mid, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = pal.closed;
    ctx.fill();
    ctx.font = '600 12px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const reason = closureLabel({
      detail: r.detail,
      closure_code: r.closure_code as string | null | undefined,
      detail_params: r.detail_params as Record<string, string> | undefined,
    });
    ctx.fillText(
      reason ? t('status.closed_reason', { reason }) : t('status.closed'),
      x0 + 10,
      mid,
    );
  } else {
    const x0 = ts.X(7 * 60);
    const x1 = ts.X(21 * 60);
    const hh = Math.min(11, h * 0.26);
    ctx.strokeStyle = pal.unknown;
    ctx.lineWidth = 1.4;
    ctx.globalAlpha = 0.85;
    setDashes(ctx, 'dotted');
    ctx.beginPath();
    ctx.rect(x0, mid - hh, x1 - x0, hh * 2);
    ctx.stroke();
    setDashes(ctx, 'solid');
    ctx.globalAlpha = 1;
    ctx.fillStyle = pal.muted || pal.unknown;
    ctx.font = '500 11.5px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText(t('status.uncurated'), (x0 + x1) / 2, mid);
    ctx.textAlign = 'left';
  }
  ctx.restore();
}

// A published-hours-but-NO-lane-split ribbon (plan item 5): a faint capacity sheath
// with a HATCHED (dotted-outline + diagonal hatch) fill so it reads clearly as
// "open, lane split not published" — never as a solid public block.
function drawUnpublishedRibbon(
  ctx: Ctx2D,
  r: RenderRibbon,
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
) {
  const x0 = ts.X(hhmmToMin(r.start ?? ''));
  const x1 = ts.X(hhmmToMin(r.end ?? ''));
  const wSeg = Math.max(1, x1 - x0);
  const top = mid - h * 0.24;
  const height = h * 0.48;
  const col = (r.family ? pal[r.family] : undefined) || pal.other;
  ctx.save();
  // faint capacity sheath
  ctx.fillStyle = pal.sheath;
  ctx.globalAlpha = 0.4;
  ctx.fillRect(x0, top, wSeg, height);
  // diagonal hatch in the family colour (clipped to the sheath box)
  ctx.globalAlpha = 0.45;
  ctx.beginPath();
  ctx.rect(x0, top, wSeg, height);
  ctx.clip();
  ctx.strokeStyle = col;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  for (let x = x0 - height; x < x1 + height; x += 6) {
    ctx.beginPath();
    ctx.moveTo(x, top + height);
    ctx.lineTo(x + height, top);
    ctx.stroke();
  }
  ctx.restore();
  // dotted outline
  ctx.save();
  ctx.strokeStyle = col;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 1.1;
  setDashes(ctx, 'dotted');
  ctx.strokeRect(x0, top, wSeg, height);
  ctx.restore();
}

function drawLaneRibbon(
  ctx: Ctx2D,
  r: RenderRibbon,
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
  phase: number,
) {
  const col = (r.family ? pal[r.family] : undefined) || pal.other;
  const maxHalf = h * 0.4; // full capacity half-height
  for (const seg of r.segments ?? []) {
    const x0 = ts.X(hhmmToMin(seg.start));
    const x1 = ts.X(hhmmToMin(seg.end ?? ''));
    const wSeg = Math.max(1, x1 - x0);
    // Capacity sheath: the full-capacity envelope, faint.
    if (r.sheath) {
      ctx.save();
      ctx.fillStyle = pal.sheath;
      ctx.globalAlpha = 0.35;
      ctx.fillRect(x0, mid - maxHalf, wSeg, maxHalf * 2);
      ctx.restore();
    }
    // Public ribbon: thickness = public fraction; pinched (thinner) where reserved.
    const half = Math.max(1, maxHalf * Number(seg.thickness) * (seg.pinched ? 0.72 : 1));
    ctx.save();
    ctx.fillStyle = col;
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    const steps = 8;
    // top edge (with a small sinusoidal waterline animated by `phase`)
    for (let i = 0; i <= steps; i += 1) {
      const x = x0 + (wSeg * i) / steps;
      const wave = Math.sin(phase + (x / 40)) * 1.4;
      const y = mid - half + wave;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    // bottom edge back
    for (let i = steps; i >= 0; i -= 1) {
      const x = x0 + (wSeg * i) / steps;
      const wave = Math.sin(phase + (x / 40)) * 1.4;
      ctx.lineTo(x, mid + half - wave);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
}
/**
 * drawRibbons(ctx, ribbons, ts, pal, mid, h, phase) — paint one row's ribbons.
 *
 * The single dispatch every surface goes through. `phase` animates the waterline
 * (pass 0 to freeze it under prefers-reduced-motion).
 */
export function drawRibbons(
  ctx: Ctx2D,
  ribbons: RenderRibbon[],
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
  phase: number,
): void {
  for (const r of ribbons) {
    if (r.kind === 'status') {
      drawStatusRibbon(ctx, r, ts, pal, mid, h);
    } else if (r.variant === 'lanes') {
      drawLaneRibbon(ctx, r, ts, pal, mid, h, phase);
    } else {
      drawUnpublishedRibbon(ctx, r, ts, pal, mid, h);
    }
  }
}

export { setDashes };
