import test from 'node:test';
import assert from 'node:assert/strict';

import { legendModel, createBoardLegend, HONESTY_NOTE } from './legend.js';
import { mount } from '../components/_fakedom.js';

test('legendModel lists the 8 families, the 3 terminal states, and the elig key', () => {
  const m = legendModel();
  assert.equal(m.families.length, 8);
  assert.deepEqual(
    m.families.map((f) => f.family),
    ['public', 'lane', 'family', 'women', 'seniors', 'adults', 'school', 'club'],
  );
  // The three terminal states are present and DISTINCT (open / closed / unknown).
  assert.deepEqual(
    m.states.map((s) => s.key),
    ['open', 'closed', 'unknown'],
  );
  assert.equal(new Set(m.states.map((s) => s.key)).size, 3);
  // The eligibility key carries ✓/?/✕ as in/chk/no — ? distinct from ✕.
  assert.deepEqual(
    m.eligibility.map((e) => e.state),
    ['in', 'chk', 'no'],
  );
  assert.equal(m.note, HONESTY_NOTE);
});

test('the honesty note names the real meaning of ribbon thickness and disclaims busyness', () => {
  assert.ok(HONESTY_NOTE.includes('public-lane split'));
  assert.ok(HONESTY_NOTE.toLowerCase().includes('busyness'));
  assert.ok(HONESTY_NOTE.toLowerCase().includes('no source'));
});

test('createBoardLegend renders swatches, the three states, the elig badges, and the note', () => {
  const el = mount();
  createBoardLegend(el);
  assert.equal(el.getAttribute('role'), 'region');
  // 8 access-family swatches (each a .fam-* class carrying the token colour).
  const famSwatches = el.queryAll(
    (c) => c.classList.contains('legend__swatch') && c.classList.value.includes('fam-'),
  );
  assert.equal(famSwatches.length, 8);
  // The three terminal states, each its own modifier class.
  for (const key of ['open', 'closed', 'unknown']) {
    assert.ok(
      el.query((c) => c.classList.contains(`legend__state--${key}`)),
      `missing legend state ${key}`,
    );
  }
  // The eligibility key reuses the EligibilityBadge primitive (3 badges).
  const badges = el.queryAll((c) => c.classList.contains('ui-eligbadge'));
  assert.equal(badges.length, 3);
  // The honesty note is rendered verbatim.
  const note = el.query((c) => c.classList.contains('legend__note'));
  assert.equal(note.textContent, HONESTY_NOTE);
});
