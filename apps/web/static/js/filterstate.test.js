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
    lapOnly: true,
    eligibleOnly: true,
    place: { lat: 47.1, lon: 8.4, label: 'Zürichhorn' },
  });
  assert.deepEqual(deserialize(serialize(s)), s);
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
    lapOnly: false,
    eligibleOnly: false,
  });
  // DEFAULT_FILTER stays frozen and is not returned directly.
  assert.notEqual(s, DEFAULT_FILTER);
});
