// api.js — the live data layer (plan Part 5 §Data).
//
// The app hydrates every block from the existing JSON endpoints (`/swim`,
// `/pools/{id}`). This module owns the URL/param construction and the two fetch
// shapes the app needs:
//   - Day mode  → ONE `/swim` call for the chosen date (the whole day's sessions).
//   - Pool mode → the SEVEN weekday `/swim` calls the current planner assembles
//     (Option A: /swim resolves a whole day per call, so 7 calls = the week).
// plus `/pools/{id}` for a facility's lane_panels (the DetailPanel/Gantt data).
//
// The URL/param builders are PURE (no fetch, no DOM) so they unit-test under
// `node --test`; the thin fetch wrappers take an injectable `fetch` so they can
// be exercised without a browser too. No colour, no hex — this is a data module.

// The UTC date arithmetic lives in datefmt.ts — it was duplicated here, in toolbar and
// in urlstate. Re-exported so existing importers of this module keep working.
import { dayParts, weekDates } from "./datefmt.js";
import { locale } from "./i18n.js";
export { isoDate, mondayOf, shiftIso, weekDates } from "./datefmt.js";

// The hardcoded English WEEKDAY_LABELS table that used to live here is gone: weekday
// names now come from `Intl` per locale (dayParts). A table cannot express Polish,
// which lowercases weekday names.

// ---- Wire shapes -------------------------------------------------------------------
//
// Declared LOCALLY and structurally (the same convention urlstate.ts follows): this
// module reads only the slice of each payload it actually projects, so the untyped
// `filterstate.js` stays untouched and the API models are not duplicated wholesale.

/** The slice of FilterState that /swim query construction reads. */
export interface SwimFilter {
  place?: { lat?: number | null; lon?: number | null } | null;
  gender?: string;
  age?: number | string | null;
  selectedPool?: { id?: string | null; name?: string | null } | null;
}

/** A `/swim` option row, read structurally. */
export interface SwimOption {
  facility: string;
  access?: string;
  /** The basin's stable id — the board row key (`OptionOut.basin_id`, added in S2). */
  basin_id?: string;
  basin?: string;
  distance_km?: number | null;
  [k: string]: unknown;
}

/** A `/swim` facility status row. */
export interface SwimStatus {
  facility: string;
  status: string;
  detail?: string | null;
}

/** A single `/swim` AnswerOut, read structurally. */
export interface Answer {
  options: SwimOption[];
  statuses: SwimStatus[];
  warnings: unknown[];
  notices: unknown[];
}

export interface WeekDay {
  label: string;
  iso: string;
  answer: Answer;
}

export interface Week {
  facility: string | null;
  days: WeekDay[];
}

/** A `/pools/{id}` FacilityDetailOut — opaque here; blocks narrow what they read. */
export type PoolDetail = Record<string, unknown>;

/** The injectable fetch the pure/headless paths take. */
export type FetchLike = (
  url: string,
) => Promise<{ ok: boolean; json(): Promise<unknown> }>;

// A representative moment inside a day — noon — so `/swim` returns that whole
// day's sessions (each option carries its own start/end; open_now is per-session).
const DAY_MOMENT = "T12:00";

/**
 * swimParams(filter, iso) → a plain {key: value} map of query params for a
 * single `/swim` call on the given ISO date. eligible_only is ALWAYS false: the
 * board shows every session and conveys eligibility through the ✓/?/✕ badge, so
 * lap-only / gender / age never *drop* rows here (they annotate). Pure.
 * @param {object} filter FilterState (place/gender/age).
 * @param {string} iso the day, 'YYYY-MM-DD'.
 */
export function swimParams(
  filter: SwimFilter,
  iso: string,
): Record<string, string> {
  const params: Record<string, string> = {
    at: `${iso}${DAY_MOMENT}`,
    eligible_only: "false",
  };
  const place = filter.place || {};
  if (place.lat != null && place.lon != null) {
    params.lat = String(place.lat);
    params.lon = String(place.lon);
  }
  if (filter.gender) params.gender = filter.gender;
  if (filter.age != null && filter.age !== "") params.age = String(filter.age);
  return params;
}

