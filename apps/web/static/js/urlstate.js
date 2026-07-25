// urlstate.js — the URL is a PURE PROJECTION of the one FilterState (plan: shareable
// links). A shared link restores the exact pool + filters + view; nothing else is a
// second source of truth. Location is deliberately NOT encoded (a client-side choice,
// never shared).
//
// This module is PURE: it touches no `history`, `document`, `fetch`, or `clipboard`
// (those all live in app.js / header.js). It maps a FilterState ⇆ a NICE, default-
// omitting query string, so a default view is the bare `/`. Everything a caller needs
// from the outside world (the receiver's `today`, the age value⇆token vocabulary) is
// passed in via `ctx`, so this file stays unit-testable and uncoupled from the UI.
//
// Fixed param order for deterministic URLs: view, date, who, age, lap, elig, pool.
//   /?view=pool&date=2026-08-03&who=female&pool=hallenbad-oerlikon
//
// ctx = { today: 'YYYY-MM-DD', ageTokens: [{ value: <number>, token: <string> }] }.

// --- tiny pure UTC date helpers (inlined so this module imports nothing) ---
function parseUtc(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
function isoDate(date) {
  return date.toISOString().slice(0, 10);
}
function shiftIso(iso, days) {
  const d = parseUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}
/** The ISO Monday (Mon=0) of a date's week. */
function mondayOf(iso) {
  const d = parseUtc(iso);
  const dow = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dow);
  return isoDate(d);
}
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;
/** A well-formed, real calendar date in ISO form (rejects 2026-02-31 &c). */
function isRealIso(iso) {
  return ISO_RE.test(iso) && isoDate(parseUtc(iso)) === iso;
}

// The date actually written for a state: in Pool mode it is normalized to that week's
// Monday; omitted entirely when it equals the receiver's today (→ bare `/` default).
function writtenDate(state, today) {
  if (!state.date) return null;
  const date = state.mode === 'pool' ? mondayOf(state.date) : state.date;
  if (today && date === today) return null;
  return date;
}

/**
 * toParams(state, ctx) → URLSearchParams with only the NON-DEFAULT params, in the
 * fixed order (view, date, who, age, lap, elig, pool). A pure projection of `state`.
 */
export function toParams(state, ctx = {}) {
  const { today, ageTokens = [] } = ctx;
  const p = new URLSearchParams();

  if (state.mode === 'pool') p.set('view', 'pool'); // 'day' is the omitted default

  const dateVal = writtenDate(state, today);
  if (dateVal) p.set('date', dateVal);

  if (state.gender) p.set('who', state.gender); // '' (Any) omitted

  if (state.age != null && state.age !== '') {
    const tok = ageTokens.find((a) => a.value === state.age);
    p.set('age', tok ? tok.token : String(state.age)); // token, numeric fallback
  }

  if (state.lapOnly) p.set('lap', '1');
  if (state.eligibleOnly) p.set('elig', '1');

  if (state.selectedPool && state.selectedPool.id) p.set('pool', state.selectedPool.id);

  return p;
}

/** toSearch(state, ctx) → '' (default view) | '?view=…' (a stable, ordered string). */
export function toSearch(state, ctx = {}) {
  const s = toParams(state, ctx).toString();
  return s ? `?${s}` : '';
}

/**
 * fromParams(params, ctx) → a partial FilterState patch. TOTAL & tolerant: each param
 * is decoded independently, validated, and DROPPED if invalid/unknown — it never
 * throws. `pool` comes back as `{ id: <slug>, name: null }` (the label is backfilled
 * later from /pools). `date` must be a real ISO date within today..+60d. `view` only
 * recognizes `pool`. Unknown `who`/`age` tokens are dropped.
 */
export function fromParams(params, ctx = {}) {
  const { today, ageTokens = [] } = ctx;
  const patch = {};

  if (params.get('view') === 'pool') patch.mode = 'pool';

  const date = params.get('date');
  if (date && isRealIso(date) && today && date >= today && date <= shiftIso(today, 60)) {
    patch.date = date;
  }

  const who = params.get('who');
  if (who === 'female' || who === 'male' || who === 'diverse') patch.gender = who;

  const age = params.get('age');
  if (age != null) {
    const tok = ageTokens.find((a) => a.token === age);
    if (tok) patch.age = tok.value;
    else {
      const n = Number(age);
      if (Number.isInteger(n) && n >= 0 && n <= 120) patch.age = n; // numeric fallback
    }
  }

  if (params.get('lap') === '1') patch.lapOnly = true;
  if (params.get('elig') === '1') patch.eligibleOnly = true;

  const pool = params.get('pool');
  if (pool) patch.selectedPool = { id: pool, name: null };

  return patch;
}

/** fromSearch(search, ctx) → patch. Accepts '', '?…', or a raw query string. */
export function fromSearch(search, ctx = {}) {
  return fromParams(new URLSearchParams(search || ''), ctx);
}
