// poolrank.ts — the PURE ranking + verdict logic behind the phone pool list.
//
// No DOM, no canvas, no i18n formatting decisions beyond choosing a message key: this
// module decides WHAT a row says and WHERE it sorts, and poollist.ts renders it. That
// split exists because the ranking is the risky part of the phone design — the desktop
// board shows every pool at once and lets the eye rank them, so a bad sort is cosmetic;
// a phone list IS the answer, and a bad sort is a wrong answer. It belongs under test.
//
// Two honesty rules are encoded here rather than left to the renderer:
//
//   1. A session with reserved lanes is NOT "open now". Saying so promises water that may
//      not be there, so it reads "Partly reserved · N of M lanes public". It also does not
//      count toward "open to you", which must mean exactly what it says.
//   2. Closed is not the same as not-for-you. A pool shut for maintenance says "closed",
//      never "✕ not for you" — that would blame the swimmer for the pool's outage.

import { hhmmToMin } from './cursor.js';
import type { MessageKey } from '../i18n.js';

/** The tiers a row can land in, in display order. */
export const TIERS = ['now', 'soon', 'unknown', 'closed'] as const;
export type Tier = (typeof TIERS)[number];

const TIER_ORDER: Record<Tier, number> = { now: 0, soon: 1, unknown: 2, closed: 3 };

/** The tier headings, as message keys (the renderer calls `t`). */
export const TIER_KEY: Record<Tier, MessageKey> = {
  now: 'mobile.tier.now',
  soon: 'mobile.tier.soon',
  unknown: 'mobile.tier.unknown',
  closed: 'mobile.tier.closed',
};

/** A `/swim` option, read structurally — only what the ranking needs. */
export interface RankOption {
  start?: string;
  end?: string;
  access?: string;
  facility?: string;
  distance_km?: number | null;
  eligible?: boolean;
  lane_timeline?: { segments?: RankLaneSegment[] } | null;
  [k: string]: unknown;
}

export interface RankLaneSegment {
  start: string;
  end: string;
  lane_count: number;
  public_lanes: number;
  [k: string]: unknown;
}

export interface RankStatus {
  status: string;
}

export interface RankRow {
  label: string;
  options?: RankOption[];
  statuses?: RankStatus[];
}

/** How many lanes are public within an option at `min`, when it publishes a split. */
export interface LaneSplit {
  public_lanes: number;
  lane_count: number;
}

/** optionAt(options, min) — the option covering `min`, or null. */
export function optionAt(options: RankOption[], min: number): RankOption | null {
  for (const o of options) {
    const s = hhmmToMin(o.start ?? '');
    const e = hhmmToMin(o.end ?? '');
    if (min >= s && min < e) return o;
  }
  return null;
}

/** optionNext(options, min) — the soonest option starting after `min`, or null. */
export function optionNext(options: RankOption[], min: number): RankOption | null {
  let best: RankOption | null = null;
  let bestMin = Infinity;
  for (const o of options) {
    const s = hhmmToMin(o.start ?? '');
    if (s > min && s < bestMin) {
      best = o;
      bestMin = s;
    }
  }
  return best;
}

/** laneSplitAt(option, min) — the published split covering `min`, or null when the
 *  option publishes no lane timeline (which is a real, distinct state — not a zero). */
export function laneSplitAt(option: RankOption | null, min: number): LaneSplit | null {
  const segments = option?.lane_timeline?.segments;
  if (!segments || !segments.length) return null;
  for (const seg of segments) {
    if (min >= hhmmToMin(seg.start) && min < hhmmToMin(seg.end)) {
      if (!(seg.lane_count > 0)) return null;
      return { public_lanes: seg.public_lanes, lane_count: seg.lane_count };
    }
  }
  return null;
}

/** `true` when some lanes in the covering segment are held back from the public. */
export function isPartlyReserved(split: LaneSplit | null): boolean {
  return !!split && split.public_lanes < split.lane_count;
}

/** A row's terminal state, if it has one. Closed beats uncurated. */
export function terminalStatus(row: RankRow): 'closed' | 'unknown' | null {
  const statuses = row.statuses ?? [];
  if (statuses.some((s) => s.status === 'closed')) return 'closed';
  if (statuses.some((s) => s.status === 'uncurated')) return 'unknown';
  return null;
}

/**
 * tierFor(row, min) — which group the row sorts into.
 *
 * A row with options that publishes no lane split still ranks by its hours, not into
 * `unknown`: it IS open, we simply cannot say how many lanes are yours. `unknown` is
 * reserved for a row with no published hours at all.
 */
