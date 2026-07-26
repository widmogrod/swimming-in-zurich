// insightbar.js — the InsightBar block (plan Part 3 §3).
//
// A single mode-aware summary line computed from the FETCHED data:
//   - Day mode : "N pools with curated hours nearby · best public window X/Y at
//                 <facility> HH:MM–HH:MM".
//   - Pool mode: "Reliable public lanes: up to X of Y around HH:MM · open D of 7
//                 days this week".
// The number is honest: it is the best actual public-lane window in the data, and
// degrades to a plain sentence when no lane split is published (never invented).
//
// The computation is PURE (`computeInsight`) so it unit-tests headless; the thin
// `createInsightBar` only writes the derived text into the DOM. No colour, no hex.

import { asDoc, type El } from '../domtypes.js';
import { t } from '../i18n.js';

/** The slice of a `/swim` option the insight summary reads. */
export interface InsightOption {
  facility?: string;
  lane_timeline?: { segments?: InsightSegment[] } | null;
  [k: string]: unknown;
}

export interface InsightSegment {
  start: string;
  end: string;
  lane_count: number;
  public_lanes: number;
  [k: string]: unknown;
}

export interface InsightStatus {
  status?: string;
  detail?: string | null;
}

export interface InsightAnswer {
  options?: InsightOption[];
  statuses?: InsightStatus[];
}

export interface InsightWeek {
  facility?: string | null;
  days?: { answer?: InsightAnswer }[];
}

/** The best public-lane window across a set of options. */
export interface BestWindow {
  facility: string | undefined;
  public_lanes: number;
  lane_count: number;
  start: string;
  end: string;
}

/** The computed summary. `text` is the rendered sentence; every other field is the DATA
 *  behind it — which is what lets S3 key a message and pass params instead of shipping a
 *  concatenated English string. */
export interface Insight {
  mode: string;
  text: string;
  best: BestWindow | null;
  poolsCount?: number;
  closed?: number;
  unlisted?: number;
  openDays?: number;
}

export interface InsightData {
  day?: InsightAnswer;
  week?: InsightWeek;
}

// The best public-lane window across a set of `/swim` options: the lane_timeline
// segment with the MOST public lanes (ties broken by earliest start), tagged with
// its facility. null when no option publishes a lane split.
function bestWindow(options: InsightOption[] | undefined) {
  let best = null;
  for (const o of options || []) {
    const tl = o.lane_timeline;
    if (!tl || !tl.segments) continue;
    for (const seg of tl.segments) {
      const cand = {
        facility: o.facility,
        public_lanes: seg.public_lanes,
        lane_count: seg.lane_count,
        start: seg.start,
        end: seg.end,
      };
      if (
        best === null ||
        cand.public_lanes > best.public_lanes ||
        (cand.public_lanes === best.public_lanes && cand.start < best.start)
      ) {
        best = cand;
      }
    }
  }
  return best;
}

// Distinct facility names that produced at least one session (curated hours).
function facilitiesWithHours(options: InsightOption[] | undefined): number {
  return new Set((options || []).map((o) => o.facility)).size;
}

// The honest coverage split from the answer's statuses: how many nearby pools are
// closed (with reason) vs merely hours-not-listed (unknown ≠ closed).
function honestyCounts(answer: InsightAnswer | undefined) {
  const statuses = (answer && answer.statuses) || [];
  let closed = 0;
  let unlisted = 0;
  for (const s of statuses) {
    if (s.status === 'closed') closed += 1;
    else if (s.status === 'uncurated') unlisted += 1;
  }
  return { closed, unlisted };
}

/** Join independent clauses for display. NOT sentence assembly: each clause is a whole
 *  translatable message, and ' · ' is punctuation between list items, never grammar. */
function clauses(...parts: (string | null)[]): string {
  return parts.filter((p): p is string => !!p).join(' · ');
}

function dayInsight(answer: InsightAnswer | undefined): Insight {
  const options = (answer && answer.options) || [];
  const n = facilitiesWithHours(options);
  const best = bestWindow(options);
  const { closed, unlisted } = honestyCounts(answer);

  // Clause 1: how many pools we can actually plan with (or an honest "none").
  const lead = n > 0 ? t('insight.day.pools', { count: n }) : t('insight.day.none');
  // Clause 2: the best window, or why there isn't one. Absent entirely when we have
  // no plannable pools — there is nothing to qualify.
  const window =
    n === 0
      ? null
      : best
        ? t('insight.bestWindow', {
            public: best.public_lanes,
            total: best.lane_count,
            facility: best.facility ?? '',
            start: best.start,
            end: best.end,
          })
        : t('insight.noSplit');
  // Clause 3: the honest coverage split, so the line states WHY the other nearby pools
  // aren't plannable (plan FIX 5).
  const coverage = closed || unlisted ? t('insight.coverage', { closed, unlisted }) : null;

  return {
    mode: 'day',
    poolsCount: n,
    best,
    closed,
    unlisted,
    text: clauses(lead, window, coverage),
  };
}

function poolInsight(week: InsightWeek | undefined): Insight {
  const days = (week && week.days) || [];
  const openDays = days.filter((d) => (d.answer?.options ?? []).length > 0).length;
  const allOptions: InsightOption[] = days.flatMap((d) => d.answer?.options ?? []);
  const best = bestWindow(allOptions);
  const facility = week && week.facility ? week.facility : t('insight.pool.thisPool');

  if (!best && openDays === 0) {
    return { mode: 'pool', openDays, best, text: t('insight.pool.none', { facility }) };
  }
  const lead = best
    ? t('insight.pool.reliable', {
        facility,
        public: best.public_lanes,
        total: best.lane_count,
        start: best.start,
      })
    : null;
  const daysClause = t('insight.pool.openDays', { count: openDays });
  const split = best ? null : t('insight.noSplit');
  return { mode: 'pool', openDays, best, text: clauses(lead, daysClause, split) };
}

/**
 * computeInsight(data, filter) → { mode, text, … } — the mode-aware summary.
 * @param {object} data `{ day: AnswerOut, week: {facility, days:[{answer}]} }`.
 * @param {object} filter FilterState (its `mode` selects Day vs Pool).
 */
export function computeInsight(
  data: InsightData | undefined,
  filter: { mode?: string } | undefined,
): Insight {
  if (filter && filter.mode === 'pool') return poolInsight(data && data.week);
  return dayInsight(data && data.day);
}

/**
 * createInsightBar(el, opts) — mount the InsightBar into `el` and paint the
 * current summary. Call `update(data, filter)` on every refetch.
 */
export function createInsightBar<T extends El>(
  el: T,
  opts: { data?: InsightData; filter?: { mode?: string } } = {},
) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  el.classList.add('insight');
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');

  const line = doc.createElement('p');
  line.className = 'insight__line';
  el.appendChild(line);

  function update(data?: InsightData, filter?: { mode?: string }) {
    const insight = computeInsight(data || {}, filter || { mode: 'day' });
    line.textContent = insight.text;
    return insight;
  }

  if (opts.data || opts.filter) update(opts.data, opts.filter);

  return { el, update };
}
