// gantt.d.ts — types for the LaneGantt block (gantt.js).
//
// The implementation stays plain JS during the TypeScript migration; this declares its
// shape so the converted `.ts` panel and suites type-check at full strictness instead of
// importing `any`. Delete this file when gantt.js converts.

import type { Basin } from './cursor.js';
import type { El } from '../domtypes.js';

export interface GanttTimescale {
  X(min: number): number;
  inverse(x: number): number;
  PLOT: number;
  lo: number;
  hi: number;
  [k: string]: unknown;
}

export interface GanttOpts {
  basin: Basin;
  /** REQUIRED — the Gantt refuses to re-derive its own scale (it throws without one). */
  timescale: GanttTimescale;
  cursorMin?: number;
}

export interface Gantt {
  el: El;
  timescale: GanttTimescale;
  /** Plot-relative x — equals the board's cursor-x for the same timescale. */
  cursorPlotX(min: number): number;
  /** Gutter-offset x within this gantt's own track. */
  trackX(min: number): number;
  readoutAt(min: number): { public: number; total: number };
  setCursor(min: number): void;
  readonly cursorMin: number;
  readonly laneCount: number;
}

export declare function createGantt(el: El, opts: GanttOpts): Gantt;
