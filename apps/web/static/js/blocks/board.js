// board.js — the RibbonBoard block (plan Part 3 §4).
//
// Builds the board DOM subtree — an axis header, a sticky RowLabel column (status
// dot + EligibilityBadge), and a per-row horizontal-scroll canvas — and renders
// flowing water-ribbons onto each canvas. It is FilterState-driven: `mode` chooses
// Day (one row per pool) vs Pool (one row per day), and `gender`/`age` drive each
// row's eligibility badge.
//
// Layering: this BLOCK imports primitives (EligibilityBadge/StatePill), the shared
// `timescale` (the single X(min) mapping the future Gantt also imports — never
// re-derived here), the shared `eligibility` rule, and the pure `ribbonmodel`. It
// introduces NO colour: canvas fills are resolved at runtime from the CSS `.fam-*`
// classes (blocks.css → tokens.css), so there is no raw hex in this file.

import { makeTimescale } from '../timescale.js';
import { eligForAccess, dayEligibility } from '../eligibility.js';
import { ribbonsFor } from './ribbonmodel.js';
import { cursorX as sharedCursorX, hhmmToMin } from './cursor.js';
import { createEligibilityBadge } from '../components/eligibilitybadge.js';

// Default board window [06:00, 22:00] across a 900px plot. The plot width is the
// canvas' intrinsic (scrollable) width; the card clips it via overflow-x:auto.
export const BOARD_DAY0 = 6;
export const BOARD_DAY1 = 22;
export const BOARD_PLOT = 900;

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const ROW_H = 46; // canvas height in CSS px
const FAMILIES = ['public', 'lane', 'family', 'women', 'seniors', 'adults', 'school', 'club'];

// "HH:MM" → minutes-of-day. Re-exported from the shared cursor leaf so the board,
// the Gantt, and the panel all parse times through ONE function (the duplicated
// two-line copy that used to live here is gone — F carried nit).
export { hhmmToMin };

// ---- Row derivation (pure, exported for unit tests) -----------------------------

/** Day mode: group a `/swim` answer's options + statuses into one row per facility,
 *  preserving first-seen order. */
export function dayRows(answer) {
  const byFacility = new Map();
  const rowFor = (name) => {
    if (!byFacility.has(name)) byFacility.set(name, { label: name, options: [], statuses: [] });
    return byFacility.get(name);
  };
  for (const o of answer.options || []) rowFor(o.facility).options.push(o);
  for (const s of answer.statuses || []) rowFor(s.facility).statuses.push(s);
  return [...byFacility.values()];
}

/** Pool mode: one row per day of the captured week. `week` is
 *  `{ facility, days: [{ label, answer }] }`. */
export function weekRows(week) {
  return (week.days || []).map((d) => ({
    label: d.label,
    options: d.answer.options || [],
    statuses: d.answer.statuses || [],
  }));
}

/** Build the row list for the given FilterState from the preloaded `data`
 *  (`{ day: answer, week: {facility, days} }`). */
export function boardRows(data, filter) {
  if (filter.mode === 'pool' && data.week) return weekRows(data.week);
  if (data.day) return dayRows(data.day);
  return [];
}

/** A row's eligibility badge state, from its options under the current gender/age. */
export function rowEligibility(row, filter) {
  const states = row.options.map((o) => eligForAccess(o.access, filter.gender, filter.age));
  return dayEligibility(states);
}

/** A row's status-dot state: open (has options) / closed / unknown. */
export function rowStatus(row) {
  if (row.options.length > 0) return 'open';
  if (row.statuses.some((s) => s.status === 'closed')) return 'closed';
  return 'unknown';
}

// ---- Colour resolution (runtime, browser only) ----------------------------------

// Resolve each family/semantic colour by probing a CSS `.fam-*` class and reading the
// computed `color`. Keeps ALL colour in tokens.css; returns null headless (no browser).
function resolvePalette(doc, host) {
  const view = doc.defaultView || (typeof window !== 'undefined' ? window : null);
  if (!view || typeof view.getComputedStyle !== 'function') return null;
  const probe = doc.createElement('span');
  probe.className = 'board__probe';
  host.appendChild(probe);
  const read = (cls) => {
    probe.className = `board__probe ${cls}`;
    return view.getComputedStyle(probe).color;
  };
  const pal = {};
  for (const f of FAMILIES) pal[f] = read(`fam-${f}`);
  pal.other = read('fam-public');
  pal.closed = read('fam-closed');
  pal.unknown = read('fam-unknown');
  pal.sheath = read('fam-sheath');
  pal.axis = read('fam-axis');
  host.removeChild(probe);
  return pal;
}

// ---- Canvas rendering -----------------------------------------------------------

function setDashes(ctx, style) {
  if (style === 'dashed') ctx.setLineDash([9, 6]);
  else if (style === 'dotted') ctx.setLineDash([2, 5]);
  else ctx.setLineDash([]);
}

