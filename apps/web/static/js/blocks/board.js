// board.js — the RibbonBoard block (plan Part 3 §4).
//
// Builds the board DOM subtree and renders flowing water-ribbons onto each row's
// canvas. It is FilterState-driven: `mode` chooses Day (one row per pool) vs Pool
// (one row per day of the selected pool's week), and `gender`/`age` drive each
// row's eligibility badge.
//
// SHARED HORIZONTAL SCROLL (the prototype's layout, restored): the board is ONE
// 2-column grid — a fixed, non-scrolling label column + a single `overflow-x:auto`
// track that holds the time-axis header canvas AND every row canvas stacked. So the
// axis and ALL rows scroll together and the time labels stay aligned to the ribbons
// below them (the old per-row scroll moved a single row and desynced the axis). The
// canvas column is `minmax(0,1fr)` so the wide (max-content) track scrolls INSIDE
// the card instead of pushing the page sideways (the S2 containment contract).
//
// Layering: this BLOCK imports primitives (EligibilityBadge), the shared `timescale`
// (the single X(min) mapping the Gantt also imports — never re-derived here), the
// shared `eligibility` rule, and the pure `ribbonmodel`. It introduces NO colour:
// canvas fills are resolved at runtime from the CSS `.fam-*` classes (blocks.css →
// tokens.css), so there is no raw hex in this file.

import { makeTimescale } from '../timescale.js';
import { eligForAccess, dayEligibility } from '../eligibility.js';
import { ribbonsFor } from './ribbonmodel.js';
import { cursorX as sharedCursorX, hhmmToMin } from './cursor.js';
import { createEligibilityBadge } from '../components/eligibilitybadge.js';
import { formatLabel } from '../components/datestepper.js';

// Default board window [06:00, 22:00] across a 900px plot. The plot width is the
// canvas' intrinsic (scrollable) width; the card clips it via overflow-x:auto.
export const BOARD_DAY0 = 6;
export const BOARD_DAY1 = 22;
export const BOARD_PLOT = 900;

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const ROW_H = 46; // row canvas height in CSS px (label cells match this exactly)
const AXIS_H = 20; // axis header canvas + head-label height, matched for alignment
const FAMILIES = ['public', 'lane', 'family', 'women', 'seniors', 'adults', 'school', 'club'];

// "HH:MM" → minutes-of-day. Re-exported from the shared cursor leaf so the board,
// the Gantt, and the panel all parse times through ONE function.
export { hhmmToMin };

// ---- Row derivation (pure, exported for unit tests) -----------------------------

/** Day mode: group a `/swim` answer's options + statuses into one row per facility,
 *  preserving first-seen order (the API already orders nearest-first). */
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
 *  `{ facility, days: [{ label, date|iso, answer }] }`. Each row keeps its ISO
 *  `date` so the label can show the weekday + DATE and mark today. */
