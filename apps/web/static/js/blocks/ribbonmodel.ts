import { t, type MessageKey } from '../i18n.js';
import { hhmmToMin, isPublicSegment, minToHhmm } from './cursor.js';
// ribbonmodel.js — PURE mapping of a `/swim` option/status → a ribbon render state.
//
// No canvas, no DOM (plan Risk #2: keep the drawable logic testable without a
// browser). The board's canvas renderer consumes these plain objects; every visual
// decision (dashed vs dotted, thickness, pinch, sheath, colour family) is decided
// HERE and unit-tested against saved `/swim` fixtures.
//
// The three terminal states are never merged (product invariant): a `closed` status
// is a DASHED ribbon carrying its reason; a schedule-less status (`awaiting_scrape`
// or `no_source`) is a DOTTED ghost; an option with no published lane split is its own
// "not published" ribbon — none of them collapses into another.

// access class name (`type(session.access).__name__`) → colour-family key. The board
// maps each key to a token (see blocks.css `.fam-*`); the key itself carries no hex.
export const ACCESS_FAMILY = Object.freeze({
  PublicSwim: 'public',
  LaneSwim: 'lane',
  FamilyTime: 'family',
  WomenOnly: 'women',
  SeniorsOnly: 'seniors',
  AdultsOnly: 'adults',
  SchoolReserved: 'school',
  ClubReserved: 'club',
  // The school-pool vocabulary (school-access-vocabulary S1). Each gets its OWN key rather
  // than falling to 'other': 'other' paints with the public-swim colour (ribbonrender's
  // `pal.other = read('fam-public')`), which is exactly the "looks open to you" lie the
  // eligibility fallback used to tell.
  GirlsOnly: 'girls',
  GenderDiverse: 'diverse',
  AccompaniedChildren: 'accompanied',
});

/** A `/swim` option as the ribbon model reads it. */
export interface RibbonOption {
  access?: string;
  start?: string;
  end?: string;
  facility?: string;
  basin?: string;
  lane_timeline?: { segments?: RibbonTimelineSegment[] } | null;
  /** `OptionOut.lane_day_view` (S2): WHICH lane and WHOSE, for the lane stack. */
  lane_day_view?: RibbonDayView | null;
  /** `OptionOut.lane_best_public` (S2): the best public window, ALREADY bounded by this
   *  option's own session hours server-side — the stack must not re-widen it. */
  lane_best_public?: RibbonPublicWindow | null;
  [k: string]: unknown;
}

/** One owner's hold on one lane, as `/swim` serves it (`LaneSegmentOut`). */
export interface RibbonLaneSegment {
  start: string;
  end: string;
  access?: string;
  owner?: string | null;
  [k: string]: unknown;
}

/** One lane's whole weekday (`LaneStripOut`). */
export interface RibbonLaneStrip {
  lane: number;
  segments?: RibbonLaneSegment[];
  [k: string]: unknown;
}

/** `LaneDayViewOut` — the basin's per-lane WEEKDAY (not the session window). */
export interface RibbonDayView {
  weekday?: number;
  lane_count: number;
  strips?: RibbonLaneStrip[];
  [k: string]: unknown;
}

/** `PublicWindowOut` — the session's "best time to come". */
export interface RibbonPublicWindow {
  start: string;
  end: string;
  public_lanes: number;
}

/** One block of one lane of the STACK: a drawable, session-clipped hold. */
export interface RibbonStackBlock {
  start: string;
  end: string;
  public: boolean;
  owner: string | null;
}

/** One lane sub-row of the stack. Always present for lanes `1..lane_count`, even when the
 *  lane holds nothing inside the session — an empty sub-row is a lane nobody has taken,
 *  which is a different fact from a lane we know nothing about. */
export interface RibbonStackLane {
  lane: number;
  segments: RibbonStackBlock[];
}

export interface RibbonTimelineSegment {
  start: string;
  end: string;
  lane_count: number;
  public_lanes: number;
  [k: string]: unknown;
}

