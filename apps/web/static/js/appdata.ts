// appdata.ts — the PURE data transforms behind the app shell.
//
// Lifted out of app.ts so they unit-test without a DOM, leaving app.ts as the thin
// composition root it is meant to be — the same split the fastapi-service convention
// applies on the server (logic in services, wiring in the router). Everything here is a
// pure function of its arguments: no fetch, no document, no history.

import type { Answer, SwimOption, SwimStatus, Week, WeekDay } from "./api.js";

type SwimAnswer = Answer;
type WeekData = Week;
type WeekDayEntry = WeekDay;

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
