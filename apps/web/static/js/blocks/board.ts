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
import {
  asCanvas,
  closureLabel,
  drawRibbons,
  resolveFamilyPalette,
  type CanvasEl,
  type Palette,
  type Timescale,
} from './ribbonrender.js';
import { cursorX as sharedCursorX, hhmmToMin } from './cursor.js';
import { fairWeatherText, isUnlisted, unlistedLabelKey } from '../appdata.js';
import { createEligibilityBadge } from '../components/eligibilitybadge.js';
import { dayParts } from '../datefmt.js';
import { asDoc, type El } from '../domtypes.js';
import { locale, t } from '../i18n.js';


// ---- Local structural types (the urlstate.ts convention) ---------------------------

/** A `/swim` option, read structurally — only the fields the board projects. */
export interface BoardOption {
  facility: string;
  facility_id?: string;
  basin?: string;
  access?: string;
  distance_km?: number | null;
  start?: string;
  end?: string;
  /** 'any' | 'fair_only' — whether the city publishes this block unconditionally. */
  weather?: string;
  [k: string]: unknown;
}

/** A `/swim` facility status. */
export interface BoardStatus {
  facility: string;
  status: string;
  detail?: string | null;
}

/** One board row: a facility (Day mode) or a day (Pool mode). */
export interface BoardRow {
  label: string;
  date?: string | null;
  options: BoardOption[];
  statuses: BoardStatus[];
}

export interface BoardAnswer {
  options: BoardOption[];
  statuses: BoardStatus[];
}

export interface BoardWeek {
  facility?: string | null;
  days: { label: string; date?: string; iso?: string; answer: BoardAnswer }[];
}

export interface BoardData {
  day?: BoardAnswer;
  week?: BoardWeek;
}

export interface BoardFilter {
  mode: string;
  gender?: string;
  age?: number | null;
  selectedPool?: { id?: string | null; name?: string | null } | null;
}

/** The runtime-resolved colour table, and the canvas/timescale surfaces, now live with
 *  the shared renderer. Re-exported here so existing importers keep working. */
export type { Palette, Timescale, CanvasEl } from './ribbonrender.js';
// closureLabel moved to ribbonrender.ts with its only caller (drawStatusRibbon);
// re-exported so existing importers (stateblocks.ts) are unaffected.
export { closureLabel } from './ribbonrender.js';

/** A ribbon from ribbonmodel.js, read structurally. */
export interface RibbonSegment {
  start: string;
  end: string;
  family?: string;
  publicLanes?: number;
  laneCount?: number;
  [k: string]: unknown;
}

export interface Ribbon {
  kind?: string;
  variant?: string;
  family?: string;
  style?: string;
  facility?: string;
  detail?: string | null;
  label?: string;
  start?: string;
  end?: string;
  segments?: RibbonSegment[];
  [k: string]: unknown;
}

// Default board window [06:00, 22:00] across a 900px plot. The plot width is the
// canvas' intrinsic (scrollable) width; the card clips it via overflow-x:auto.
export const BOARD_DAY0 = 6;
export const BOARD_DAY1 = 22;
export const BOARD_PLOT = 900;

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const ROW_H = 46; // row canvas height in CSS px (label cells match this exactly)
const AXIS_H = 20; // axis header canvas + head-label height, matched for alignment

// "HH:MM" → minutes-of-day. Re-exported from the shared cursor leaf so the board,
// the Gantt, and the panel all parse times through ONE function.
export { hhmmToMin };

// ---- Row derivation (pure, exported for unit tests) -----------------------------

/** Day mode: group a `/swim` answer's options + statuses into one row per facility,
 *  preserving first-seen order (the API already orders nearest-first). */
export function dayRows(answer: BoardAnswer): BoardRow[] {
  const byFacility = new Map<string, BoardRow>();
  const rowFor = (name: string): BoardRow => {
    if (!byFacility.has(name)) byFacility.set(name, { label: name, options: [], statuses: [] });
    return byFacility.get(name) as BoardRow;
  };
  for (const o of answer.options || []) rowFor(o.facility).options.push(o);
  for (const s of answer.statuses || []) rowFor(s.facility).statuses.push(s);
  return [...byFacility.values()];
}

/** Pool mode: one row per day of the captured week. `week` is
 *  `{ facility, days: [{ label, date|iso, answer }] }`. Each row keeps its ISO
 *  `date` so the label can show the weekday + DATE and mark today. */
export function weekRows(week: BoardWeek): BoardRow[] {
  return (week.days || []).map((d) => ({
    label: d.label,
    date: d.date != null ? d.date : d.iso,
    options: d.answer.options || [],
    statuses: d.answer.statuses || [],
  }));
}

/** Build the row list for the given FilterState from the preloaded `data`
 *  (`{ day: answer, week: {facility, days} }`). */
export function boardRows(data: BoardData, filter: BoardFilter): BoardRow[] {
  if (filter.mode === 'pool' && data.week) return weekRows(data.week);
  if (data.day) return dayRows(data.day);
  return [];
}

