import { expect, test } from 'vitest';

import { legendModel, createBoardLegend, HONESTY_NOTE } from './legend.js';
import { ACCESS_FAMILY } from './ribbonmodel.js';
import { mount } from '../components/_fakedom.js';
import { must } from '../testutil.js';
import type { FakeElement } from '../components/_fakedom.js';

test('legendModel lists every family, the 3 terminal states, and the elig key', () => {
  const m = legendModel();
  // Every access family the ribbon can paint must be DECODABLE here: a band with no legend
  // row is an unexplained colour on the board.
  expect(new Set(m.families.map((f) => f.family))).toEqual(new Set(Object.values(ACCESS_FAMILY)));
  expect(m.families.length).toBe(11);
  expect(m.families.map((f) => f.family)).toEqual(['public', 'lane', 'family', 'women', 'seniors', 'adults', 'school', 'club', 'girls', 'diverse', 'accompanied']);
  // The three terminal states are present and DISTINCT (open / closed / unknown).
  expect(m.states.map((s) => s.key)).toEqual(['open', 'closed', 'unknown']);
  expect(new Set(m.states.map((s) => s.key)).size).toBe(3);
  // The eligibility key carries ✓/?/✕ as in/chk/no — ? distinct from ✕.
  expect(m.eligibility.map((e) => e.state)).toEqual(['in', 'chk', 'no']);
  expect(m.note).toBe(HONESTY_NOTE);
});

test('AC5 · the legend decodes the LANE STACK, including the pools that have no plan', () => {
  // The board grew an encoding (one sub-row per lane) the original three groups cannot
  // explain. The fourth entry is invariant I5 in words: "not published" is its own state,
  // never "no lanes free".
  const m = legendModel();
  expect(m.laneStack.map((l) => l.key)).toEqual(['public', 'reserved', 'best', 'unpublished']);
  expect(m.laneStack.every((l) => l.label.trim().length > 0)).toBe(true);
  expect(new Set(m.laneStack.map((l) => l.label)).size).toBe(4);
  // The stack's rows are their OWN swatches — reusing a `.fam-*` access hue would say the
  // sub-rows are coloured by session type, which they are not.
  const el = mount();
  createBoardLegend(el);
  const laneSwatches = el.queryAll(
    (c: FakeElement) =>
      c.classList.contains('legend__swatch') && c.className.includes('legend__lane--'),
  );
  expect(laneSwatches.length).toBe(4);
  for (const key of ['public', 'reserved', 'best', 'unpublished']) {
    expect(
      must(el.query((c: FakeElement) => c.classList.contains(`legend__lane--${key}`))),
    ).toBeTruthy();
  }
  // The access-family swatches are untouched — the new group is additive.
  expect(
    el.queryAll((c: FakeElement) => c.classList.contains('legend__swatch') && c.className.includes('fam-'))
      .length,
  ).toBe(11);
});

test('the honesty note names the real meaning of ribbon thickness and disclaims busyness', () => {
  expect(HONESTY_NOTE.includes('public-lane split')).toBeTruthy();
  expect(HONESTY_NOTE.toLowerCase().includes('busyness')).toBeTruthy();
  expect(HONESTY_NOTE.toLowerCase().includes('no source')).toBeTruthy();
});

test('createBoardLegend renders swatches, the three states, the elig badges, and the note', () => {
  const el = mount();
  createBoardLegend(el);
  expect(el.getAttribute('role')).toBe('region');
  // 11 access-family swatches (each a .fam-* class carrying the token colour).
  const famSwatches = el.queryAll(
    (c) => c.classList.contains('legend__swatch') && c.className.includes('fam-'),
  );
  expect(famSwatches.length).toBe(11);
  // The three terminal states, each its own modifier class.
  for (const key of ['open', 'closed', 'unknown']) {
    expect(must(el.query((c: FakeElement) => c.classList.contains(`legend__state--${key}`)))).toBeTruthy();
  }
  // The eligibility key reuses the EligibilityBadge primitive (3 badges).
  const badges = el.queryAll((c: FakeElement) => c.classList.contains('ui-eligbadge'));
  expect(badges.length).toBe(3);
  // The honesty note is rendered verbatim.
  const note = must(el.query((c: FakeElement) => c.classList.contains('legend__note')));
  expect(note.textContent).toBe(HONESTY_NOTE);
});
