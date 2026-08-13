// datestepper_tz.test.js — the DateStepper's date math must be TIMEZONE-INDEPENDENT
// (it renders absolute calendar days, not moments). This file pins a NEGATIVE-offset
// zone (America/Los_Angeles) BEFORE any Date is constructed, so a regression from the
// UTC accessors (Date.UTC / getUTC*) to LOCAL ones (getDate / getMonth / getDay) would
// shift the day by one under this zone and FAIL here — the exact local-Date bug the
// UTC parsing guards against. Kept in its own file so the zone is scoped to this
// process (node --test isolates each file), never bleeding into sibling suites.

import { afterAll, expect, test } from 'vitest';

const ORIG_TZ = process.env.TZ;
process.env.TZ = 'America/Los_Angeles';

// Imported AFTER the zone is pinned (module-eval order is irrelevant here since the
// functions read the zone per-call, but this documents the intent).
const { formatLabel, shiftDate } = await import('./datestepper.js');

afterAll(() => {
  if (ORIG_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIG_TZ;
});

test('the pinned zone is actually in effect (guards against a vacuous test)', () => {
  // Under LA, UTC-midnight of the 23rd reads as the 22nd in LOCAL time — so if the
  // stepper ever used local Date accessors, its day would be wrong here.
  expect(new Date('2026-07-23T00:00:00Z').getDate()).toBe(22); // TZ not applied → vacuous
});

test('formatLabel yields the absolute day unshifted under a negative-offset zone', () => {
  expect(formatLabel('2026-07-23')).toBe('Thu 23 Jul');
  expect(formatLabel('2026-01-01')).toBe('Thu 1 Jan');
});

test('shiftDate crosses day/month boundaries unshifted under a negative-offset zone', () => {
  expect(shiftDate('2026-07-23', 1)).toBe('2026-07-24');
  expect(shiftDate('2026-07-31', 1)).toBe('2026-08-01');
  expect(shiftDate('2026-08-01', -1)).toBe('2026-07-31');
});