/** A row's eligibility badge state, from its options under the current gender/age. */
export function rowEligibility(
  row: { options: { access?: string }[] },
  filter: { gender?: string; age?: number | null },
) {
  const states = row.options.map((o) => eligForAccess(o.access ?? '', filter.gender, filter.age));
  return dayEligibility(states);
}

/** A row's status-dot state: open (has options) / closed / unknown. */
export function rowStatus(row: {
  options: unknown[];
  statuses: { status: string }[];
}): string {
  if (row.options.length > 0) return 'open';
  if (row.statuses.some((s) => s.status === 'closed')) return 'closed';
  return 'unknown';
}

/** A non-open row's compact status line for the label AND the canvas (plan FIX 1):
 *  closed → `Closed · <detail>` (keeps its reason), uncurated → `Hours not listed`.
 *  Returns null for an open row (its ribbons say everything). Pure, exported for tests. */
/** The human label for a closed status, from its S4 closure code.
 *
 * Falls back to the server's prose only when no code is present at all (an older payload)
 * — never invents a reason, and never blanks one we were given. */

export function rowStatusLine(row: {
  options?: unknown[];
  statuses?: {
    status: string;
    detail?: string | null;
    detail_code?: string;
    closure_code?: string | null;
    detail_params?: Record<string, string>;
  }[];
}) {
  if ((row.options || []).length > 0) return null;
  const closed = (row.statuses || []).find((s) => s.status === 'closed');
  if (closed) {
    // S4: rendered from the CLASSIFIED closure code. `unmapped` still interpolates the
    // curated German verbatim — an unrecognised phrase must read as the truth, not as a
    // blank (the builder has already reported it on stderr).
    const reason = closureLabel(closed);
    return {
      kind: 'closed',
      text: reason ? t('status.closed_reason', { reason }) : t('status.closed'),
    };
  }
  const unlisted = (row.statuses || []).find((s) => isUnlisted(s.status));
  if (unlisted) {
    // Render the SPECIFIC freshness label (awaiting_scrape vs no_source), never a merged bucket.
    return { kind: 'unknown', text: t(unlistedLabelKey(unlisted.status)) };
  }
  return null;
}

// A gender/age filter is "engaged" once the viewer picks a specific gender or age —
// only then do we stamp the per-row ✓/?/✕ badge (Anyone + Any age → no badge, since
// every session is open to everyone and there is nothing personal to flag). Toggling
// a gender/age therefore VISIBLY adds/updates the badges (plan item 6).
function eligEngaged(filter: BoardFilter | null | undefined): boolean {
  return !!(filter && ((filter.gender && filter.gender !== '') || filter.age != null));
}

/**
 * Pool-mode row label: "Mon · 20 Jul", derived from the row's ISO date.
 *
 * Reads the NAMED parts from `Intl` rather than splitting a formatted string on spaces.
 * The old version did `formatLabel(row.date).split(' ')` and indexed [0][1][2], which
 * silently fell back to `row.label` for any locale that does not format a date as
 * exactly three space-separated tokens — i.e. most of them.
 */
function weekdayDateLabel(row: BoardRow): string {
  if (!row.date) return row.label;
  const { weekday, day, month } = dayParts(row.date, locale());
  if (!weekday || !day || !month) return row.label;
  // eslint-disable-next-line i18next/no-literal-string -- punctuation between Intl-formatted parts, not copy
  return `${weekday} · ${day} ${month}`;
}

// ---- Colour resolution (runtime, browser only) ----------------------------------


// ---- Canvas rendering -----------------------------------------------------------

// Draw one row's ribbons. The ribbon painting itself lives in ribbonrender.ts (shared
// with the phone day tail); what stays here is board-specific chrome: the row hairline
// and the ROW_H box. `phase` animates the waterline (0 when frozen).
function drawRow(
  canvas: CanvasEl,
  ribbons: Ribbon[],
  ts: Timescale,
  pal: Palette | null,
  phase: number,
): void {
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;
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
  drawRibbons(ctx, ribbons, ts, pal, h / 2, h, phase);
}

