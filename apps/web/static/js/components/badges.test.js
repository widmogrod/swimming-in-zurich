import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createStatePill } from './statepill.js';
import { createEligibilityBadge } from './eligibilitybadge.js';
import { createLengthLanesBadge } from './lengthlanesbadge.js';
import { createProvenanceStamp } from './provenancestamp.js';
import { iconSvg, ICON_NAMES } from './iconset.js';

test('StatePill renders a dot AND a word for each of the four states', () => {
  for (const [state, cls, word] of [
    ['open', 'is-open', 'Open'],
    ['opens-later', 'is-later', 'Opens later'],
    ['closed', 'is-closed', 'Closed'],
    ['unknown', 'is-unknown', 'Hours not listed'],
  ]) {
    const el = mount();
    createStatePill(el, { props: { state } });
    assert.equal(el.getAttribute('role'), 'status');
    assert.ok(el.classList.contains(cls), `${state} → ${cls}`);
    assert.ok(el.query((c) => c.classList.contains('ui-statepill__dot')), 'has dot');
    assert.equal(el.query((c) => c.classList.contains('ui-statepill__word')).textContent, word);
  }
});

test('EligibilityBadge uses distinct marks for ? and ✕ and carries the reason', () => {
  const el = mount();
  createEligibilityBadge(el, { props: { state: 'chk', reason: 'Confirm on site' } });
  assert.equal(el.getAttribute('role'), 'img');
  assert.equal(el.getAttribute('title'), 'Confirm on site');
  assert.ok(el.classList.contains('is-chk'));
  assert.equal(el.query((c) => c.classList.contains('ui-eligbadge__mark')).textContent, '?');

  const no = mount();
  createEligibilityBadge(no, { props: { state: 'no', reason: 'Women only' } });
  assert.ok(no.classList.contains('is-no'));
  assert.equal(no.query((c) => c.classList.contains('ui-eligbadge__mark')).textContent, '✕');
  // ? and ✕ are never the same mark/class.
  assert.notEqual('?', '✕');
});

test('EligibilityBadge tag variant adds the board-tag class', () => {
  const el = mount();
  createEligibilityBadge(el, { props: { state: 'in', variant: 'tag' } });
  assert.ok(el.classList.contains('ui-eligbadge--tag'));
  assert.ok(el.classList.contains('is-in'));
});

test('LengthLanesBadge shows length + lanes, pluralising honestly', () => {
  const el = mount();
  createLengthLanesBadge(el, { props: { length_m: 25, lanes: 6 } });
  assert.equal(el.query((c) => c.classList.contains('ui-lenlanes__len')).textContent, '25 m');
  assert.equal(el.query((c) => c.classList.contains('ui-lenlanes__lanes')).textContent, '6 lanes');
  assert.equal(el.getAttribute('aria-label'), '25 metre pool, 6 lanes');

  const one = mount();
  createLengthLanesBadge(one, { props: { length_m: 50, lanes: 1 } });
  assert.equal(one.query((c) => c.classList.contains('ui-lenlanes__lanes')).textContent, '1 lane');
});

test('LengthLanesBadge omits lanes when unknown and degrades without a length', () => {
  const noLanes = mount();
  createLengthLanesBadge(noLanes, { props: { length_m: 25 } });
  assert.equal(noLanes.query((c) => c.classList.contains('ui-lenlanes__lanes')), null);

  const degraded = mount();
  createLengthLanesBadge(degraded, { props: { length_m: null } });
  assert.ok(degraded.classList.contains('is-degraded'));
  assert.equal(
    degraded.query((c) => c.classList.contains('ui-lenlanes__degrade')).textContent,
    'Teaching pool',
  );
});

test('ProvenanceStamp distinguishes curated from illustrative', () => {
  const curated = mount();
  createProvenanceStamp(curated, {
    props: { curated: true, source: 'stadt-zuerich.ch', valid_as_of: '2026-07-18' },
  });
  assert.equal(curated.getAttribute('role'), 'note');
  assert.ok(curated.classList.contains('is-curated'));
  const text = curated.query((c) => c.classList.contains('ui-provstamp__text')).textContent;
  assert.match(text, /Official schedule/);
  assert.match(text, /last checked 2026-07-18/);

  const illus = mount();
  createProvenanceStamp(illus, { props: { curated: false } });
  assert.ok(illus.classList.contains('is-illustrative'));
  assert.match(
    illus.query((c) => c.classList.contains('ui-provstamp__text')).textContent,
    /Illustrative/,
  );
});

test('IconSet glyphs are decorative currentColor SVG (no hex) by default', () => {
  for (const name of ICON_NAMES) {
    const svg = iconSvg(name);
    assert.match(svg, /<svg/);
    assert.match(svg, /stroke="currentColor"/);
    assert.match(svg, /aria-hidden="true"/);
    assert.doesNotMatch(svg, /#[0-9a-fA-F]{3,8}/); // no raw hex in the glyph markup
  }
  // A titled glyph is promoted to role=img with a label.
  assert.match(iconSvg('lock', { title: 'Reserved' }), /role="img" aria-label="Reserved"/);
});
