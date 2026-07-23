// cursor.js — the shared, PURE cursor + lane-count helpers that the RibbonBoard,
// the LaneGantt, and the DetailPanel ALL consume (plan Part 3 §5/§6, Risk #3).
//
// The crown jewel of the board is that ONE cursor time T lands on the same plot-x
// in the board ribbon and the lane Gantt, and that the "N public lanes at T"
// number shown next to the board and in the panel headline is the SAME value —
// driven by the cursor, never by the day's peak (the real bug the prototype fixed).
//
// Both of those coincidences are made structural here: a single mapping
// (`cursorX`) and a single reducer (`publicAt`). Anyone who re-derives either in a
// renderer instead of calling these breaks a unit test.
//
// This module is a pure leaf: no DOM, no canvas, no timescale construction. It is
// handed a timescale (built ONCE, upstream) and a canonical `basin` model.

// "HH:MM" → minutes-of-day. This leaf is the ONE definition: board.js (and the
// Gantt/panel via this module) import it from here — the old duplicated copy in
// board.js was consolidated away (S5 F nit), so there is a single time parser.
export function hhmmToMin(hhmm) {
  const [h, m] = String(hhmm).split(':').map((n) => parseInt(n, 10));
  return h * 60 + m;
}

// minutes-of-day → "HH:MM" (zero-padded). Used by the live cursor readout.
export function minToHhmm(min) {
  const m = Math.round(min);
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

/**
 * cursorX(timescale, min) → plot-x (px) for the time cursor at `min`.
 *
 * This is THE mapping. The board draws its ribbons and its cursor through
 * `timescale.X(min)`; the Gantt draws its segments and its cursor through the
 * SAME injected `timescale`. So `cursorX(ts, T)` is, by construction, both the
 * board cursor-x and the Gantt cursor-x for the same `ts` — the anti-desync anchor
 * (give the Gantt its own scale and this equality fails a test).
 * @param {{X:(min:number)=>number}} timescale the ONE shared timescale.
 * @param {number} min minutes-of-day.
 */
export function cursorX(timescale, min) {
  return timescale.X(min);
}

/**
 * basinFromPanel(lanePanel) → the canonical `basin` model both the Gantt and the
 * DetailPanel render from, derived from a `/pools/{id}` `lane_panels[]` entry.
 * @param {object} lanePanel `{ basin_id, basin_name, panel:{ day_view, best_public, roster } }`.
 * @returns {{id:string, name:string, lane_count:number,
 *            strips:Array<{lane:number, segments:Array}>, best_public:object|null,
 *            weekday:number}}
 */
export function basinFromPanel(lanePanel) {
  const dv = lanePanel.panel.day_view;
  return {
    id: lanePanel.basin_id,
    name: lanePanel.basin_name,
    lane_count: dv.lane_count,
    strips: dv.strips || [],
    best_public: lanePanel.panel.best_public || null,
    weekday: dv.weekday,
  };
}

/**
 * panelForBasin(lanePanels, basinName) → the `/pools/{id}` `lane_panels[]` entry
 * whose basin matches `basinName` (by `basin_name`), or the FIRST panel as a
 * fallback, or null when there are no panels.
 *
 * This is what lets a click on a MULTI-BASIN facility's board row open the panel on
 * the SAME basin the clicked option belongs to (so board readout == panel headline
 * holds — the S3/S4 identity), instead of always taking `lane_panels[0]`.
 * @param {Array<{basin_name:string}>} lanePanels the detail's lane_panels[].
 * @param {string|null|undefined} basinName the clicked option's basin name.
 */
export function panelForBasin(lanePanels, basinName) {
  const panels = lanePanels || [];
  if (panels.length === 0) return null;
  if (basinName != null) {
    const match = panels.find((lp) => lp.basin_name === basinName);
    if (match) return match;
  }
  return panels[0];
}

// The lane segment covering `min` in a strip (start ≤ min < end), or null. Gaps
// between segments are absent on purpose (a gap is "no session", NOT public).
function segmentAt(strip, min) {
  return (
    strip.segments.find((s) => hhmmToMin(s.start) <= min && min < hhmmToMin(s.end)) || null
  );
}

/**
 * publicAt(basin, min) → { public, total } — how many of the basin's lanes are
 * open to the public at minute `min`. A lane counts as public only when its
 * covering segment is a `PublicSwim` session (owner null); a reserved segment or a
 * gap does not. `total` is the basin's lane_count (M).
 *
 * This is the SINGLE source of the "N of M public" number: the board's cursor
 * readout AND the DetailPanel headline both call it with the same basin + cursor,
 * so they are equal BY CONSTRUCTION — and neither can silently fall back to the
 * day's peak.
 * @param {{lane_count:number, strips:Array}} basin canonical basin model.
 * @param {number} min minutes-of-day.
 */
export function publicAt(basin, min) {
  let count = 0;
  for (const strip of basin.strips) {
    const seg = segmentAt(strip, min);
    if (seg && seg.access === 'PublicSwim') count += 1;
  }
  return { public: count, total: basin.lane_count };
}

// Every minute at which the public-lane count can change is a segment boundary, so
// sampling publicAt at each distinct segment start finds the day's true peak.
function boundaryMinutes(basin) {
  const set = new Set();
  for (const strip of basin.strips) {
    for (const seg of strip.segments) set.add(hhmmToMin(seg.start));
  }
  return [...set].sort((a, b) => a - b);
}

/**
 * peakPublic(basin) → the MAX public-lane count across the whole day. Kept as a
 * SECONDARY note only (the headline is always cursor-driven `publicAt`).
 */
export function peakPublic(basin) {
  let peak = 0;
  for (const min of boundaryMinutes(basin)) {
    const { public: n } = publicAt(basin, min);
    if (n > peak) peak = n;
  }
  return peak;
}
