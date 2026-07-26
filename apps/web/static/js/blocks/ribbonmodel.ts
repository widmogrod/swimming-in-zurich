import { t } from '../i18n.js';
// ribbonmodel.js — PURE mapping of a `/swim` option/status → a ribbon render state.
//
// No canvas, no DOM (plan Risk #2: keep the drawable logic testable without a
// browser). The board's canvas renderer consumes these plain objects; every visual
// decision (dashed vs dotted, thickness, pinch, sheath, colour family) is decided
// HERE and unit-tested against saved `/swim` fixtures.
//
// The three terminal states are never merged (product invariant): a `closed` status
// is a DASHED ribbon carrying its reason; an `uncurated` status is a DOTTED ghost;
// an option with no published lane split is its own "not published" ribbon — none
// of them collapses into another.

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
});

/** A `/swim` option as the ribbon model reads it. */
export interface RibbonOption {
  access?: string;
  start?: string;
  end?: string;
  facility?: string;
  basin?: string;
  lane_timeline?: { segments?: RibbonTimelineSegment[] } | null;
  [k: string]: unknown;
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
 * optionRibbon(option) → a ribbon render state for a `/swim` option.
 *   - with `lane_timeline`  → a FILLED ribbon; each segment's `thickness` is the
 *     public fraction (public_lanes/lane_count) and it is `pinched` wherever any
 *     lane is reserved (reserved_lanes>0); `sheath:true` draws the capacity envelope.
 *   - without `lane_timeline` → a "lane split not published" ribbon (`sheath:false`).
 * The colour `family` is set in both cases.
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
    label: t('insight.noSplit.label'),
  };
}

/**
 * statusRibbon(status) → a ribbon render state for a `/swim` status entry.
 *   - status === 'closed'    → a DASHED closed ribbon carrying `detail`.
 *   - status === 'uncurated' → a DOTTED ghost ribbon (unknown ≠ closed).
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
  return { ...base, variant: 'ghost', style: 'dotted', family: 'unknown' };
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
