import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_FILTER,
  createFilterState,
  merge,
  serialize,
  deserialize,
} from './filterstate.js';

test('merge applies a patch, deep-merges place, and mutates neither argument', () => {
  const s = createFilterState({
    gender: 'female',
    place: { lat: 47.3779, lon: 8.5403, label: 'Zürich HB' },
  });
  const s2 = merge(s, { age: 34, mode: 'pool', place: { label: 'Bellevue' } });

  // Patch applied.
  assert.equal(s2.age, 34);
  assert.equal(s2.mode, 'pool');
  // place is deep-merged: label changes, lat/lon survive.
  assert.equal(s2.place.label, 'Bellevue');
  assert.equal(s2.place.lat, 47.3779);
  assert.equal(s2.place.lon, 8.5403);
  // Original untouched (immutability).
  assert.equal(s.age, null);
  assert.equal(s.mode, 'day');
  assert.equal(s.place.label, 'Zürich HB');
});

test('serialize/deserialize round-trips a full state', () => {
  const s = createFilterState({
    gender: 'male',
    age: 40,
    mode: 'pool',
    date: '2026-07-23',
    week: '2026-07-20',
    selectedPool: { id: 'oer', name: 'Hallenbad Oerlikon' },
    lapOnly: true,
    eligibleOnly: true,
    place: { lat: 47.1, lon: 8.4, label: 'Zürichhorn' },
  });
  assert.deepEqual(deserialize(serialize(s)), s);
});

// selectedPool is the ONE shared "currently selected pool" (Day + Pool views). It is
// a declared top-level key (default null), overwritten WHOLESALE by merge (NOT
// shallow-merged like `place`), so a patch can both set a new pool and clear it.
test('selectedPool defaults to null and merge overwrites it wholesale (set + clear)', () => {
  assert.equal(DEFAULT_FILTER.selectedPool, null);
  assert.equal(createFilterState().selectedPool, null);

  const chosen = merge(createFilterState(), {
    selectedPool: { id: 'oer', name: 'Hallenbad Oerlikon' },
  });
  assert.deepEqual(chosen.selectedPool, { id: 'oer', name: 'Hallenbad Oerlikon' });

  // A new pick replaces the whole object (no field bleed-through from the old pool).
  const repicked = merge(chosen, { selectedPool: { id: 'city', name: 'Hallenbad City' } });
  assert.deepEqual(repicked.selectedPool, { id: 'city', name: 'Hallenbad City' });

  // null clears it (no explicit choice) — proving it is not shallow-merged.
  const cleared = merge(chosen, { selectedPool: null });
  assert.equal(cleared.selectedPool, null);
});

test('createFilterState fills gaps from DEFAULT_FILTER', () => {
  const s = createFilterState();
  assert.deepEqual(s, {
    place: { lat: null, lon: null, label: '' },
    date: null,
    week: null,
    gender: '',
    age: null,
    mode: 'day',
    selectedPool: null,
    lapOnly: false,
    eligibleOnly: false,
  });
  // DEFAULT_FILTER stays frozen and is not returned directly.
  assert.notEqual(s, DEFAULT_FILTER);
});