export function weekRows(week) {
  return (week.days || []).map((d) => ({
    label: d.label,
    date: d.date != null ? d.date : d.iso,
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

// A gender/age filter is "engaged" once the viewer picks a specific gender or age —
// only then do we stamp the per-row ✓/?/✕ badge (Anyone + Any age → no badge, since
// every session is open to everyone and there is nothing personal to flag). Toggling
// a gender/age therefore VISIBLY adds/updates the badges (plan item 6).
function eligEngaged(filter) {
  return !!(filter && ((filter.gender && filter.gender !== '') || filter.age != null));
}

/** Pool-mode row label: "Mon · 20 Jul", derived from the row's ISO date. */
function weekdayDateLabel(row) {
  if (!row.date) return row.label;
  const parts = formatLabel(row.date).split(' '); // ["Mon","20","Jul"]
  if (parts.length < 3) return row.label;
  return `${parts[0]} · ${parts[1]} ${parts[2]}`;
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
  pal.hair = read('fam-hair');
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
  // A faint top hairline separates rows (drawn here so the canvas keeps its exact
  // ROW_H height — a CSS border would shrink the drawing box and blur the ribbon).
  ctx.save();
  ctx.strokeStyle = pal.hair || pal.axis;
  ctx.globalAlpha = 0.9;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, 0.5);
  ctx.lineTo(w, 0.5);
  ctx.stroke();
  ctx.restore();
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

// A published-hours-but-NO-lane-split ribbon (plan item 5): a faint capacity sheath
// with a HATCHED (dotted-outline + diagonal hatch) fill so it reads clearly as
// "open, lane split not published" — never as a solid public block.
function drawUnpublishedRibbon(ctx, r, ts, pal, mid, h) {
  const x0 = ts.X(hhmmToMin(r.start));
  const x1 = ts.X(hhmmToMin(r.end));
  const wSeg = Math.max(1, x1 - x0);
  const top = mid - h * 0.24;
  const height = h * 0.48;
  const col = pal[r.family] || pal.other;
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
  ctx.clearRect(0, 0, ts.PLOT, AXIS_H);
  ctx.save();
  ctx.font = '10px system-ui, sans-serif';
  ctx.textBaseline = 'bottom';
  ctx.fillStyle = pal.axis;
  for (let hour = ts.DAY0; hour <= ts.DAY1; hour += 2) {
    const x = ts.X(hour * 60);
    // a short tick + the hour label, both anchored at the same x as the ribbons below
    ctx.globalAlpha = 0.5;
    ctx.fillRect(Math.min(x, ts.PLOT - 1), AXIS_H - 6, 1, 6);
    ctx.globalAlpha = 1;
    ctx.fillText(`${String(hour).padStart(2, '0')}:00`, Math.min(x + 2, ts.PLOT - 26), AXIS_H - 7);
  }
  ctx.restore();
}

// ---- DOM build + lifecycle ------------------------------------------------------

/**
 * createBoard(el, opts) — mount the RibbonBoard into `el`.
 * @param {object} opts
 * @param {object} opts.data  `{ day: AnswerOut, week: {facility, days:[{label,date,answer}]} }`.
 * @param {object} opts.filter FilterState (mode/gender/age drive the render).
 * @param {string} [opts.today] the ISO "today" so Pool-mode rows can mark TODAY.
 * @param {object} [opts.timescale] shared timescale (defaults to the board window).
 * @param {function} [opts.matchMedia] injectable matchMedia (reduced-motion probe).
 * @param {function} [opts.requestAnimationFrame] injectable RAF (animation loop).
 * @returns {{el, board, reducedMotion:boolean, timescale, cursorX, rows,
 *            setFilter, setData, destroy}}
 */
export function createBoard(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const ts = opts.timescale || makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const mm = opts.matchMedia || (typeof globalThis.matchMedia === 'function' ? globalThis.matchMedia : null);
  const raf = opts.requestAnimationFrame || (typeof globalThis.requestAnimationFrame === 'function' ? globalThis.requestAnimationFrame : null);
  const reducedMotion = !!(mm && mm(REDUCED_MOTION_QUERY).matches);

  let filter = opts.filter || { mode: 'day', gender: '', age: null };
  let data = opts.data || {};
  let today = opts.today || null;

  el.classList.add('stage');
  const board = doc.createElement('div');
  board.className = 'board';
  el.appendChild(board);

  // Column 1: the fixed, non-scrolling label stack (axis corner + one cell per row).
  const labels = doc.createElement('div');
  labels.className = 'board__labels';
  // Column 2: the ONE shared horizontal-scroll track (axis canvas + every row canvas).
  const scrollx = doc.createElement('div');
  scrollx.className = 'board__scrollx';
  const track = doc.createElement('div');
  track.className = 'board__track';
  scrollx.appendChild(track);
  board.appendChild(labels);
  board.appendChild(scrollx);

  // Axis header: a head label (identity / caption) beside the tick canvas.
  const headLabel = doc.createElement('div');
  headLabel.className = 'board__rowlabel board__rowlabel--head';
  headLabel.style.height = `${AXIS_H}px`;
  labels.appendChild(headLabel);
  const axisCanvas = doc.createElement('canvas');
  axisCanvas.className = 'board__axiscanvas';
  axisCanvas.width = ts.PLOT;
  axisCanvas.height = AXIS_H;
  axisCanvas.style.width = `${ts.PLOT}px`;
  axisCanvas.style.height = `${AXIS_H}px`;
  track.appendChild(axisCanvas);

  // The per-row cells live in dedicated body containers so a rebuild clears just the
  // rows (textContent='') and leaves the axis header/canvas in place.
  const labelsBody = doc.createElement('div');
  labelsBody.className = 'board__labelsbody';
  labels.appendChild(labelsBody);
  const trackBody = doc.createElement('div');
  trackBody.className = 'board__trackbody';
  track.appendChild(trackBody);

  const pal = resolvePalette(doc, board);
  // One entry per data row: { canvas, row, ribbons, animated }. `ribbons` is computed
  // ONCE here (not per frame); only the ~1–2 rows carrying a flowing lane ribbon are
  // redrawn in the RAF loop — the static ghost/closed/unpublished rows are painted once.
  const canvases = [];

  function isAnimated(ribbons) {
    return ribbons.some((r) => r.kind !== 'status' && r.variant === 'lanes');
  }

  // The identity caption shown in the axis corner: in Pool mode the selected pool's
  // name (+ its basin(s)), so the board itself surfaces WHICH pool it is (plan item 3).
  function headCaption(rows) {
    if (filter.mode === 'pool') {
      const name = filter.pool && filter.pool.label ? filter.pool.label : (data.week && data.week.facility) || 'Pool';
      const basins = [...new Set(rows.flatMap((r) => r.options.map((o) => o.basin)).filter(Boolean))];
      return basins.length ? `${name} · ${basins.join(' / ')}` : name;
    }
    return 'Nearest first';
  }

  function buildRows() {
    labelsBody.textContent = '';
    trackBody.textContent = '';
    canvases.length = 0;
    const rows = boardRows(data, filter);
    headLabel.textContent = headCaption(rows);

    for (const row of rows) {
      // --- label cell (column 1, non-scrolling) ---
      const label = doc.createElement('div');
      label.className = 'board__rowlabel';
      label.style.height = `${ROW_H}px`;
      const dot = doc.createElement('span');
      dot.className = `board__dot board__dot--${rowStatus(row)}`;
      dot.setAttribute('aria-hidden', 'true');
      label.appendChild(dot);

      const name = doc.createElement('span');
      name.className = 'board__rowname';
      if (filter.mode === 'pool') {
        name.textContent = weekdayDateLabel(row);
        if (today && row.date === today) label.classList.add('board__rowlabel--today');
      } else {
        name.textContent = row.label;
      }
      label.appendChild(name);

      if (filter.mode === 'pool' && today && row.date === today) {
        const tag = doc.createElement('span');
        tag.className = 'board__todaytag';
        tag.textContent = 'Today';
        label.appendChild(tag);
      }

      // Eligibility badge — only once a gender/age filter is engaged (so toggling a
      // filter visibly changes the board), and only on rows that have sessions.
      const elig = row.options.length > 0 ? rowEligibility(row, filter) : null;
      if (elig && eligEngaged(filter)) {
        const badge = doc.createElement('span');
        badge.className = 'board__rowbadge';
        createEligibilityBadge(badge, { props: { state: elig, variant: 'tag' } });
        label.appendChild(badge);
        if (elig === 'no') label.classList.add('board__rowlabel--noelig');
      }
      labelsBody.appendChild(label);

      // --- row canvas (column 2, inside the shared scroll track) ---
      const canvas = doc.createElement('canvas');
      canvas.className = 'board__canvas';
      canvas.width = ts.PLOT;
      canvas.height = ROW_H;
      canvas.style.width = `${ts.PLOT}px`;
      canvas.style.height = `${ROW_H}px`;
      if (elig === 'no' && eligEngaged(filter)) canvas.classList.add('board__canvas--noelig');
      trackBody.appendChild(canvas);

      const ribbons = ribbonsFor(row);
      canvases.push({ canvas, row, ribbons, animated: isAnimated(ribbons) });
    }
    return rows;
  }

  let rows = buildRows();

  function paintStatic(phase = 0) {
    drawAxis(axisCanvas, ts, pal);
    for (const { canvas, ribbons } of canvases) drawRow(canvas, ribbons, ts, pal, phase);
  }

  function paintAnimated(phase) {
    for (const { canvas, ribbons, animated } of canvases) {
      if (animated) drawRow(canvas, ribbons, ts, pal, phase);
    }
  }

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
  // gantt.cursorPlotX(T) BY CONSTRUCTION. This is the anti-desync anchor the
  // board_gantt_align test asserts directly.
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
