import test from 'node:test';
import assert from 'node:assert/strict';

import { toParams, toSearch, fromParams, fromSearch } from './urlstate.js';
import { createFilterState, merge } from './filterstate.js';

// The receiver context: a fixed today + the age value⇆token vocabulary (mirrors the
// toolbar's DEFAULT_AGE_CHIPS: Child 8 / Teen 16 / Adult 34 / Senior 70).
const TODAY = '2026-07-24';
const CTX = {
  today: TODAY,
  ageTokens: [
    { value: 8, token: 'child' },
    { value: 16, token: 'teen' },
    { value: 34, token: 'adult' },
    { value: 70, token: 'senior' },
  ],
};

// A round-trip helper: encode a state, decode the string, merge the patch back over a
// fresh Day/today seed (what app.js does on load), and return the reconstructed state.
function roundTrip(state) {
  const seed = createFilterState({ mode: 'day', date: TODAY });
  return merge(seed, fromSearch(toSearch(state, CTX), CTX));
}

test('the default view projects to EMPTY params (bare /)', () => {
  const def = createFilterState({ mode: 'day', date: TODAY });
  assert.equal(toParams(def, CTX).toString(), '');
  assert.equal(toSearch(def, CTX), '');
});

test('a fully-loaded pool state round-trips (pool + filters)', () => {
  const s = createFilterState({
    mode: 'pool',
    date: '2026-08-03', // a Monday
    gender: 'female',
    age: 34,
    lapOnly: true,
    eligibleOnly: true,
    selectedPool: { id: 'hallenbad-oerlikon', name: 'Hallenbad Oerlikon' },
  });
  // Fixed order: view, date, who, age, lap, elig, pool.
  assert.equal(
    toSearch(s, CTX),
    '?view=pool&date=2026-08-03&who=female&age=adult&lap=1&elig=1&pool=hallenbad-oerlikon',
  );
  const back = roundTrip(s);
  assert.equal(back.mode, 'pool');
  assert.equal(back.date, '2026-08-03');
  assert.equal(back.gender, 'female');
  assert.equal(back.age, 34);
  assert.equal(back.lapOnly, true);
  assert.equal(back.eligibleOnly, true);
  // pool comes back as {id, name:null} — the label is backfilled later from /pools.
  assert.deepEqual(back.selectedPool, { id: 'hallenbad-oerlikon', name: null });
});

test('Pool mode normalizes date to that week Monday before writing', () => {
  const wed = createFilterState({
    mode: 'pool',
    date: '2026-08-05', // a Wednesday
    selectedPool: { id: 'city', name: 'Hallenbad City' },
  });
  assert.equal(toParams(wed, CTX).get('date'), '2026-08-03'); // → the Monday
  assert.equal(roundTrip(wed).date, '2026-08-03');
});

test('a Day-mode date equal to today is OMITTED, a future date is written', () => {
  const todayState = createFilterState({ mode: 'day', date: TODAY });
  assert.equal(toParams(todayState, CTX).has('date'), false);

  const future = createFilterState({ mode: 'day', date: '2026-08-01' });
  assert.equal(toParams(future, CTX).get('date'), '2026-08-01');
  assert.equal(roundTrip(future).date, '2026-08-01');
});

test('age uses a token, with a numeric fallback for off-chip ages', () => {
  const senior = createFilterState({ age: 70 });
  assert.equal(toParams(senior, CTX).get('age'), 'senior');

  const odd = createFilterState({ age: 50 }); // no chip → numeric fallback
  assert.equal(toParams(odd, CTX).get('age'), '50');
  assert.equal(roundTrip(odd).age, 50);
});

test('fromParams is TOTAL & tolerant — garbage/unknown params are dropped, never throws', () => {
  const patch = fromParams(
    new URLSearchParams(
      'view=weird&date=not-a-date&who=alien&age=nope&lap=yes&elig=0&pool=&junk=1',
    ),
    CTX,
  );
  assert.deepEqual(patch, {}); // every param invalid → empty patch
});

test('fromParams drops an out-of-range date (before today / beyond +60d) and an impossible date', () => {
  assert.equal(fromParams(new URLSearchParams('date=2026-07-23'), CTX).date, undefined); // yesterday
  assert.equal(fromParams(new URLSearchParams('date=2026-12-01'), CTX).date, undefined); // > +60d
  assert.equal(fromParams(new URLSearchParams('date=2026-02-31'), CTX).date, undefined); // impossible
  assert.equal(fromParams(new URLSearchParams('date=2026-08-10'), CTX).date, '2026-08-10'); // in range
});

test('view only recognizes `pool`; a bare pool param yields {id, name:null}', () => {
  assert.equal(fromParams(new URLSearchParams('view=pool'), CTX).mode, 'pool');
  assert.equal(fromParams(new URLSearchParams('view=day'), CTX).mode, undefined);
  assert.deepEqual(fromParams(new URLSearchParams('pool=seebad-enge'), CTX).selectedPool, {
    id: 'seebad-enge',
    name: null,
  });
});

test('age accepts a known token OR a numeric string, dropping unknown tokens', () => {
  assert.equal(fromParams(new URLSearchParams('age=teen'), CTX).age, 16);
  assert.equal(fromParams(new URLSearchParams('age=42'), CTX).age, 42);
  assert.equal(fromParams(new URLSearchParams('age=grandparent'), CTX).age, undefined);
});

test('lap/elig only turn on for the literal `1`', () => {
  assert.equal(fromParams(new URLSearchParams('lap=1&elig=1'), CTX).lapOnly, true);
  assert.equal(fromParams(new URLSearchParams('lap=1&elig=1'), CTX).eligibleOnly, true);
  assert.equal(fromParams(new URLSearchParams('lap=true'), CTX).lapOnly, undefined);
  assert.equal(fromParams(new URLSearchParams('elig=0'), CTX).eligibleOnly, undefined);
});

test('fromSearch accepts a leading `?` and an empty string', () => {
  assert.deepEqual(fromSearch('', CTX), {});
  assert.equal(fromSearch('?who=male', CTX).gender, 'male');
});
