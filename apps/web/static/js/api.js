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

// Parse an ISO date (YYYY-MM-DD) as UTC midnight — the SAME pattern DateStepper
// uses — so weekday arithmetic never drifts a day in a positive-offset zone.
function parseUtc(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** isoDate(date) → 'YYYY-MM-DD' (UTC). */
export function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

/** shiftIso('2026-07-23', 2) → '2026-07-25'. Pure UTC date arithmetic. */
export function shiftIso(iso, days) {
  const d = parseUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

/** mondayOf('2026-07-23') → the ISO Monday of that date's week (Mon=0). Pure. */
export function mondayOf(iso) {
  const d = parseUtc(iso);
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  d.setUTCDate(d.getUTCDate() - dow);
  return isoDate(d);
}

/** weekDates(mondayIso) → the 7 ISO dates Mon…Sun of that week. Pure. */
export function weekDates(mondayIso) {
  const monday = mondayOf(mondayIso);
  return Array.from({ length: 7 }, (_, i) => shiftIso(monday, i));
}

// The weekday labels the board's Pool-mode rows carry, aligned to weekDates order.
export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// A representative moment inside a day — noon — so `/swim` returns that whole
// day's sessions (each option carries its own start/end; open_now is per-session).
const DAY_MOMENT = 'T12:00';

/**
 * swimParams(filter, iso) → a plain {key: value} map of query params for a
 * single `/swim` call on the given ISO date. eligible_only is ALWAYS false: the
 * board shows every session and conveys eligibility through the ✓/?/✕ badge, so
 * lap-only / gender / age never *drop* rows here (they annotate). Pure.
 * @param {object} filter FilterState (place/gender/age).
 * @param {string} iso the day, 'YYYY-MM-DD'.
 */
export function swimParams(filter, iso) {
  const params = { at: `${iso}${DAY_MOMENT}`, eligible_only: 'false' };
  const place = filter.place || {};
  if (place.lat != null && place.lon != null) {
    params.lat = String(place.lat);
    params.lon = String(place.lon);
  }
  if (filter.gender) params.gender = filter.gender;
  if (filter.age != null && filter.age !== '') params.age = String(filter.age);
  return params;
}

/** swimUrl(filter, iso) → '/swim?…'. Pure (keys sorted for a stable string). */
export function swimUrl(filter, iso) {
  const params = swimParams(filter, iso);
  const qs = Object.keys(params)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&');
  return `/swim?${qs}`;
}

/** poolUrl(id, iso) → '/pools/{id}?at=…' (or no query when iso is absent). Pure. */
export function poolUrl(id, iso) {
  const base = `/pools/${encodeURIComponent(id)}`;
  return iso ? `${base}?at=${encodeURIComponent(`${iso}${DAY_MOMENT}`)}` : base;
}

// The empty answer used when a call fails — an honest "nothing", never a throw,
// so one bad weekday call cannot blank the whole board.
const EMPTY_ANSWER = { options: [], statuses: [], warnings: [], notices: [] };

function pickFetch(fetchImpl) {
  const f = fetchImpl || (typeof globalThis.fetch === 'function' ? globalThis.fetch : null);
  if (!f) throw new Error('api: no fetch available (pass one in headless contexts)');
  return f;
}

async function getJson(url, fetchImpl, fallback) {
  const res = await pickFetch(fetchImpl)(url);
  if (!res.ok) return fallback;
  return res.json();
}

/** fetchDay(filter, iso, fetch?) → the day's `/swim` AnswerOut. */
export async function fetchDay(filter, iso, fetchImpl) {
  return getJson(swimUrl(filter, iso), fetchImpl, { ...EMPTY_ANSWER });
}

/**
 * fetchWeek(filter, weekIso, fetch?) → `{ facility, days:[{label, iso, answer}] }`
 * — the SAME shape the board's Pool mode consumes (weekRows). One `/swim` call
 * per weekday, gathered with Promise.all (Option A, no API change).
 * @param {object} filter FilterState (place/gender/age + the selected pool id/name).
 */
export async function fetchWeek(filter, weekIso, fetchImpl) {
  const dates = weekDates(weekIso);
  const answers = await Promise.all(
    dates.map((iso) => getJson(swimUrl(filter, iso), fetchImpl, { ...EMPTY_ANSWER })),
  );
  const facility = filter.pool && filter.pool.label ? filter.pool.label : null;
  const days = dates.map((iso, i) => ({ label: WEEKDAY_LABELS[i], iso, answer: answers[i] }));
  return { facility, days };
}

/** fetchPoolDetail(id, iso, fetch?) → a `/pools/{id}` FacilityDetailOut, or null. */
export async function fetchPoolDetail(id, iso, fetchImpl) {
  return getJson(poolUrl(id, iso), fetchImpl, null);
}
