// gantt.js — the LaneGantt block (plan Part 3 §5).
//
// A per-basin, lane-by-lane plan drawn on the SAME timescale as the RibbonBoard:
// one row per lane, public vs reserved-with-owner-named segments, a highlighted
// "best public window" band, and a vertical time-cursor that lands on exactly the
// board's cursor-x (because it uses the board's injected `timescale`, never a
// re-derived one — the createGantt factory THROWS without one). A live readout
// "T · N of M lanes public" is computed by the shared `publicAt` helper, so it is
// identical to the DetailPanel headline.
//
// Layering: a BLOCK. It imports the shared `cursor` helpers (cursorX / publicAt /
// peakPublic / basinFromPanel / minToHhmm / hhmmToMin) and lays out DOM. It adds
// NO colour — every hue (public/reserved/best-band/cursor) is a token applied via
// a class in blocks.css, so this file carries no raw hex. Positions are px numbers
// derived from the timescale only.

import { asDoc, type El } from '../domtypes.js';
import { cursorX, hhmmToMin, minToHhmm, publicAt, type Basin } from './cursor.js';

// The left label gutter (GL): lane names sit here; the plot starts at GL. A segment
// at minute `min` is drawn at `GL + timescale.X(min)`; the cursor at the same x.
export const GANTT_LABEL_W = 120;

/**
 * createGantt(el, opts) — mount a LaneGantt into `el`.
 * @param {object} opts
 * @param {{lane_count: number, strips: any[], best_public?: any, name?: string}} opts.basin canonical basin.
 * @param {object} opts.timescale the SHARED timescale (REQUIRED — throws if absent,
 *   which is what forbids a Gantt-local scale and guarantees board↔Gantt alignment).
 * @param {number} [opts.cursorMin] initial cursor minutes-of-day (default: best-public start).
 * @returns {{el, timescale, cursorPlotX, trackX, readoutAt, setCursor, cursorMin}}
 */
export interface GanttTimescale {
  X(min: number): number;
  inverse(x: number): number;
  DAY0: number;
  DAY1: number;
  PLOT: number;
  lo: number;
  hi: number;
  span: number;
}

export interface GanttOpts {
  basin: Basin;
  /** REQUIRED — the Gantt refuses to re-derive its own scale (it throws without one). */
  timescale: GanttTimescale;
  cursorMin?: number;
}

export function createGantt<T extends El>(el: T, opts: GanttOpts) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const ts = opts.timescale;
  if (!ts || typeof ts.X !== 'function') {
    // The single hardest correctness property (Risk #3): a Gantt with its OWN scale
    // would desync from the board. Refuse to build one.
    throw new TypeError('createGantt: a shared `timescale` is required (never re-derive the scale)');
  }
  const basin = opts.basin || { lane_count: 0, strips: [], best_public: null };
  const GL = GANTT_LABEL_W;

  // cursor-x, plot-relative (matches the board, which also draws at timescale.X).
  const cursorPlotX = (min: number) => cursorX(ts, min);
  // absolute x within the gantt track (gutter + plot).
  const trackX = (min: number) => GL + cursorPlotX(min);

  let cursorMin =
    opts.cursorMin != null
      ? opts.cursorMin
      : basin.best_public
        ? hhmmToMin(basin.best_public.start)
        : Math.round((ts.lo + ts.hi) / 2);

  el.classList.add('gantt');

  // --- live readout: "T · N of M lanes public" ---
  const readout = doc.createElement('div');
  readout.className = 'gantt__readout tnum';
  readout.setAttribute('role', 'status');
  readout.setAttribute('aria-live', 'polite');
  el.appendChild(readout);

  // --- horizontally-scrollable track (own overflow container on mobile) ---
  const scroll = doc.createElement('div');
  scroll.className = 'gantt__scroll';
  const track = doc.createElement('div');
  track.className = 'gantt__track';
  track.style.width = `${GL + ts.PLOT}px`;
  scroll.appendChild(track);
  el.appendChild(scroll);

  // axis row: ticks aligned to the board's (same timescale, drawn at GL + X(h)).
  const axis = doc.createElement('div');
  axis.className = 'gantt__axis';
  for (let hour = ts.DAY0; hour <= ts.DAY1; hour += 2) {
    const tick = doc.createElement('span');
    tick.className = 'gantt__tick tnum';
    tick.style.left = `${trackX(hour * 60)}px`;
    tick.textContent = `${String(hour).padStart(2, '0')}:00`;
    axis.appendChild(tick);
  }
  track.appendChild(axis);

  // best-public band: highlight the "best time to come" window.
  if (basin.best_public) {
    const band = doc.createElement('div');
    band.className = 'gantt__band';
    const x0 = trackX(hhmmToMin(basin.best_public.start));
    const x1 = trackX(hhmmToMin(basin.best_public.end));
    band.style.left = `${x0}px`;
    band.style.width = `${Math.max(1, x1 - x0)}px`;
    band.setAttribute(
      'aria-label',
      `Best public window ${basin.best_public.start}–${basin.best_public.end}, ` +
        `${basin.best_public.public_lanes} lanes`,
    );
    track.appendChild(band);
  }

  // one row per lane; each segment is public (aqua) or reserved-with-owner (grey).
  for (const strip of basin.strips) {
    const lane = doc.createElement('div');
    lane.className = 'gantt__lane';

    const label = doc.createElement('span');
    label.className = 'gantt__lanelabel';
    label.style.width = `${GL}px`;
    label.textContent = `Lane ${strip.lane}`;
    lane.appendChild(label);

    for (const seg of strip.segments) {
      const isPublic = seg.access === 'PublicSwim';
      const box = doc.createElement('span');
      box.className = `gantt__seg ${isPublic ? 'is-public' : 'is-reserved'}`;
      const x0 = trackX(hhmmToMin(seg.start));
      const x1 = trackX(hhmmToMin(seg.end));
      box.style.left = `${x0}px`;
      box.style.width = `${Math.max(1, x1 - x0)}px`;
      // Owner-named reserved lanes carry the owner text (never hue-only — CVD-safe).
      box.textContent = isPublic ? 'Public' : seg.owner || 'Reserved';
      box.setAttribute(
        'title',
        `${seg.start}–${seg.end} · ${isPublic ? 'Public' : seg.owner || 'Reserved'}`,
      );
      lane.appendChild(box);
    }
    track.appendChild(lane);
  }

  // --- the vertical time cursor (shared position) ---
  const cursor = doc.createElement('div');
  cursor.className = 'gantt__cursor';
  cursor.setAttribute('aria-hidden', 'true');
  track.appendChild(cursor);

  // readoutAt(min) → { public, total } at `min` — the SAME publicAt the panel uses.
  const readoutAt = (min: number) => publicAt(basin, min);

  function paintCursor() {
    cursor.style.left = `${trackX(cursorMin)}px`;
    const { public: n, total: m } = readoutAt(cursorMin);
    readout.textContent = `${minToHhmm(cursorMin)} · ${n} of ${m} lanes public`;
  }
  paintCursor();

  function setCursor(min: number) {
    cursorMin = min;
    paintCursor();
  }

  return {
    el,
    timescale: ts,
    cursorPlotX, // plot-relative x (== board cursor-x for the same timescale)
    trackX, // gutter-offset x within this gantt's own track
    readoutAt,
    setCursor,
    get cursorMin() {
      return cursorMin;
    },
    get laneCount() {
      return basin.strips.length;
    },
  };
}
