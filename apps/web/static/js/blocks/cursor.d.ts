// cursor.d.ts — types for the shared cursor/basin leaf (cursor.js).
//
// The implementation stays plain JS during the TypeScript migration; this declares its
// shape so the converted `.ts` blocks and suites that consume it type-check at full
// strictness instead of importing `any`. Delete this file when cursor.js converts.

/** A single lane's occupancy segment within a basin's day. */
export interface LaneSegment {
  start: string;
  end: string;
  access: string;
  owner?: string;
  [k: string]: unknown;
}

export interface LaneStrip {
  lane: number | string;
  segments: LaneSegment[];
}

/** The canonical basin the board, panel and Gantt all read. */
export interface Basin {
  id: string;
  name: string;
  lane_count: number;
  strips: LaneStrip[];
  best_public: { start: string; end: string } | null;
  weekday: number;
}

/** A `/pools/{id}` `lane_panels[]` entry. */
export interface LanePanel {
  basin_id: string;
  basin_name: string;
  panel: {
    day_view: { lane_count: number; strips?: LaneStrip[]; weekday: number };
    best_public?: { start: string; end: string } | null;
  };
  [k: string]: unknown;
}

/** `'06:30'` → 390 (minutes-of-day). */
export declare function hhmmToMin(hhmm: string): number;

/** 390 → `'06:30'`. */
export declare function minToHhmm(min: number): string;

/** Plot-relative x for a minute, on the SHARED timescale. */
export declare function cursorX(timescale: { X(min: number): number }, min: number): number;

export declare function basinFromPanel(lanePanel: LanePanel): Basin;

/** The panel matching `basinName`, else the first, else null. */
export declare function panelForBasin<T extends { basin_name: string }>(
  lanePanels: T[],
  basinName: string | null | undefined,
): T | null;

/** Public/total lane counts at a given minute. */
export declare function publicAt(
  basin: { lane_count: number; strips: LaneStrip[] },
  min: number,
): { public: number; total: number };

/** The day's peak public-lane count. */
export declare function peakPublic(basin: { lane_count: number; strips: LaneStrip[] }): number;
