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
import { ACCESS_FAMILY } from './ribbonmodel.js';
import { unlistedLabelKey } from '../appdata.js';
import { t, type MessageKey } from '../i18n.js';
import type { Doc, El, WindowLike } from '../domtypes.js';
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

/** One drawable block of one lane sub-row (ribbonmodel's `RibbonStackBlock`).
 *
 *  No `owner`: this interface lists only the fields the RENDERER reads, and since the stack
 *  became text-free that is a block's start, end and public-ness — nothing else. The
 *  producer still carries the owner (`ribbonmodel`'s `RibbonStackBlock` keeps it, and the
 *  DetailPanel's Gantt writes it); it simply arrives here through the index signature and
 *  goes unread, which is what this type should say. */
export interface RenderStackBlock {
  start: string;
  end: string;
  public?: boolean;
  [k: string]: unknown;
}

/** One lane sub-row of a `lanestack` ribbon. */
export interface RenderStackLane {
  lane?: number;
  segments?: RenderStackBlock[];
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
  /** `lanestack` only: how many sub-rows the row is split into. */
  lane_count?: number;
  /** `lanestack` only: one entry per lane, in lane order. */
  strips?: RenderStackLane[];
  /** `lanestack` only: the session's best public window, ABSENT when there is none. */
  best_public?: { start: string; end: string; public_lanes?: number };
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

/** The access families whose colours the renderer resolves.
 *
 * DERIVED from `ACCESS_FAMILY`, not re-listed: a new access kind that got a family key but
 * no probe here would silently paint `undefined` on the canvas. */
const FAMILIES = [...new Set(Object.values(ACCESS_FAMILY))];

/**
 * resolveFamilyPalette(doc, host) — probe each `.fam-*` class for its computed colour,
 * so canvas fills come from tokens.css and this file holds no hex.
 *
 * Shared by the board and the phone tail: both paint the same families, and resolving
 * them from two separate lists is exactly how the surfaces would drift. Null headless.
 */
export function resolveFamilyPalette(doc: Doc, host: El): Palette | null {
  const view: WindowLike | null =
    doc.defaultView || (typeof window !== 'undefined' ? (window as unknown as WindowLike) : null);
  if (!view || typeof view.getComputedStyle !== 'function') return null;
  const probe = doc.createElement('span');
  probe.className = 'board__probe';
  host.appendChild(probe);
  const read = (cls: string): string => {
    probe.className = `board__probe ${cls}`;
    return view.getComputedStyle(probe).color;
  };
  const pal: Palette = {};
  for (const f of FAMILIES) pal[f] = read(`fam-${f}`);
  pal.other = read('fam-public');
  pal.closed = read('fam-closed');
  pal.unknown = read('fam-unknown');
  pal.sheath = read('fam-sheath');
  // The lane stack's own inks (lane-stack-board S4). Tokens, like every other fill here.
  pal.lanepublic = read('fam-lanepublic');
  pal.lanereserved = read('fam-lanereserved');
  pal.lanetrack = read('fam-lanetrack');
  pal.bestband = read('fam-bestband');
  pal.bestedge = read('fam-bestedge');
  pal.axis = read('fam-axis');
  pal.cursor = read('fam-cursor');
  pal.hair = read('fam-hair');
  pal.muted = read('fam-muted');
  host.removeChild?.(probe);
  return pal;
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
// dot, and NO text: the row label already carries "Closed · <detail>" (rowStatusLine),
// and the on-plot copy was painted centred on `mid` — i.e. its own dashed rule struck
// through it, in the same pal.closed colour, so it read as scribble. Deleted rather
// than nudged: the dot + rule already say "shut all day". Uncurated keeps its text —
// a dotted envelope + "Hours not listed", centred INSIDE the box, nothing across it.
// The text is a token colour (pal.*), never a raw hex.
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
    ctx.fillText(
      t(unlistedLabelKey(r.status as string | undefined)),
      (x0 + x1) / 2,
      mid,
    );
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

// ---- The lane stack (variant C) --------------------------------------------------
//
// One hairline sub-row per lane, inside the SAME row box the other variants use: within a
// row the stack subdivides rather than adding rows. (What the row's HEIGHT is, is the
// caller's business and not this file's: `board.ts::rowHeight` grows a plan-bearing row to
// `10 x lanes` so each band stays legible as a band, while the phone tail keeps its 46px
// `TAIL_H`. This module has always taken `h` and never seen either constant.)
//
// The stack paints NO TEXT. Public vs reserved fill says which lanes are free; WHOSE a
// reserved lane is, is read in the DetailPanel's Gantt (`gantt.ts` writes the owner into
// each segment box), one click away. The board's job at row scale is the shape.

/** The stack's box is the same 0.8h envelope `drawLaneRibbon` fills at full capacity. */
const STACK_BOX = 0.8;
/**
 * The shortest a lane band may be and still read as its own band rather than as a hairline
 * in a hatch. It is what SETS the board's row height: solving `h * STACK_BOX / n - 1 >=
 * LANE_BAND_MIN_H` gives `h >= 10n`, which is exactly `board.ts::rowHeight`.
 *
 * HISTORY, because the number is unchanged and its REASON is not: 7 first entered as
 * `OWNER_LABEL_MIN_H`, the height below which an owner name could not be set in type. The
 * board no longer writes owner names, so that gate is gone and the constant is re-founded
 * on the bands themselves — at six lanes a 46px row gives 5.13px bands, which stripe into
 * mush, against 8.2px at `10n`. Same arithmetic, a reason that still exists.
 */
export const LANE_BAND_MIN_H = 7;

/**
 * laneBands(laneCount, mid, h) → the sub-row geometry: `laneCount` bands, top to bottom,
 * inside the row's own box, whatever height that box is. PURE — the "n distinct sub-bands
 * within h" property is asserted here rather than inferred from a canvas.
 *
 * The 1px separator is dropped once the pitch is too tight to spare it: at 20 lanes a gap
 * would eat a third of each band, and touching bands still read as bands.
 */
export function laneBands(
  laneCount: number,
  mid: number,
  h: number,
): { top: number; height: number }[] {
  const n = Math.max(1, Math.floor(laneCount));
  const boxH = h * STACK_BOX;
  const top = mid - boxH / 2;
  const pitch = boxH / n;
  const gap = pitch > 4 ? 1 : 0;
  return Array.from({ length: n }, (_, i) => ({
    top: top + i * pitch,
    height: Math.max(1, pitch - gap),
  }));
}

/** The best-public window, painted BEHIND the stack (a band, never a lane). Absent when
 *  the option carries no window — a zero-width band would be a claim about 00:00. */
function drawBestPublicBand(
  ctx: Ctx2D,
  r: RenderRibbon,
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
): void {
  const win = r.best_public;
  if (!win) return;
  const x0 = ts.X(hhmmToMin(win.start));
  const x1 = ts.X(hhmmToMin(win.end));
  const boxH = h * STACK_BOX;
  const top = mid - boxH / 2 - 2;
  ctx.save();
  ctx.fillStyle = pal.bestband;
  ctx.fillRect(x0, top, Math.max(1, x1 - x0), boxH + 4);
  ctx.strokeStyle = pal.bestedge;
  ctx.lineWidth = 1;
  setDashes(ctx, 'solid');
  ctx.strokeRect(x0, top, Math.max(1, x1 - x0), boxH + 4);
  ctx.restore();
}

function drawLaneStack(
  ctx: Ctx2D,
  r: RenderRibbon,
  ts: Timescale,
  pal: Palette,
  mid: number,
  h: number,
): void {
  const x0 = ts.X(hhmmToMin(r.start ?? ''));
  const x1 = ts.X(hhmmToMin(r.end ?? ''));
  const w = Math.max(1, x1 - x0);
  const strips = r.strips ?? [];
  const bands = laneBands(Number(r.lane_count) || strips.length, mid, h);
  drawBestPublicBand(ctx, r, ts, pal, mid, h);
  ctx.save();
  for (const [i, band] of bands.entries()) {
    // The lane's own track: the capacity envelope, per lane. An EMPTY sub-row therefore
    // still shows a lane exists — "nobody holds it" reads differently from "no data".
    if (r.sheath) {
      ctx.fillStyle = pal.lanetrack || pal.sheath;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(x0, band.top, w, band.height);
    }
    drawLaneBlocks(ctx, strips[i]?.segments ?? [], ts, pal, band);
  }
  ctx.restore();
}

/** One lane's holds: public vs reserved fill, and NOTHING ELSE — no text.
 *
 * DELIBERATELY drops `r.family`, unlike its two sibling painters (`drawLaneRibbon`,
 * `drawUnpublishedRibbon`), which both resolve `(r.family ? pal[r.family] : undefined) ||
 * pal.other`: a lane block is coloured by whether the LANE is free, not by what the session
 * is. That is only safe because the two questions currently have the same answer — every
 * plan-bearing session served today is `PublicSwim` (measured: 1351 of 1351 options carrying
 * a `lane_day_view`, across all six lane facilities over 200 dates).
 *
 * The moment a WomenOnly / GirlsOnly / ClubReserved session appears on a basin with a parsed
 * Belegungsplan, this REGRESSES: its lanes would paint in the public teal under a legend row
 * reading "Lane open to the public" — exactly the "looks open to you" lie `ACCESS_FAMILY`
 * (ribbonmodel.ts:26-29) exists to prevent. Revisit here before such data ships. */
function drawLaneBlocks(
  ctx: Ctx2D,
  blocks: RenderStackBlock[],
  ts: Timescale,
  pal: Palette,
  band: { top: number; height: number },
): void {
  for (const seg of blocks) {
    const sx = ts.X(hhmmToMin(seg.start));
    const sw = Math.max(1, ts.X(hhmmToMin(seg.end)) - sx);
    ctx.globalAlpha = seg.public ? 0.9 : 0.75;
    ctx.fillStyle = seg.public ? pal.lanepublic : pal.lanereserved;
    ctx.fillRect(sx, band.top, sw, band.height);
  }
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
    } else if (r.variant === 'lanestack') {
      drawLaneStack(ctx, r, ts, pal, mid, h);
    } else if (r.variant === 'lanes') {
      drawLaneRibbon(ctx, r, ts, pal, mid, h, phase);
    } else {
      drawUnpublishedRibbon(ctx, r, ts, pal, mid, h);
    }
  }
}

export { setDashes };
