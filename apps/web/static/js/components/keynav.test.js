import test from 'node:test';
import assert from 'node:assert/strict';

import { rovingIndex, listboxIndex, filterOptions } from './keynav.js';

test('rovingIndex moves and wraps in both directions', () => {
  assert.equal(rovingIndex(0, 3, 'ArrowRight'), 1);
  assert.equal(rovingIndex(2, 3, 'ArrowRight'), 0); // wrap forward
  assert.equal(rovingIndex(0, 3, 'ArrowLeft'), 2); // wrap back
  assert.equal(rovingIndex(1, 3, 'ArrowUp'), 0);
  assert.equal(rovingIndex(1, 3, 'ArrowDown'), 2);
  assert.equal(rovingIndex(2, 3, 'Home'), 0);
  assert.equal(rovingIndex(0, 3, 'End'), 2);
});

test('rovingIndex returns null for non-navigation keys and empty groups', () => {
  assert.equal(rovingIndex(0, 3, 'Enter'), null);
  assert.equal(rovingIndex(0, 3, 'a'), null);
  assert.equal(rovingIndex(0, 0, 'ArrowRight'), null);
});

test('rovingIndex without wrap clamps at the edges', () => {
  assert.equal(rovingIndex(2, 3, 'ArrowRight', { wrap: false }), 2);
  assert.equal(rovingIndex(0, 3, 'ArrowLeft', { wrap: false }), 0);
});

test('listboxIndex opens from -1, wraps, and jumps', () => {
  assert.equal(listboxIndex(-1, 3, 'ArrowDown'), 0);
  assert.equal(listboxIndex(2, 3, 'ArrowDown'), 0); // wrap
  assert.equal(listboxIndex(-1, 3, 'ArrowUp'), 2); // from closed, up → last
  assert.equal(listboxIndex(0, 3, 'ArrowUp'), 2); // wrap
  assert.equal(listboxIndex(1, 3, 'Home'), 0);
  assert.equal(listboxIndex(1, 3, 'End'), 2);
  assert.equal(listboxIndex(0, 3, 'Enter'), null);
  assert.equal(listboxIndex(0, 0, 'ArrowDown'), -1);
});

test('filterOptions does case-insensitive substring on label by default', () => {
  const opts = [
    { value: 'a', label: 'Hallenbad Oerlikon' },
    { value: 'b', label: 'Hallenbad City' },
  ];
  assert.deepEqual(filterOptions(opts, 'oer'), [opts[0]]);
  assert.deepEqual(filterOptions(opts, '  CITY '), [opts[1]]);
  assert.deepEqual(filterOptions(opts, ''), opts); // copy of all
  assert.notEqual(filterOptions(opts, ''), opts); // a copy, not the original
});

test('filterOptions honours a custom filterFn', () => {
  const opts = [{ value: 'a', label: 'A', tag: 'x' }, { value: 'b', label: 'B', tag: 'y' }];
  assert.deepEqual(filterOptions(opts, 'x', (o, q) => o.tag === q), [opts[0]]);
});
