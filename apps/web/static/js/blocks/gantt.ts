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
import { t } from '../i18n.js';
import {
  cursorX,
  hhmmToMin,
  isPublicSegment,
  minToHhmm,
  publicAt,
  type Basin,
} from './cursor.js';

// The left label gutter (GL): lane names sit here; the plot starts at GL. A segment
// at minute `min` is drawn at `GL + timescale.X(min)`; the cursor at the same x.
export const GANTT_LABEL_W = 120;

/** Fallback width for the readout where the DOM cannot measure one: the headless suites'
 *  FakeElement has no layout, and a real element has no `offsetWidth` until it is in a
 *  rendered document. Used ONLY to place the readout; a browser reports its real width. */
export const READOUT_NOMINAL_W = 180;

/**
 * readoutLeft(x, width, lo, hi) → the readout's left edge, in TRACK px.
 *
 * The readout names the moment the cursor is on, so it is CENTRED on the cursor's x — the
 * same `trackX` the cursor line is placed at, never a second derivation (a readout that
 * disagrees with its own cursor is worse than one that never moves).
 *
 * `[lo, hi]` is the VISIBLE window of the track, not the track. Clamping to the track's own
 * ends is not enough: in the desktop detail panel a ~1020px track lives inside a ~290px
 * column, so a centred readout is cut in half by `.gantt__scroll` for most of the day —
 * observed in the running app, which is why this takes a window and not a width. Clamped to
 * the window the readout stops flush with the visible edge and the cursor keeps travelling
 * past its middle: always wholly readable, at the cost of not being centred at the extremes.
 * That trade is deliberate — a half-clipped number is not a number. A window narrower than
 * the readout has no non-overflowing placement at all, so it sits flush at `lo`, which at
 * least keeps the beginning of the sentence (the time itself) readable.
 */
export function readoutLeft(x: number, width: number, lo: number, hi: number): number {
  const maxLeft = hi - width;
  if (maxLeft <= lo) return lo;
  return Math.min(Math.max(x - width / 2, lo), maxLeft);
}

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

  // --- horizontally-scrollable track (own overflow container on mobile) ---
  const scroll = doc.createElement('div');
  scroll.className = 'gantt__scroll';
  const track = doc.createElement('div');
  track.className = 'gantt__track';
  const trackW = GL + ts.PLOT;
  track.style.width = `${trackW}px`;
  scroll.appendChild(track);
  el.appendChild(scroll);

  // --- live readout: "T · N of M lanes public", riding above the cursor ---
  //
  // It lives INSIDE the track, not beside it, so that it shares the cursor's coordinate
  // space: one number in track px places both, and `scrollLeft` never enters the alignment.
  // Parked in `el` the readout would need `scrollLeft` subtracted from every placement just
  // to sit over the line it names.
  //
  // That buys ALIGNMENT only, not visibility — see `placeReadout` below, which clamps to the
  // VISIBLE window and therefore does need a scroll listener, because scrolling moves that
  // window without moving the cursor. Track parenthood and the scroll listener answer two
  // different questions; neither replaces the other.
  //
  // It is still a live region — `role=status` / `aria-live=polite` are on the element, which
  // is created once and only ever has its text rewritten, so moving it changes where it is
  // painted and nothing about what a screen reader announces.
  const readout = doc.createElement('div');
  readout.className = 'gantt__readout tnum';
  readout.setAttribute('role', 'status');
  readout.setAttribute('aria-live', 'polite');
  track.appendChild(readout);

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
    label.textContent = t('gantt.lane', { lane: String(strip.lane) });
    lane.appendChild(label);

    for (const seg of strip.segments) {
      // The ONE definition of "a public lane" (cursor.js), shared with the board's lane
      // stack and the panel — a local `access === 'PublicSwim'` here could disagree with
      // the "N of M lanes public" readout drawn a few pixels above it.
      const isPublic = isPublicSegment(seg);
      const box = doc.createElement('span');
      box.className = `gantt__seg ${isPublic ? 'is-public' : 'is-reserved'}`;
      const x0 = trackX(hhmmToMin(seg.start));
      const x1 = trackX(hhmmToMin(seg.end));
      box.style.left = `${x0}px`;
      box.style.width = `${Math.max(1, x1 - x0)}px`;
      // Owner-named reserved lanes carry the owner text (never hue-only — CVD-safe).
      box.textContent = isPublic ? t('gantt.public') : seg.owner || t('gantt.reserved');
      box.setAttribute(
        'title',
        `${seg.start}–${seg.end} · ${isPublic ? t('gantt.public') : seg.owner || t('gantt.reserved')}`,
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

  /** The readout's own width: measured where the DOM can measure it, nominal where it
   *  cannot. Only the placement uses it; the text is unaffected. */
  const readoutWidth = (): number => {
    const w = (readout as El & { offsetWidth?: number }).offsetWidth;
    return typeof w === 'number' && w > 0 ? w : READOUT_NOMINAL_W;
  };

  /** The slice of the track the reader can currently see, in track px. Read off the scroll
   *  container on every placement rather than cached: it changes on scroll AND on resize,
   *  and it is two property reads.
   *
   *  Two degenerate readings both fall back to the whole track, `[0, trackW]`. Headless
   *  there is no layout at all, and "nothing is clipping this" is the honest answer for a
   *  surface with no viewport. In a browser `clientWidth` can also be 0 for one beat — the
   *  element is in the DOM but not yet laid out at the first `paintCursor` — which places
   *  the readout as if unclipped; the next cursor move or scroll re-reads a real width and
   *  corrects it, so the wrong value cannot persist past the first interaction. */
  const visibleWindow = (): [number, number] => {
    const box = scroll as El & { scrollLeft?: number; clientWidth?: number };
    const w = box.clientWidth;
    if (typeof w !== 'number' || w <= 0) return [0, trackW];
    const lo = typeof box.scrollLeft === 'number' ? box.scrollLeft : 0;
    return [lo, Math.min(lo + w, trackW)];
  };

  function placeReadout() {
    const [lo, hi] = visibleWindow();
    // Off the SAME `trackX` the cursor line is drawn at — never a second derivation.
    readout.style.left = `${readoutLeft(trackX(cursorMin), readoutWidth(), lo, hi)}px`;
  }

  function paintCursor() {
    cursor.style.left = `${trackX(cursorMin)}px`;
    const { public: n, total: m } = readoutAt(cursorMin);
    // Was a hardcoded English template — the `gantt.readout` key already existed in all
    // five catalogues and simply was not used, so this line stayed English on a Polish page.
    readout.textContent = t('gantt.readout', { hhmm: minToHhmm(cursorMin), public: n, total: m });
    // Placed AFTER the text is written, so a browser measures the sentence it will show.
    placeReadout();
  }

  // Scrolling the track moves the visible window under a stationary readout, so the clamp
  // has to be re-evaluated — otherwise scrolling away from the cursor drags the readout off
  // screen with it, which is the same "can't read the number" the placement exists to fix.
  //
  // DELIBERATELY no `resize` listener to go with it. A resize can leave the readout clamped
  // to a window one size stale, but this surface is driven by hover: the board re-places the
  // readout on every cursor minute, so a stale clamp is corrected by the first mouse
  // movement over the very Gantt whose number the reader is trying to read. Add a
  // ResizeObserver only if a surface appears that resizes while nobody is pointing at it.
  scroll.addEventListener('scroll', placeReadout);
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