/** swimUrl(filter, iso) → '/swim?…'. Pure (keys sorted for a stable string). */
export function swimUrl(filter: SwimFilter, iso: string): string {
  const params = swimParams(filter, iso);
  const qs = Object.keys(params)
    // eslint-disable-next-line i18next/no-literal-string -- query-string assembly, not copy
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    // eslint-disable-next-line i18next/no-literal-string -- query-string assembly, not copy
    .join("&");
  // eslint-disable-next-line i18next/no-literal-string -- an API path, not copy
  return `/swim?${qs}`;
}

/** poolUrl(id, iso) → '/pools/{id}?at=…' (or no query when iso is absent). Pure. */
export function poolUrl(id: string, iso?: string | null): string {
  // eslint-disable-next-line i18next/no-literal-string -- an API path, not copy
  const base = `/pools/${encodeURIComponent(id)}`;
  // eslint-disable-next-line i18next/no-literal-string -- an API path, not copy
  return iso ? `${base}?at=${encodeURIComponent(`${iso}${DAY_MOMENT}`)}` : base;
}

// The empty answer used when a call fails — an honest "nothing", never a throw,
// so one bad weekday call cannot blank the whole board.
const EMPTY_ANSWER: Answer = {
  options: [],
  statuses: [],
  warnings: [],
  notices: [],
};

function pickFetch(fetchImpl?: FetchLike): FetchLike {
  const f =
    fetchImpl ||
    (typeof globalThis.fetch === "function" ? globalThis.fetch : null);
  if (!f)
    throw new Error("api: no fetch available (pass one in headless contexts)");
  return f;
}

async function getJson<T>(
  url: string,
  fetchImpl: FetchLike | undefined,
  fallback: T,
): Promise<T> {
  const res = await pickFetch(fetchImpl)(url);
  if (!res.ok) return fallback;
  return (await res.json()) as T;
}

/** fetchDay(filter, iso, fetch?) → the day's `/swim` AnswerOut. */
export async function fetchDay(
  filter: SwimFilter,
  iso: string,
  fetchImpl?: FetchLike,
): Promise<Answer> {
  return getJson(swimUrl(filter, iso), fetchImpl, { ...EMPTY_ANSWER });
}

/**
 * fetchWeek(filter, weekIso, fetch?) → `{ facility, days:[{label, iso, answer}] }`
 * — the SAME shape the board's Pool mode consumes (weekRows). One `/swim` call
 * per weekday, gathered with Promise.all (Option A, no API change).
 * @param {object} filter FilterState (place/gender/age + the selectedPool id/name).
 */
export async function fetchWeek(
  filter: SwimFilter,
  weekIso: string,
  fetchImpl?: FetchLike,
): Promise<Week> {
  const dates = weekDates(weekIso);
  const answers = await Promise.all(
    dates.map((iso) =>
      getJson(swimUrl(filter, iso), fetchImpl, { ...EMPTY_ANSWER }),
    ),
  );
  const facility = filter.selectedPool?.name ? filter.selectedPool.name : null;
  // The row label is derived from the date itself, per locale — not read off a fixed
  // English table positionally.
  const days = dates.map((iso, i) => ({
    label: dayParts(iso, locale()).weekday,
    iso,
    answer: answers[i],
  }));
  return { facility, days };
}

/** fetchPoolDetail(id, iso, fetch?) → a `/pools/{id}` FacilityDetailOut, or null. */
export async function fetchPoolDetail(
  id: string,
  iso?: string | null,
  fetchImpl?: FetchLike,
): Promise<PoolDetail | null> {
  return getJson(poolUrl(id, iso), fetchImpl, null);
}
