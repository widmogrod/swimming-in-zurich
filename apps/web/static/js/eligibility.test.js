import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { eligForAccess, dayEligibility } from './eligibility.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

test('open-to-all access is always ✓, whatever the person', () => {
  for (const a of ['PublicSwim', 'LaneSwim', 'FamilyTime']) {
    assert.equal(eligForAccess(a, '', null), 'in');
    assert.equal(eligForAccess(a, 'male', 8), 'in');
  }
});

test('women-only → female=in, male=no, unset=chk, diverse=chk', () => {
  assert.equal(eligForAccess('WomenOnly', 'female', null), 'in');
  assert.equal(eligForAccess('WomenOnly', 'male', null), 'no');
  assert.equal(eligForAccess('WomenOnly', '', null), 'chk');
  assert.equal(eligForAccess('WomenOnly', 'diverse', null), 'chk');
});

test('women-only: ? (unset) is NEVER the same mark as ✕ (male)', () => {
  assert.notEqual(eligForAccess('WomenOnly', '', null), eligForAccess('WomenOnly', 'male', null));
});

test('seniors-only ≥60: in at/above, no below, chk when age unknown', () => {
  assert.equal(eligForAccess('SeniorsOnly', '', 60), 'in');
  assert.equal(eligForAccess('SeniorsOnly', '', 75), 'in');
  assert.equal(eligForAccess('SeniorsOnly', '', 59), 'no');
  assert.equal(eligForAccess('SeniorsOnly', '', null), 'chk');
});

test('adults-only ≥18: <18 is no, ≥18 is in, unknown is chk', () => {
  assert.equal(eligForAccess('AdultsOnly', '', 17), 'no');
  assert.equal(eligForAccess('AdultsOnly', '', 18), 'in');
  assert.equal(eligForAccess('AdultsOnly', '', null), 'chk');
});

test('never-public access (school/club) is always ✕', () => {
  assert.equal(eligForAccess('SchoolReserved', 'female', 40), 'no');
  assert.equal(eligForAccess('ClubReserved', 'male', 40), 'no');
});

test('every access family in the synthetic fixture maps to a valid state', () => {
  const { options } = load('access_families.json');
  const seen = new Set();
  for (const o of options) {
    const s = eligForAccess(o.access, '', null);
    assert.ok(['in', 'chk', 'no'].includes(s), `${o.access} → ${s}`);
    seen.add(o.access);
  }
  // the fixture exercises the branches the captured day/week fixtures lack
  for (const a of ['WomenOnly', 'SeniorsOnly', 'AdultsOnly', 'SchoolReserved', 'ClubReserved']) {
    assert.ok(seen.has(a), `fixture missing access ${a}`);
  }
});

test('dayEligibility priority is in > chk > no, and ? never collapses to ✕', () => {
  assert.equal(dayEligibility(['no', 'chk', 'in']), 'in');
  assert.equal(dayEligibility(['no', 'chk']), 'chk'); // a check-only day is ?, NOT ✕
  assert.equal(dayEligibility(['no', 'no']), 'no');
  assert.equal(dayEligibility([]), 'no');
});

test('a WomenOnly-only day reads ✓ for a woman and ? (not ✕) for an unset viewer', () => {
  const { options } = load('access_families.json');
  const women = options.filter((o) => o.access === 'WomenOnly');
  assert.equal(dayEligibility(women.map((o) => eligForAccess(o.access, 'female', null))), 'in');
  assert.equal(dayEligibility(women.map((o) => eligForAccess(o.access, '', null))), 'chk');
});
