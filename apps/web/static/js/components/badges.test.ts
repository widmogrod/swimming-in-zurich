import { expect, test } from 'vitest';

import { mount } from './_fakedom.js';
import { createStatePill } from './statepill.js';
import { createEligibilityBadge } from './eligibilitybadge.js';
import { createLengthLanesBadge } from './lengthlanesbadge.js';
import { createProvenanceStamp } from './provenancestamp.js';
import { iconSvg, ICON_NAMES } from './iconset.js';
import { must } from '../testutil.js';

test('StatePill renders a dot AND a word for each of the four states', () => {
  for (const [state, cls, word] of [
    ['open', 'is-open', 'Open'],
    ['opens-later', 'is-later', 'Opens later'],
    ['closed', 'is-closed', 'Closed'],
    ['unknown', 'is-unknown', 'Hours not listed'],
  ]) {
    const el = mount();
    createStatePill(el, { props: { state } });
    expect(el.getAttribute('role')).toBe('status');
    expect(el.classList.contains(cls)).toBeTruthy();
    expect(must(el.query((c) => c.classList.contains('ui-statepill__dot')))).toBeTruthy();
    expect(must(el.query((c) => c.classList.contains('ui-statepill__word'))).textContent).toBe(word);
  }
});

test('EligibilityBadge uses distinct marks for ? and ✕ and carries the reason', () => {
  const el = mount();
  createEligibilityBadge(el, { props: { state: 'chk', reason: 'Confirm on site' } });
  expect(el.getAttribute('role')).toBe('img');
  expect(el.getAttribute('title')).toBe('Confirm on site');
  expect(el.classList.contains('is-chk')).toBeTruthy();
  expect(must(el.query((c) => c.classList.contains('ui-eligbadge__mark'))).textContent).toBe('?');

  const no = mount();
  createEligibilityBadge(no, { props: { state: 'no', reason: 'Women only' } });
  expect(no.classList.contains('is-no')).toBeTruthy();
  expect(must(no.query((c) => c.classList.contains('ui-eligbadge__mark'))).textContent).toBe('✕');
  // ? and ✕ are never the same mark/class.
  expect('?').not.toBe('✕');
});

test('EligibilityBadge tag variant adds the board-tag class', () => {
  const el = mount();
  createEligibilityBadge(el, { props: { state: 'in', variant: 'tag' } });
  expect(el.classList.contains('ui-eligbadge--tag')).toBeTruthy();
  expect(el.classList.contains('is-in')).toBeTruthy();
});

test('LengthLanesBadge shows length + lanes, pluralising honestly', () => {
  const el = mount();
  createLengthLanesBadge(el, { props: { length_m: 25, lanes: 6 } });
  expect(must(el.query((c) => c.classList.contains('ui-lenlanes__len'))).textContent).toBe('25 m');
  expect(must(el.query((c) => c.classList.contains('ui-lenlanes__lanes'))).textContent).toBe('6 lanes');
  expect(el.getAttribute('aria-label')).toBe('25 metre pool, 6 lanes');

  const one = mount();
  createLengthLanesBadge(one, { props: { length_m: 50, lanes: 1 } });
  expect(must(one.query((c) => c.classList.contains('ui-lenlanes__lanes'))).textContent).toBe('1 lane');
});

test('LengthLanesBadge omits lanes when unknown and degrades without a length', () => {
  const noLanes = mount();
  createLengthLanesBadge(noLanes, { props: { length_m: 25 } });
  expect(noLanes.query((c) => c.classList.contains('ui-lenlanes__lanes'))).toBe(null);

  const degraded = mount();
  createLengthLanesBadge(degraded, { props: { length_m: null } });
  expect(degraded.classList.contains('is-degraded')).toBeTruthy();
  expect(must(degraded.query((c) => c.classList.contains('ui-lenlanes__degrade'))).textContent).toBe('Teaching pool');
});

test('ProvenanceStamp distinguishes curated from illustrative', () => {
  const curated = mount();
  createProvenanceStamp(curated, {
    props: { curated: true, source: 'stadt-zuerich.ch', valid_as_of: '2026-07-18' },
  });
  expect(curated.getAttribute('role')).toBe('note');
  expect(curated.classList.contains('is-curated')).toBeTruthy();
  const text = must(curated.query((c) => c.classList.contains('ui-provstamp__text'))).textContent;
  expect(text).toMatch(/Official schedule/);
  // The date is now RENDERED for the viewer's locale (en → en-GB) rather than shown as
  // a raw ISO string — that is the point of routing it through Intl.
  expect(text).toMatch(/last checked 18 Jul 2026/);

  const illus = mount();
  createProvenanceStamp(illus, { props: { curated: false } });
  expect(illus.classList.contains('is-illustrative')).toBeTruthy();
  expect(must(illus.query((c) => c.classList.contains('ui-provstamp__text'))).textContent).toMatch(/Illustrative/);
});

test('IconSet glyphs are decorative currentColor SVG (no hex) by default', () => {
  for (const name of ICON_NAMES) {
    const svg = iconSvg(name);
    expect(svg).toMatch(/<svg/);
    expect(svg).toMatch(/stroke="currentColor"/);
    expect(svg).toMatch(/aria-hidden="true"/);
    expect(svg).not.toMatch(/#[0-9a-fA-F]{3,8}/); // no raw hex in the glyph markup
  }
  // A titled glyph is promoted to role=img with a label.
  expect(iconSvg('lock', { title: 'Reserved' })).toMatch(/role="img" aria-label="Reserved"/);
});