export interface RibbonStatus {
  facility?: string;
  status?: string;
  detail?: string | null;
  closure_code?: string | null;
  detail_params?: Record<string, string>;
}

/** One drawable band on a board row. */
export interface Ribbon {
  kind: string;
  variant?: string;
  family?: string;
  style?: string;
  [k: string]: unknown;
}

/** The i18n key for the "lane split not published" label — the one ribbon field whose
 *  rendered form is locale-dependent. Exported so the golden fixture can carry the key
 *  rather than a translation. */
export const NO_SPLIT_LABEL_KEY: MessageKey = 'insight.noSplit.label';

/** access class name → colour-family key ('other' for an unknown type). */
export function accessFamily(access: string): string {
  return (ACCESS_FAMILY as Record<string, string>)[access] || 'other';
}

// Public fraction of a lane-timeline segment: how much of the ribbon is open to you.
// Explicit 0 when the basin has no lanes recorded (avoid NaN → the ribbon pinches shut).
function publicFraction(seg: RibbonTimelineSegment): number {
  return seg.lane_count > 0 ? seg.public_lanes / seg.lane_count : 0;
}

/**
 * laneStackFor(dayView, start, end) → one sub-row per lane `1..lane_count`, each carrying
 * only the holds that fall inside THIS option's hours.
 *
 * The clip is not cosmetic. `lane_day_view` spans the whole WEEKDAY, while a ribbon is one
 * SESSION: Oerlikon's 06:00–08:00 and 08:00–21:30 options share a basin and therefore
 * share a day view, so an unclipped stack would paint each option's ribbon across the
 * whole day — two ribbons claiming hours neither session covers, drawn over each other.
 * Clipping mirrors what S2 already did server-side for `lane_best_public`.
 *
 * A lane with nothing inside the window keeps its (empty) sub-row: "nobody holds this
 * lane" is a fact, and dropping the row would silently renumber the lanes below it.
 */
export function laneStackFor(
  dayView: RibbonDayView,
  start: string | undefined,
  end: string | undefined,
): RibbonStackLane[] {
  const lo = hhmmToMin(start ?? '');
  const hi = hhmmToMin(end ?? '');
  const byLane = new Map<number, RibbonLaneSegment[]>();
  for (const strip of dayView.strips ?? []) {
    byLane.set(Number(strip.lane), strip.segments ?? []);
  }
  const lanes: RibbonStackLane[] = [];
  for (let lane = 1; lane <= dayView.lane_count; lane += 1) {
    const segments: RibbonStackBlock[] = [];
    for (const seg of byLane.get(lane) ?? []) {
      const s = Math.max(lo, hhmmToMin(seg.start));
      const e = Math.min(hi, hhmmToMin(seg.end));
      if (!(e > s)) continue; // wholly outside this session (or zero-length)
      segments.push({
        start: minToHhmm(s),
        end: minToHhmm(e),
        public: isPublicSegment(seg),
        owner: typeof seg.owner === 'string' && seg.owner ? seg.owner : null,
      });
    }
    lanes.push({ lane, segments });
  }
  return lanes;
}

/**
 * optionRibbon(option) → a ribbon render state for a `/swim` option.
 *   - with `lane_day_view`  → a LANE STACK: one sub-row per lane, public vs reserved,
 *     the owner carried on each reserved block, and the session's best-public window
 *     (`option.lane_best_public`, absent when the server sent null).
 *   - with `lane_timeline` only → a FILLED ribbon; each segment's `thickness` is the
 *     public fraction (public_lanes/lane_count) and it is `pinched` wherever any
 *     lane is reserved (reserved_lanes>0); `sheath:true` draws the capacity envelope.
 *   - with neither → a "lane split not published" ribbon (`sheath:false`).
 * The colour `family` is set in every case.
 *
 * The three are NEVER merged (invariant I5): the published universe is closed at 8 lane
 * sheets, so most pools will never have a stack, and a pool with no plan must not read as
 * a pool with no free lanes.
 */
