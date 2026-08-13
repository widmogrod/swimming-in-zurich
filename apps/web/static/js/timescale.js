// timescale.js — the ONE shared time→x mapping.
//
// The board's ribbon renderer and the per-basin lane Gantt both import this, so a
// click at time T lands on the same plot-x in both. That coincidence is the whole
// board's correctness anchor (plan Design §"shared time-scale"), so it lives in a
// single pure module — no canvas, no DOM — that is unit-testable in isolation.
//
//   X(min) = ((min − DAY0·60) / (DAY1·60 − DAY0·60)) · PLOT
//
// mapping minutes-of-day in [DAY0·60, DAY1·60] linearly onto plot-x in [0, PLOT].

/**
 * Build a timescale for a day window [DAY0:00, DAY1:00] rendered across PLOT px.
 * @param {number} DAY0 first shown hour (0–24), inclusive left edge.
 * @param {number} DAY1 last shown hour (0–24), must be > DAY0.
 * @param {number} PLOT plot width in px, must be > 0.
 * @returns {{X:(min:number)=>number, inverse:(x:number)=>number,
 *            DAY0:number, DAY1:number, PLOT:number, lo:number, hi:number, span:number}}
 */
export function makeTimescale(DAY0, DAY1, PLOT) {
  const lo = DAY0 * 60;
  const hi = DAY1 * 60;
  const span = hi - lo;
  if (!(span > 0)) throw new RangeError('timescale: DAY1 must be after DAY0');
  if (!(PLOT > 0)) throw new RangeError('timescale: PLOT must be positive');

  // map: minutes-of-day → plot-x.
  const X = (min) => ((min - lo) / span) * PLOT;
  // inverse: plot-x → minutes-of-day.
  const inverse = (x) => lo + (x / PLOT) * span;

  return { X, inverse, DAY0, DAY1, PLOT, lo, hi, span };
}