function drawAxis(canvas: CanvasEl, ts: Timescale, pal: Palette | null) {
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

export interface BoardOpts {
  timescale?: Timescale;
  matchMedia?: (q: string) => { matches: boolean };
  requestAnimationFrame?: (cb: (t: number) => void) => number | void;
  filter?: BoardFilter;
  data?: BoardData;
  today?: string | null;
  onPick?: (...args: unknown[]) => void;
  onCursor?: (...args: unknown[]) => void;
  [k: string]: unknown;
}

export function createBoard<T extends El>(el: T, opts: BoardOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const ts = opts.timescale || makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const mm = opts.matchMedia || (typeof globalThis.matchMedia === 'function' ? globalThis.matchMedia : null);
  const raf = opts.requestAnimationFrame || (typeof globalThis.requestAnimationFrame === 'function' ? globalThis.requestAnimationFrame : null);
  const reducedMotion = !!(mm && mm(REDUCED_MOTION_QUERY).matches);

  let filter = opts.filter || { mode: 'day', gender: '', age: null };
  let data = opts.data || {};
  const today = opts.today || null;

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
  const axisCanvas = asCanvas(doc.createElement('canvas'));
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

  const pal = resolveFamilyPalette(doc, board);
  // One entry per data row: { canvas, row, ribbons, animated }. `ribbons` is computed
  // ONCE here (not per frame); only the ~1–2 rows carrying a flowing lane ribbon are
  // redrawn in the RAF loop — the static ghost/closed/unpublished rows are painted once.
  const canvases: { canvas: CanvasEl; row: BoardRow; ribbons: Ribbon[]; animated: boolean }[] = [];

  function isAnimated(ribbons: Ribbon[]): boolean {
    return ribbons.some((r: Ribbon) => r.kind !== 'status' && r.variant === 'lanes');
  }

  // The identity caption shown in the axis corner: in Pool mode the selected pool's
  // name (+ its basin(s)), so the board itself surfaces WHICH pool it is (plan item 3).
  function headCaption(rows: BoardRow[]): string {
    if (filter.mode === 'pool') {
      const name = filter.selectedPool?.name ? filter.selectedPool.name : (data.week && data.week.facility) || t('detail.pool');
      const basins = [
        ...new Set(rows.flatMap((r) => r.options.map((o) => o.basin)).filter(Boolean)),
      ];
      // eslint-disable-next-line i18next/no-literal-string -- punctuation between proper nouns, not copy
  return basins.length ? `${name} · ${basins.join(' / ')}` : name;
    }
    return t('board.nearestFirst');
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

      // The name + an optional status sub-line stack in a meta column so a closed /
      // uncurated row states its condition ON the label (plan FIX 1), not only below.
      const meta = doc.createElement('div');
      meta.className = 'board__rowmeta';
      const name = doc.createElement('span');
      name.className = 'board__rowname';
      if (filter.mode === 'pool') {
        name.textContent = weekdayDateLabel(row);
        if (today && row.date === today) label.classList.add('board__rowlabel--today');
      } else {
        name.textContent = row.label;
      }
      meta.appendChild(name);

      const statusLine = rowStatusLine(row);
      if (statusLine) {
        const sub = doc.createElement('span');
        sub.className = `board__rowsub board__rowsub--${statusLine.kind}`;
        sub.textContent = statusLine.text;
        meta.appendChild(sub);
      }

      // Fair-weather marker (seasonal-hours S4). The city publishes an outdoor pool's late
      // block only for good weather; without this the ribbon reads as a promise. It is a
      // SEPARATE line from the status sub-line and it does NOT change the row's dot or its
      // terminal state: the row is genuinely open, and only the NAMED spans are conditional.
      const fair = fairWeatherText(row.options);
      if (fair) {
        const cond = doc.createElement('span');
        cond.className = 'board__rowfair';
        cond.textContent = fair;
        meta.appendChild(cond);
      }
      label.appendChild(meta);

      if (filter.mode === 'pool' && today && row.date === today) {
        const tag = doc.createElement('span');
        tag.className = 'board__todaytag';
        tag.textContent = t('common.today');
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
      const canvas = asCanvas(doc.createElement('canvas'));
      canvas.className = 'board__canvas';
      canvas.width = ts.PLOT;
      canvas.height = ROW_H;
      canvas.style.width = `${ts.PLOT}px`;
      canvas.style.height = `${ROW_H}px`;
      if (elig === 'no' && eligEngaged(filter)) canvas.classList.add('board__canvas--noelig');
      trackBody.appendChild(canvas);

      const ribbons = ribbonsFor(row) as Ribbon[];
      canvases.push({ canvas, row, ribbons, animated: isAnimated(ribbons) });
    }
    return rows;
  }

  let rows = buildRows();

  function paintStatic(phase = 0) {
    drawAxis(axisCanvas, ts, pal);
    for (const { canvas, ribbons } of canvases) drawRow(canvas, ribbons, ts, pal, phase);
  }

  function paintAnimated(phase: number) {
    for (const { canvas, ribbons, animated } of canvases) {
      if (animated) drawRow(canvas, ribbons, ts, pal, phase);
    }
  }

  let running = false;
  function loop(t: number) {
    paintAnimated((t || 0) / 600);
    if (running && raf) raf(loop);
  }
  paintStatic(0);
  if (!reducedMotion && raf) {
    running = true;
    raf(loop);
  }

  function setFilter(next: BoardFilter) {
    filter = next;
    rows = buildRows();
    paintStatic(0);
  }

  function setData(next: BoardData) {
    data = next;
    rows = buildRows();
    paintStatic(0);
  }

  function destroy() {
    running = false; // stop the shared RAF loop so a rebuilt board leaves no orphan
    if (board.parentNode === el) el.removeChild?.(board);
  }

  // The board's cursor-x for minute `min`, routed through the SHARED cursor helper
  // over the board's OWN timescale `ts`. The Gantt computes its cursor-x the same
  // way (gantt.js → cursorX(ts, min)); handed the same `ts`, board.cursorX(T) ===
  // gantt.cursorPlotX(T) BY CONSTRUCTION. This is the anti-desync anchor the
  // board_gantt_align test asserts directly.
  function cursorXAt(min: number) {
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
