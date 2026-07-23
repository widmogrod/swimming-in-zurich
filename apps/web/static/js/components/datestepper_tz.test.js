// datestepper_tz.test.js — the DateStepper's date math must be TIMEZONE-INDEPENDENT
// (it renders absolute calendar days, not moments). This file pins a NEGATIVE-offset
// zone (America/Los_Angeles) BEFORE any Date is constructed, so a regression from the
// UTC accessors (Date.UTC / getUTC*) to LOCAL ones (getDate / getMonth / getDay) would
// shift the day by one under this zone and FAIL here — the exact local-Date bug the
// UTC parsing guards against. Kept in its own file so the zone is scoped to this
// process (node --test isolates each file), never bleeding into sibling suites.

import test, { after } from 'node:test';
import assert from 'node:assert/strict';

const ORIG_TZ = process.env.TZ;
process.env.TZ = 'America/Los_Angeles';

// Imported AFTER the zone is pinned (module-eval order is irrelevant here since the
// functions read the zone per-call, but this documents the intent).
const { formatLabel, shiftDate } = await import('./datestepper.js');

after(() => {
  if (ORIG_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIG_TZ;
});

test('the pinned zone is actually in effect (guards against a vacuous test)', () => {
  // Under LA, UTC-midnight of the 23rd reads as the 22nd in LOCAL time — so if the
  // stepper ever used local Date accessors, its day would be wrong here.
  assert.equal(new Date('2026-07-23T00:00:00Z').getDate(), 22, 'TZ=America/Los_Angeles not applied');
});

test('formatLabel yields the absolute day unshifted under a negative-offset zone', () => {
  assert.equal(formatLabel('2026-07-23'), 'Thu 23 Jul');
  assert.equal(formatLabel('2026-01-01'), 'Thu 1 Jan');
});

test('shiftDate crosses day/month boundaries unshifted under a negative-offset zone', () => {
  assert.equal(shiftDate('2026-07-23', 1), '2026-07-24');
  assert.equal(shiftDate('2026-07-31', 1), '2026-08-01');
  assert.equal(shiftDate('2026-08-01', -1), '2026-07-31');
});
