import { expect, test } from 'vitest';

import { mount } from './_fakedom.js';
import { createDateStepper, formatLabel, shiftDate } from './datestepper.js';

test('formatLabel renders an absolute "Dow D Mon" label', () => {
  expect(formatLabel('2026-07-23')).toBe('Thu 23 Jul');
  expect(formatLabel('2026-01-01')).toBe('Thu 1 Jan');
});

test('shiftDate crosses month boundaries', () => {
  expect(shiftDate('2026-07-31', 1)).toBe('2026-08-01');
  expect(shiftDate('2026-08-01', -1)).toBe('2026-07-31');
});

test('DateStepper labels its nav buttons and shows the Today tag on today', () => {
  const el = mount();
  createDateStepper(el, {
    props: { value: '2026-07-23', today: '2026-07-23', min: '2026-07-01', max: '2026-08-31' },
  });
  expect(el.getAttribute('role')).toBe('group');
  const [prev, label, todaytag, next] = el.children;
  expect(prev.getAttribute('aria-label')).toBe('Previous day');
  expect(next.getAttribute('aria-label')).toBe('Next day');
  expect(label.textContent).toBe('Thu 23 Jul');
  expect(todaytag.getAttribute('aria-hidden')).toBe('false');
});

test('DateStepper steps forward and fires onChange with the new ISO date', () => {
  const el = mount();
  const seen: string[] = [];
  createDateStepper(el, {
    props: { value: '2026-07-23', today: '2026-07-23', min: '2026-07-01', max: '2026-08-31' },
    onChange: (v) => seen.push(v),
  });
  const [, label, todaytag, next] = el.children;
  next.click();
  expect(seen).toEqual(['2026-07-24']);
  expect(label.textContent).toBe('Fri 24 Jul');
  expect(todaytag.getAttribute('aria-hidden')).toBe('true'); // no longer today
});

test('DateStepper disables prev at the min bound and refuses to step past it', () => {
  const el = mount();
  const seen: string[] = [];
  createDateStepper(el, {
    props: { value: '2026-07-23', min: '2026-07-23', max: '2026-08-31' },
    onChange: (v) => seen.push(v),
  });
  const [prev] = el.children;
  expect(prev.getAttribute('aria-disabled')).toBe('true');
  expect(prev.disabled).toBe(true);
  prev.click();
  expect(seen).toEqual([]);
});