// Draw one row's ribbons. `phase` animates the waterline (0 when frozen).
function drawRow(canvas, ribbons, ts, pal, phase) {
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx || !pal) return; // headless / no canvas → nothing to paint (logic already tested)
  const w = ts.PLOT;
  const h = ROW_H;
  ctx.clearRect(0, 0, w, h);
  const mid = h / 2;

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

function drawStatusRibbon(ctx, r, ts, pal, mid) {
  // Closed = dashed, ghost/uncurated = dotted; both span the whole plot as a thin rule.
  ctx.save();
  ctx.strokeStyle = r.variant === 'closed' ? pal.closed : pal.unknown;
  ctx.lineWidth = 1.5;
  setDashes(ctx, r.style);
  ctx.beginPath();
  ctx.moveTo(2, mid);
  ctx.lineTo(ts.PLOT - 2, mid);
  ctx.stroke();
  ctx.restore();
}

function drawUnpublishedRibbon(ctx, r, ts, pal, mid, h) {
  const x0 = ts.X(hhmmToMin(r.start));
  const x1 = ts.X(hhmmToMin(r.end));
  const col = pal[r.family] || pal.other;
  ctx.save();
  ctx.fillStyle = pal.sheath;
  ctx.globalAlpha = 0.5;
  ctx.fillRect(x0, mid - h * 0.28, Math.max(1, x1 - x0), h * 0.56);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = col;
  ctx.lineWidth = 1;
  setDashes(ctx, 'dotted');
  ctx.strokeRect(x0, mid - h * 0.28, Math.max(1, x1 - x0), h * 0.56);
  ctx.restore();
}

