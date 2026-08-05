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

test('girls-only: male/diverse=no, female=chk (no published cutoff), unset=chk — never ✓', () => {
  // Mirrors `_girls_only` (access.py). A woman is NOT welcomed: the city publishes no age
  // cutoff for "Mädchen", so she gets ? rather than ✓.
  assert.equal(eligForAccess('GirlsOnly', 'male', 40), 'no');
  assert.equal(eligForAccess('GirlsOnly', 'diverse', 40), 'no');
  assert.equal(eligForAccess('GirlsOnly', 'female', 12), 'chk');
  assert.equal(eligForAccess('GirlsOnly', '', null), 'chk');
});

test('gender-diverse: only the published age denies; above it ? — NEVER ✓, never a gender deny', () => {
  assert.equal(eligForAccess('GenderDiverse', '', 15), 'no'); // below "ab 16 Jahren"
  assert.equal(eligForAccess('GenderDiverse', 'male', 40), 'chk');
  assert.equal(eligForAccess('GenderDiverse', 'female', 40), 'chk'); // a trans woman is female
  assert.equal(eligForAccess('GenderDiverse', 'diverse', null), 'chk');
});

test('accompanied-children is always ? — accompaniment is not a filter attribute', () => {
  for (const g of ['', 'female', 'male', 'diverse']) {
    for (const a of [null, 8, 40]) {
      assert.equal(eligForAccess('AccompaniedChildren', g, a), 'chk');
    }
  }
});

test('an UNKNOWN access type is ? , never ✓ — the fallback may not invent permission', () => {
  // The regression this suite exists for: the fallback used to return 'in', so the first
  // new domain access kind (GirlsOnly) rendered ✓ on a session the server had refused.
  assert.equal(eligForAccess('SomeFutureAccessKind', 'male', 40), 'chk');
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
  for (const a of [
    'WomenOnly',
    'SeniorsOnly',
    'AdultsOnly',
    'SchoolReserved',
    'ClubReserved',
    'GirlsOnly',
    'GenderDiverse',
    'AccompaniedChildren',
  ]) {
    assert.ok(seen.has(a), `fixture missing access ${a}`);
  }
});

test('this module agrees with the SERVER on every access type × gender × age', () => {
  // The generated contract: every row is what `swimzh.domain.access.eligibility` actually
  // decided, mapped to the UI's three marks by ONE documented rule (see
  // apps/web/tests/test_eligibility_ui_contract.py). Two implementations of one rule drift;
  // this is what stops them.
  const { cases } = load('eligibility_contract.json');
  assert.ok(cases.length > 0);
  for (const c of cases) {
    const got = eligForAccess(c.access, c.gender, c.age);
    assert.equal(got, c.ui, `${c.access} gender=${c.gender || 'unset'} age=${c.age}: ` +
      `server said ${c.code} (allowed=${c.allowed}) → ${c.ui}, UI drew ${got}`);
  }
  // The contract must actually exercise the kinds this plan added.
  for (const a of ['GirlsOnly', 'GenderDiverse', 'AccompaniedChildren']) {
    assert.ok(cases.some((c) => c.access === a), `contract missing access ${a}`);
  }
});

test('the aemtler Thursday girls-only session never reads ✓ for an adult man', () => {
  // The named harm, replayed from a REAL /swim round-trip (generated fixture).
  const { viewer, option } = load('aemtler_girls_only.json');
  assert.equal(option.access, 'GirlsOnly');
  assert.equal(option.eligible, false); // what the server told poolrank
  const state = eligForAccess(option.access, viewer.gender, viewer.age);
  assert.notEqual(state, 'in'); // the badge may NEVER contradict the server's refusal
  assert.equal(state, 'no');
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
