// filterstate.js — the ONE immutable filter context that drives every block.
//
// Authored at S0, first *observed* in S2/S4 (plan Decisions). It carries the whole
// global query surface: place (lat/lon + human label), the day (Day mode) or week
// (Pool mode), gender, age, mode, and the two boolean refinements. FilterToolbar
// emits it; the board / gantt / panel read it. Everything here is pure — merge
// returns a NEW state and never mutates — so it is unit-testable without a DOM.

/** The zero state: no place, no date, nothing filtered. Frozen so it can't drift. */
export const DEFAULT_FILTER = Object.freeze({
  place: Object.freeze({ lat: null, lon: null, label: '' }),
  date: null, // ISO date (YYYY-MM-DD) — Day mode
  week: null, // ISO Monday (YYYY-MM-DD) — Pool/week mode
  gender: '', // '' | 'female' | 'male' | 'diverse'
  age: null, // number | null
  mode: 'day', // 'day' | 'pool'
  // The ONE currently-selected pool, shared by Day and Pool views:
  // `{ id: <facility_id>, name: <display name> } | null`. `null` = no explicit
  // choice yet. A normal top-level key — `merge` overwrites it WHOLESALE (never
  // shallow-merged like `place`), and serialize/deserialize carry it for free.
  selectedPool: null,
  lapOnly: false,
  eligibleOnly: false,
});

/**
 * merge(state, patch) → a new FilterState with patch applied.
 * Top-level keys are overwritten; `place` is merged shallowly so a patch may
 * change just the label without dropping lat/lon. Neither argument is mutated.
 */
export function merge(state, patch = {}) {
  const next = { ...state, ...patch };
  next.place = { ...state.place, ...(patch.place || {}) };
  return next;
}

/** Build a state from partial input, filling gaps from DEFAULT_FILTER. */
export function createFilterState(init = {}) {
  return merge(DEFAULT_FILTER, init);
}

/** serialize(state) → a JSON string (URL/query/localStorage friendly). */
export function serialize(state) {
  return JSON.stringify(state);
}

/** deserialize(text) → a FilterState, normalised through DEFAULT_FILTER. */
export function deserialize(text) {
  return merge(DEFAULT_FILTER, JSON.parse(text));
}
