// appdata.ts — the PURE data transforms behind the app shell.
//
// Lifted out of app.ts so they unit-test without a DOM, leaving app.ts as the thin
// composition root it is meant to be — the same split the fastapi-service convention
// applies on the server (logic in services, wiring in the router). Everything here is a
// pure function of its arguments: no fetch, no document, no history.

import type { Answer, SwimOption, SwimStatus, Week, WeekDay } from "./api.js";
import type { MessageKey } from "./i18n.js";

type SwimAnswer = Answer;
type WeekData = Week;
type WeekDayEntry = WeekDay;

// The three-state schedule freshness a `/swim` status / `/pools` row can carry
// (delete-curated-schedule-tier S1). A "scraped" pool has a real schedule (options, or a "closed"
// status); the two SCHEDULE-LESS states below replaced the single "uncurated" bucket. Each maps to
// its own honest label — unknown is NEVER "closed".
const UNLISTED_STATUS_LABEL: Readonly<Record<string, MessageKey>> = {
  awaiting_scrape: "status.awaiting_scrape", // indoor, scrapeable — hours not published yet
  no_source: "status.no_source", // no timetable source at all
};

/** A `/swim` status whose pool has no schedule (freshness `awaiting_scrape` | `no_source`). */
export function isUnlisted(status: string | null | undefined): boolean {
  return !!status && Object.hasOwn(UNLISTED_STATUS_LABEL, status);
}

/** The i18n key for a schedule-less status' label; falls back to the generic ghost copy. */
export function unlistedLabelKey(
  status: string | null | undefined,
): MessageKey {
  return (status && UNLISTED_STATUS_LABEL[status]) || "status.uncurated";
}

/** The FACILITY a clicked board row belongs to.
 *
 *  The two modes label rows differently: in Day view a row IS a pool, so the row label is
 *  the facility name; in Pool view the rows are the seven DAYS of the ONE selected pool,
 *  so the row label is a date ("Mon · 20 Jul") and the facility is the selection. Reading
 *  the row label in both modes is why the Pool-view panel lost its official-page link and
 *  its facts (a date is in no pool→url / pool→id map) and why a Pool-view row click
 *  overwrote `selectedPool.name` with a date, emptying the next week render.
 *
 *  Falls back to the ROW'S OWN facility (its options/statuses carry it in both views) and
 *  only then to the row label, so a caller always gets a name rather than null.
 *
 *  That middle step is load-bearing. A URL-restored `?view=pool&pool=<id>` arrives with an
 *  id and NO name (the name is backfilled from /pools, which resolves AFTER the first
 *  render's auto-open). Falling straight through to the row label then wrote a WEEKDAY
 *  into `selectedPool.name` — and because `backfillPoolName` skips a filter that already
 *  has a name, the weekday stuck permanently. Every later render filtered the week to
 *  options whose facility equalled "Monday", i.e. none: the pool rendered on first paint
 *  and went empty on the next re-render. */
export function rowFacilityName(
  mode: string | null | undefined,
  rowLabel: string,
  selectedName: string | null | undefined,
  rowFacility?: string | null,
): string {
  if (mode === "pool") return selectedName || rowFacility || rowLabel;
  return rowLabel;
}

/** A `/pools` PoolOut row, read structurally. */
export interface PoolMeta {
  pool_id: string;
  name: string;
  [k: string]: unknown;
}

/** One entry in the pool picker, classified honestly (see classifyPools). */
export interface PoolOption {
  value: string;
  label: string;
  state: string;
  distanceKm: number | null;
  closed?: boolean;
  note?: string;
}

// Lap-friendly access types: real lane-swim + public swim (both are lap-swimmable in
// a pool). The "Lap lanes only" toggle filters the fetched options to these client-side
// — there is no `/swim` lap param, so the board itself does the filtering (plan item 6).
const LAP_FRIENDLY = new Set(["LaneSwim", "PublicSwim"]);