function drawLaneRibbon(ctx, r, ts, pal, mid, h, phase) {
  const col = pal[r.family] || pal.other;
  const maxHalf = h * 0.4; // full capacity half-height
  for (const seg of r.segments) {
    const x0 = ts.X(hhmmToMin(seg.start));
    const x1 = ts.X(hhmmToMin(seg.end));
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
    const half = Math.max(1, maxHalf * seg.thickness * (seg.pinched ? 0.72 : 1));
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

function drawAxis(canvas, ts, pal) {
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx || !pal) return;
  ctx.clearRect(0, 0, ts.PLOT, 18);
  ctx.save();
  ctx.font = '10px system-ui, sans-serif';
  ctx.textBaseline = 'top';
  ctx.fillStyle = pal.axis;
  for (let hour = ts.DAY0; hour <= ts.DAY1; hour += 2) {
    const x = ts.X(hour * 60);
    ctx.fillText(`${String(hour).padStart(2, '0')}:00`, Math.min(x + 2, ts.PLOT - 26), 3);
  }
  ctx.restore();
}

// ---- DOM build + lifecycle ------------------------------------------------------

function makeScrollCell(doc, plot, canvasClass, height) {
  const scrollx = doc.createElement('div');
  scrollx.className = 'board__scrollx';
  const track = doc.createElement('div');
  track.className = 'board__track';
  // No inline width: the canvas' own width (below) is the intrinsic content and
  // `.board__track { width: max-content }` (blocks.css) governs the track width.
  const canvas = doc.createElement('canvas');
  canvas.className = canvasClass;
  canvas.width = plot;
  canvas.height = height;
  canvas.style.width = `${plot}px`;
  canvas.style.height = `${height}px`;
  track.appendChild(canvas);
  scrollx.appendChild(track);
  return { scrollx, canvas };
}

/**
 * createBoard(el, opts) — mount the RibbonBoard into `el`.
 * @param {object} opts
 * @param {object} opts.data  `{ day: AnswerOut, week: {facility, days:[{label,answer}]} }`.
 * @param {object} opts.filter FilterState (mode/gender/age drive the render).
 * @param {object} [opts.timescale] shared timescale (defaults to the board window).
 * @param {function} [opts.matchMedia] injectable matchMedia (reduced-motion probe).
 * @param {function} [opts.requestAnimationFrame] injectable RAF (animation loop).
 * @returns {{el, reducedMotion:boolean, rows:Array, setFilter:function, destroy:function}}
 */
export function createBoard(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const ts = opts.timescale || makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const mm = opts.matchMedia || (typeof globalThis.matchMedia === 'function' ? globalThis.matchMedia : null);
  const raf = opts.requestAnimationFrame || (typeof globalThis.requestAnimationFrame === 'function' ? globalThis.requestAnimationFrame : null);
  const reducedMotion = !!(mm && mm(REDUCED_MOTION_QUERY).matches);

  let filter = opts.filter || { mode: 'day', gender: '', age: null };
  let data = opts.data || {};

  el.classList.add('stage');
  const board = doc.createElement('div');
  board.className = 'board';
  el.appendChild(board);

  // Axis header row: an empty label spacer + a scroll cell carrying the tick canvas.
  const axisRow = doc.createElement('div');
  axisRow.className = 'board__row board__row--axis';
  const axisSpacer = doc.createElement('div');
  axisSpacer.className = 'board__rowlabel board__rowlabel--head';
  const axisCell = makeScrollCell(doc, ts.PLOT, 'board__axiscanvas', 18);
  axisRow.appendChild(axisSpacer);
  axisRow.appendChild(axisCell.scrollx);
  board.appendChild(axisRow);

  const body = doc.createElement('div');
  body.className = 'board__body';
  board.appendChild(body);

  const pal = resolvePalette(doc, board);
  // One entry per data row: { canvas, row, ribbons, animated }. `ribbons` is
  // computed ONCE here (not per frame — the old paint re-ran ribbonsFor for all 58
  // rows every frame, pure allocation churn) and `animated` flags the ~1–2 rows that
  // carry a flowing lane ribbon. Only those are redrawn in the RAF loop; the ~55
  // static ghost/closed/unpublished rows are painted once and never touched again.
  const canvases = [];

  // A row animates only if it has a lane ribbon whose waterline the `phase` moves.
  // Status ghosts/closed rules and unpublished sheaths are phase-independent → static.
  function isAnimated(ribbons) {
    return ribbons.some((r) => r.kind !== 'status' && r.variant === 'lanes');
  }

  function buildRows() {
    body.textContent = '';
    canvases.length = 0;
    const rows = boardRows(data, filter);
    for (const row of rows) {
      const rowEl = doc.createElement('div');
      rowEl.className = 'board__row';

      // --- sticky RowLabel column: status dot + name + EligibilityBadge ---
      const label = doc.createElement('div');
      label.className = 'board__rowlabel';
      const dot = doc.createElement('span');
      dot.className = `board__dot board__dot--${rowStatus(row)}`;
      dot.setAttribute('aria-hidden', 'true');
      const name = doc.createElement('span');
      name.className = 'board__rowname';
      name.textContent = row.label;
      label.appendChild(dot);
      label.appendChild(name);
      if (row.options.length > 0) {
        const badge = doc.createElement('span');
        badge.className = 'board__rowbadge';
        createEligibilityBadge(badge, {
          props: { state: rowEligibility(row, filter), variant: 'tag' },
        });
        label.appendChild(badge);
      }

      // --- canvas column: one horizontally-scrollable canvas per row ---
      const cell = makeScrollCell(doc, ts.PLOT, 'board__canvas', ROW_H);
      rowEl.appendChild(label);
      rowEl.appendChild(cell.scrollx);
      body.appendChild(rowEl);
      const ribbons = ribbonsFor(row);
      canvases.push({ canvas: cell.canvas, row, ribbons, animated: isAnimated(ribbons) });
    }
    return rows;
  }

  let rows = buildRows();

  // Full frame: axis + EVERY row painted once (at `phase`). The axis and the static
  // rows never change with time, so this is the ONLY place they are drawn — after
  // this, the RAF loop only re-touches the animated ribbons.
  function paintStatic(phase = 0) {
    drawAxis(axisCell.canvas, ts, pal);
    for (const { canvas, ribbons } of canvases) drawRow(canvas, ribbons, ts, pal, phase);
  }

  // Per-frame work: redraw ONLY the rows with a moving waterline (~1–2 curated
  // ribbons), not all 58 canvases. The precomputed `ribbons` avoids per-frame alloc.
  function paintAnimated(phase) {
    for (const { canvas, ribbons, animated } of canvases) {
      if (animated) drawRow(canvas, ribbons, ts, pal, phase);
    }
  }

  // Reduced motion → paint a single frozen frame, no RAF loop. Otherwise paint the
  // static frame once, then animate only the moving ribbons in one shared RAF loop.
  let running = false;
  function loop(t) {
    paintAnimated((t || 0) / 600);
    if (running && raf) raf(loop);
  }
  paintStatic(0);
  if (!reducedMotion && raf) {
    running = true;
    raf(loop);
  }

  function setFilter(next) {
    filter = next;
    rows = buildRows();
    paintStatic(0);
  }

  function setData(next) {
    data = next;
    rows = buildRows();
    paintStatic(0);
  }

  function destroy() {
    running = false; // stop the shared RAF loop so a rebuilt board leaves no orphan
    if (board.parentNode === el) el.removeChild(board);
  }

  // The board's cursor-x for minute `min`, routed through the SHARED cursor helper
  // over the board's OWN timescale `ts`. The Gantt computes its cursor-x the same
  // way (gantt.js → cursorX(ts, min)); handed the same `ts`, board.cursorX(T) ===
  // gantt.cursorPlotX(T) BY CONSTRUCTION — and a Gantt given its own scale diverges.
  // This is the anti-desync anchor the S5 DOM-contract test asserts directly.
  function cursorXAt(min) {
    return sharedCursorX(ts, min);
  }

  return {
    el,
    board,
    reducedMotion,
    timescale: ts,
    cursorX: cursorXAt,
    get rows() {
      return rows;
    },
    setFilter,
    setData,
    destroy,
  };
}
