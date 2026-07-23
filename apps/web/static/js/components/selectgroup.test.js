import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createSegmentedControl } from './segmentedcontrol.js';
import { createChipGroup } from './chipgroup.js';

const MODES = [
  { value: 'day', label: 'Day' },
  { value: 'pool', label: 'Pool' },
  { value: 'week', label: 'Week' },
];

test('SegmentedControl exposes role=group and aria-pressed reflecting selection', () => {
  const el = mount();
  createSegmentedControl(el, { props: { items: MODES, selected: 'pool', label: 'Mode' } });
  assert.equal(el.getAttribute('role'), 'group');
  assert.equal(el.getAttribute('aria-label'), 'Mode');
  const pressed = el.children.map((b) => b.getAttribute('aria-pressed'));
  assert.deepEqual(pressed, ['false', 'true', 'false']);
  // Roving tabindex: only the selected option is focusable.
  assert.deepEqual(el.children.map((b) => b.getAttribute('tabindex')), ['-1', '0', '-1']);
});

test('SegmentedControl click selects and fires onChange once with the value', () => {
  const el = mount();
  const seen = [];
  createSegmentedControl(el, {
    props: { items: MODES, selected: 'day' },
    onChange: (v) => seen.push(v),
  });
  el.children[2].click(); // Week
  assert.deepEqual(seen, ['week']);
  assert.equal(el.children[2].getAttribute('aria-pressed'), 'true');
  assert.equal(el.children[0].getAttribute('aria-pressed'), 'false');
  // Clicking the already-selected option does not re-fire.
  el.children[2].click();
  assert.deepEqual(seen, ['week']);
});

test('SegmentedControl arrow keys move selection, wrap, and preventDefault', () => {
  const el = mount();
  const seen = [];
  createSegmentedControl(el, {
    props: { items: MODES, selected: 'day' },
    onChange: (v) => seen.push(v),
  });
  const ev = el.children[0].keydown('ArrowRight');
  assert.equal(ev.defaultPrevented, true);
  assert.deepEqual(seen, ['pool']);
  el.children[1].keydown('ArrowRight'); // → week
  el.children[2].keydown('ArrowRight'); // wrap → day
  assert.deepEqual(seen, ['pool', 'week', 'day']);
  // A non-nav key is ignored (no preventDefault, no change).
  const ev2 = el.children[0].keydown('Enter');
  assert.equal(ev2.defaultPrevented, false);
  assert.deepEqual(seen, ['pool', 'week', 'day']);
});

test('SegmentedControl mode variant adds the accent skin class', () => {
  const el = mount();
  createSegmentedControl(el, { props: { items: MODES, variant: 'mode' } });
  assert.ok(el.classList.contains('ui-seg--mode'));
});

test('Disabled SegmentedControl marks aria-disabled and ignores interaction', () => {
  const el = mount();
  const seen = [];
  createSegmentedControl(el, {
    props: { items: MODES, selected: 'day', disabled: true },
    onChange: (v) => seen.push(v),
  });
  assert.equal(el.getAttribute('aria-disabled'), 'true');
  assert.ok(el.children.every((b) => b.getAttribute('aria-disabled') === 'true'));
  el.children[1].click();
  el.children[0].keydown('ArrowRight');
  assert.deepEqual(seen, []);
});

test('ChipGroup shares the roving group ARIA under its own skin classes', () => {
  const el = mount();
  const seen = [];
  createChipGroup(el, {
    props: {
      label: 'Age',
      items: [
        { value: '6', label: 'Kid' },
        { value: '34', label: 'Adult' },
      ],
      selected: '6',
    },
    onChange: (v) => seen.push(v),
  });
  assert.equal(el.getAttribute('role'), 'group');
  assert.ok(el.classList.contains('ui-chipgroup'));
  assert.ok(el.children[0].classList.contains('ui-chip'));
  // Focus starts on the selected chip (index 0); ArrowRight moves to '34'.
  el.children[0].keydown('ArrowRight');
  assert.deepEqual(seen, ['34']);
  assert.equal(el.children[1].getAttribute('aria-pressed'), 'true');
});