// Keep only the selected pool's options/statuses in a Pool-mode week, so the board
// shows that one pool across seven days (not every nearby pool). When the pool is
// unplannable (no options — only a closed/uncurated status), this leaves the honest
// ghost/closed rows and NO fabricated ribbons (plan item 4).
export function focusWeekOnPool(
  week: WeekData,
  poolLabel: string | null,
): WeekData {
  if (!poolLabel) return week;
  return {
    facility: poolLabel,
    days: week.days.map((d: WeekDayEntry) => ({
      ...d,
      answer: {
        ...d.answer,
        options: (d.answer.options ?? []).filter(
          (o: SwimOption) => o.facility === poolLabel,
        ),
        statuses: (d.answer.statuses ?? []).filter(
          (s: SwimStatus) => s.facility === poolLabel,
        ),
      },
    })),
  };
}

// Filter a `/swim` answer's options to the lap-friendly access types (no-op unless
// the toggle is on). A day left with no lap-friendly session shows as an empty row —
// an honest "no lap swim here" — rather than inventing a lane session.
export function applyLap(answer: SwimAnswer, lapOnly: boolean): SwimAnswer {
  if (!lapOnly || !answer) return answer;
  return {
    ...answer,
    options: (answer.options || []).filter((o) =>
      LAP_FRIENDLY.has(String(o.access)),
    ),
  };
}

export function applyLapWeek(week: WeekData, lapOnly: boolean): WeekData {
  if (!lapOnly) return week;
  return {
    ...week,
    days: week.days.map((d) => ({ ...d, answer: applyLap(d.answer, lapOnly) })),
  };
}

// Classify the poolsMeta (/pools) against a day's `/swim` answer into the pool-picker
// options, HONESTLY (plan item 4): a pool with sessions is PLANNABLE (listed first,
// no badge, carrying its distance), a genuinely closed pool is 'closed', and a pool
// with no curated timetable is 'no timetable yet' (NEVER "closed" — unknown ≠ closed).
export function classifyPools(
  poolsMeta: PoolMeta[],
  dayAnswer: SwimAnswer,
): PoolOption[] {
  const dist = new Map<string, number | null>(); // facility name → nearest distance_km
  for (const o of dayAnswer.options || []) {
    const cur = dist.get(o.facility);
    if (o.distance_km != null && (cur == null || o.distance_km < cur))
      dist.set(o.facility, o.distance_km);
    else if (!dist.has(o.facility)) dist.set(o.facility, o.distance_km ?? null);
  }
  const closed = new Set(
    (dayAnswer.statuses || [])
      .filter((s: SwimStatus) => s.status === "closed")
      .map((s: SwimStatus) => s.facility),
  );
  const plannableNames = new Set(dist.keys());

  const rank = (p: { name: string }) =>
    plannableNames.has(p.name) ? 0 : closed.has(p.name) ? 1 : 2;
  const items: PoolOption[] = poolsMeta.map((p) => {
    const state = plannableNames.has(p.name)
      ? // eslint-disable-next-line i18next/no-literal-string -- state keys, not copy
        "plannable"
      : closed.has(p.name)
        ? "closed"
        : "unknown";
    return {
      value: p.pool_id,
      label: p.name,
      state,
      distanceKm: dist.get(p.name) ?? null,
      // Combobox badges: plannable → none; closed → 'closed'; unknown → 'no timetable yet'.
      ...(state === "closed" ? { closed: true } : {}),
      ...(state === "unknown" ? { note: "no timetable yet" } : {}),
    };
  });
  items.sort((a, b) => {
    const ra = rank({ name: a.label });
    const rb = rank({ name: b.label });
    if (ra !== rb) return ra - rb;
    if (ra === 0) return (a.distanceKm ?? 1e9) - (b.distanceKm ?? 1e9); // plannable: nearest first
    return a.label.localeCompare(b.label);
  });
  return items;
}

/**
 * Whether a URL change is STRUCTURAL (a different view or a different pool) and so
 * deserves a history entry, versus a plain filter toggle that should replace it.
 *
 * Pure so the rule is testable: getting it wrong is subtle — too eager and Back becomes
 * unusable after a few toggles; too lazy and Back skips past pools the user visited.
 */
export function isStructuralUrlChange(
  prev: { mode?: string; selectedPool?: { id?: string | null } | null },
  next: { mode?: string; selectedPool?: { id?: string | null } | null },
): boolean {
  const view = (f: { mode?: string }) => (f.mode === "pool" ? "pool" : "day");
  const pool = (f: { selectedPool?: { id?: string | null } | null }) =>
    f.selectedPool?.id ?? null;
  return view(prev) !== view(next) || pool(prev) !== pool(next);
}