export function optionRibbon(option: RibbonOption): Ribbon {
  const family = accessFamily(option.access ?? '');
  const base = {
    kind: 'option',
    family,
    access: option.access,
    facility: option.facility,
    basin: option.basin,
    start: option.start,
    end: option.end,
  };
  const dayView = option.lane_day_view;
  // Hours are required to CLIP the day view to this session, so an option missing them
  // cannot be stacked: a stack with no window would paint every lane empty, i.e. "nothing
  // free", which is the one thing a missing fact must never look like (I5).
  const hasHours =
    Number.isFinite(hhmmToMin(option.start ?? '')) && Number.isFinite(hhmmToMin(option.end ?? ''));
  if (dayView && Number(dayView.lane_count) > 0 && Array.isArray(dayView.strips) && hasHours) {
    return {
      ...base,
      variant: 'lanestack',
      style: 'solid',
      sheath: true,
      lane_count: Number(dayView.lane_count),
      strips: laneStackFor(dayView, option.start, option.end),
      // ABSENT, not zero-width, when the server has no window for this session: the band
      // is a claim ("come then"), and a null one is no claim at all.
      ...(option.lane_best_public ? { best_public: option.lane_best_public } : {}),
    };
  }
  const timeline = option.lane_timeline;
  if (timeline && Array.isArray(timeline.segments) && timeline.segments.length > 0) {
    return {
      ...base,
      variant: 'lanes',
      style: 'solid',
      sheath: true,
      segments: timeline.segments.map((seg) => ({
        start: seg.start,
        end: seg.end,
        thickness: publicFraction(seg),
        pinched: Number(seg.reserved_lanes) > 0,
        lane_count: seg.lane_count,
        public_lanes: seg.public_lanes,
        reserved_lanes: Number(seg.reserved_lanes),
        partial: seg.partial,
      })),
    };
  }
  return {
    ...base,
    variant: 'unpublished',
    style: 'solid',
    sheath: false,
    label: t(NO_SPLIT_LABEL_KEY),
    // The KEY beside the rendered label. `label` is locale-dependent output, so it is the one
    // field of a ribbon that cannot appear in a cross-client golden fixture without pinning
    // this suite's locale into it; the key is the thing both clients actually agree on, and
    // the iOS port renders it through its own catalog.
    label_key: NO_SPLIT_LABEL_KEY,
  };
}

/**
 * statusRibbon(status) → a ribbon render state for a `/swim` status entry.
 *   - status === 'closed'                       → a DASHED closed ribbon carrying `detail`.
 *   - status === 'awaiting_scrape' | 'no_source' → a DOTTED ghost ribbon (unknown ≠ closed).
 * Any other status label falls back to the ghost/unknown ribbon (never to closed).
 */
export function statusRibbon(status: RibbonStatus): Ribbon {
  // Carry the S4 closure code alongside the prose so the CANVAS ribbon and the label
  // column render the same fact the same way — they used to diverge (label translated,
  // ribbon still German), which is worse than either alone.
  const base = {
    kind: 'status',
    facility: status.facility,
    detail: status.detail,
    closure_code: status.closure_code,
    detail_params: status.detail_params,
  };
  if (status.status === 'closed') {
    return { ...base, variant: 'closed', style: 'dashed', family: 'closed' };
  }
  // A schedule-less status (awaiting_scrape / no_source) → a DOTTED ghost; carry the status value
  // so the canvas can render its SPECIFIC freshness label, never a merged bucket.
  return { ...base, status: status.status, variant: 'ghost', style: 'dotted', family: 'unknown' };
}

/**
 * ribbonsFor(row) → every ribbon for one board row, statuses first (background
 * closed/ghost states) then the option ribbons on top. `row` is
 * `{ options: OptionOut[], statuses: StatusOut[] }`.
 */
export function ribbonsFor(row: {
  options?: RibbonOption[];
  statuses?: RibbonStatus[];
}): Ribbon[] {
  const statuses = (row.statuses || []).map(statusRibbon);
  const options = (row.options || []).map(optionRibbon);
  return [...statuses, ...options];
}
