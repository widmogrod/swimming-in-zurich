import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createDateStepper, formatLabel, shiftDate } from './datestepper.js';

test('formatLabel renders an absolute "Dow D Mon" label', () => {
  assert.equal(formatLabel('2026-07-23'), 'Thu 23 Jul');
  assert.equal(formatLabel('2026-01-01'), 'Thu 1 Jan');
});

test('shiftDate crosses month boundaries', () => {
  assert.equal(shiftDate('2026-07-31', 1), '2026-08-01');
  assert.equal(shiftDate('2026-08-01', -1), '2026-07-31');
});

test('DateStepper labels its nav buttons and shows the Today tag on today', () => {
  const el = mount();
  createDateStepper(el, {
    props: { value: '2026-07-23', today: '2026-07-23', min: '2026-07-01', max: '2026-08-31' },
  });
  assert.equal(el.getAttribute('role'), 'group');
  const [prev, label, todaytag, next] = el.children;
  assert.equal(prev.getAttribute('aria-label'), 'Previous day');
  assert.equal(next.getAttribute('aria-label'), 'Next day');
  assert.equal(label.textContent, 'Thu 23 Jul');
  assert.equal(todaytag.getAttribute('aria-hidden'), 'false');
});

test('DateStepper steps forward and fires onChange with the new ISO date', () => {
  const el = mount();
  const seen = [];
  createDateStepper(el, {
    props: { value: '2026-07-23', today: '2026-07-23', min: '2026-07-01', max: '2026-08-31' },
    onChange: (v) => seen.push(v),
  });
  const [, label, todaytag, next] = el.children;
  next.click();
  assert.deepEqual(seen, ['2026-07-24']);
  assert.equal(label.textContent, 'Fri 24 Jul');
  assert.equal(todaytag.getAttribute('aria-hidden'), 'true'); // no longer today
});

test('DateStepper disables prev at the min bound and refuses to step past it', () => {
  const el = mount();
  const seen = [];
  createDateStepper(el, {
    props: { value: '2026-07-23', min: '2026-07-23', max: '2026-08-31' },
    onChange: (v) => seen.push(v),
  });
  const [prev] = el.children;
  assert.equal(prev.getAttribute('aria-disabled'), 'true');
  assert.equal(prev.disabled, true);
  prev.click();
  assert.deepEqual(seen, []);
});