export function tierFor(row: RankRow, min: number): Tier {
  const options = row.options ?? [];
  if (!options.length) {
    const terminal = terminalStatus(row);
    return terminal === 'closed' ? 'closed' : 'unknown';
  }
  if (optionAt(options, min)) return 'now';
  // `soon` has to MEAN soon. A pool whose sessions have all ended has nothing left to
  // wait for, and filing it under "Later today" produced a card that read
  // "Later today / Done for today" — the heading contradicting the verdict beneath it.
  return optionNext(options, min) ? 'soon' : 'closed';
}

/** The head of the verdict: the bolded claim. */
export interface Verdict {
  key: MessageKey;
  params: Record<string, string | number>;
  /** The muted trailing clause, a whole translatable unit (may be null). */
  tailKey: MessageKey | null;
  tailParams: Record<string, string | number>;
}

/**
 * verdictFor(row, min) — the sentence a row leads with.
 *
 * Deliberately a clause LIST (head · tail), never a sentence assembled by concatenation:
 * each clause stands alone and a translator may reorder freely inside it. See the
 * catalogue's note on the InsightBar for why that distinction is safe here.
 */
export function verdictFor(row: RankRow, min: number): Verdict {
  const options = row.options ?? [];
  const none = {} as Record<string, string | number>;
  if (!options.length) {
    const terminal = terminalStatus(row);
    return terminal === 'closed'
      ? { key: 'mobile.verdict.closedAllDay', params: none, tailKey: null, tailParams: none }
      : { key: 'mobile.verdict.hoursUnknown', params: none, tailKey: null, tailParams: none };
  }
  const current = optionAt(options, min);
  if (!current) {
    const next = optionNext(options, min);
    if (!next) {
      return { key: 'mobile.verdict.doneForToday', params: none, tailKey: null, tailParams: none };
    }
    return {
      key: 'mobile.verdict.opensAt',
      params: { hhmm: next.start ?? '' },
      tailKey: null,
      tailParams: none,
    };
  }
  const split = laneSplitAt(current, min);
  if (current.eligible === false) {
    const next = optionNext(options, min);
    return {
      key: 'mobile.verdict.notYoursUntil',
      params: { hhmm: next?.start ?? current.end ?? '' },
      tailKey: 'mobile.verdict.untilTime',
      tailParams: { hhmm: current.end ?? '' },
    };
  }
  if (isPartlyReserved(split) && split) {
    return {
      key: 'mobile.verdict.partlyReserved',
      params: none,
      tailKey: 'mobile.lanesUntil',
      tailParams: {
        public: split.public_lanes,
        total: split.lane_count,
        hhmm: current.end ?? '',
      },
    };
  }
  return {
    key: 'mobile.verdict.openNow',
    params: none,
    tailKey: 'mobile.verdict.untilTime',
    tailParams: { hhmm: current.end ?? '' },
  };
}

/** A row, ranked. */
export interface RankedRow {
  row: RankRow;
  tier: Tier;
  verdict: Verdict;
  /** `true` only when the row is open AND wholly open to this viewer. */
  openToYou: boolean;
  distanceKm: number | null;
}

function rowDistance(row: RankRow): number | null {
  for (const o of row.options ?? []) {
    if (typeof o.distance_km === 'number') return o.distance_km;
  }
  return null;
}

/**
 * rankRows(rows, min) — group into tiers, then nearest-first inside each tier.
 *
 * A row with no distance sorts last within its tier rather than first, which is what a
 * missing number should cost: absence must never outrank a real, worse value.
 */
export function rankRows(rows: RankRow[], min: number): RankedRow[] {
  const ranked = rows.map((row) => {
    const tier = tierFor(row, min);
    const current = optionAt(row.options ?? [], min);
    const split = laneSplitAt(current, min);
    return {
      row,
      tier,
      verdict: verdictFor(row, min),
      openToYou: tier === 'now' && current?.eligible !== false && !isPartlyReserved(split),
      distanceKm: rowDistance(row),
    };
  });
  return ranked.sort((a, b) => {
    if (TIER_ORDER[a.tier] !== TIER_ORDER[b.tier]) return TIER_ORDER[a.tier] - TIER_ORDER[b.tier];
    const da = a.distanceKm ?? Infinity;
    const db = b.distanceKm ?? Infinity;
    if (da !== db) return da - db;
    return String(a.row.label).localeCompare(String(b.row.label));
  });
}

/** countOpenToYou(ranked) — the number the summary tag leads with. */
export function countOpenToYou(ranked: RankedRow[]): number {
  return ranked.filter((r) => r.openToYou).length;
}

/** tierCounts(ranked) — how many rows landed in each tier, for the group headings. */
export function tierCounts(ranked: RankedRow[]): Record<Tier, number> {
  const out: Record<Tier, number> = { now: 0, soon: 0, unknown: 0, closed: 0 };
  for (const r of ranked) out[r.tier] += 1;
  return out;
}
