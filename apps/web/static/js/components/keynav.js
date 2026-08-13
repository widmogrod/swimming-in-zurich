// keynav.js — PURE keyboard-navigation + filter helpers (no DOM).
//
// Risk #2 mitigation: keep all navigation LOGIC in pure functions so it is
// unit-testable without a browser. The component factories call these; the fake
// DOM never has to model key semantics.

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown']);
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp']);

/**
 * rovingIndex(current, length, key) → next index for a roving single-select
 * group (SegmentedControl / ChipGroup). Wraps by default. Returns `null` when
 * `key` is not a navigation key (caller should ignore the event).
 */
export function rovingIndex(current, length, key, { wrap = true } = {}) {
  if (length <= 0) return null;
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  let delta = 0;
  if (NEXT_KEYS.has(key)) delta = 1;
  else if (PREV_KEYS.has(key)) delta = -1;
  else return null;
  let next = current + delta;
  if (wrap) next = (next + length) % length;
  else next = Math.max(0, Math.min(length - 1, next));
  return next;
}

/**
 * listboxIndex(active, length, key) → next active-descendant index for a
 * combobox listbox. ArrowDown/Up move (wrapping from the closed -1 state);
 * Home/End jump. Returns `null` for non-navigation keys.
 */
export function listboxIndex(active, length, key) {
  if (length <= 0) return -1;
  if (key === 'ArrowDown') return active < 0 ? 0 : (active + 1) % length;
  if (key === 'ArrowUp') return active <= 0 ? length - 1 : active - 1;
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  return null;
}

/**
 * filterOptions(options, query, filterFn?) → the subset matching `query`.
 * Case-insensitive substring on `label` by default; a caller-supplied
 * `filterFn(option, loweredQuery)` overrides. Empty query returns a copy of all.
 */
export function filterOptions(options, query, filterFn) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return options.slice();
  if (filterFn) return options.filter((o) => filterFn(o, q));
  return options.filter((o) => String(o.label).toLowerCase().includes(q));
}
