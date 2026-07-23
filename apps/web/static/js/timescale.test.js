import test from 'node:test';
import assert from 'node:assert/strict';

import { makeTimescale } from './timescale.js';

test('endpoints map exactly to 0 and PLOT', () => {
  const ts = makeTimescale(6, 22, 960);
  assert.equal(ts.X(6 * 60), 0); // DAY0·60 → left edge
  assert.equal(ts.X(22 * 60), 960); // DAY1·60 → right edge (== PLOT)
});

test('X(min) is strictly monotonic increasing across the day', () => {
  const ts = makeTimescale(6, 22, 960);
  let prev = -Infinity;
  for (let m = ts.lo; m <= ts.hi; m += 5) {
    const x = ts.X(m);
    assert.ok(x > prev, `X(${m}) = ${x} is not > previous ${prev}`);
    prev = x;
  }
});

test('inverse round-trips X within floating-point tolerance', () => {
  const ts = makeTimescale(6, 22, 960);
  for (const m of [360, 512, 700, 933, 1320]) {
    assert.ok(Math.abs(ts.inverse(ts.X(m)) - m) < 1e-9);
  }
});

test('rejects a non-positive span or plot width', () => {
  assert.throws(() => makeTimescale(22, 6, 960), RangeError);
  assert.throws(() => makeTimescale(6, 6, 960), RangeError);
  assert.throws(() => makeTimescale(6, 22, 0), RangeError);
});
