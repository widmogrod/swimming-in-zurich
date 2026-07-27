import { expect, test } from 'vitest';

import { mount, type FakeElement } from './_fakedom.js';
import { fake, must } from '../testutil.js';
import { createSelect } from './select.js';

const LOCALES = [
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
  { value: 'pl', label: 'Polski' },
];

function build(extra = {}) {
  const el = mount();
  const seen: string[] = [];
  const api = createSelect(el, {
    props: { options: LOCALES, label: 'Language', ...extra },
    onChange: (v) => seen.push(v),
  });
  return { el: fake(el), api, seen };
}

test('Select keeps the native control and does NOT override its role', () => {
  const { api } = build();
  expect(api.control.tagName).toBe('SELECT');
  // A native <select> already exposes the right semantics; an explicit role would
  // replace them, which is the whole reason this primitive is not a custom listbox.
  expect(api.control.getAttribute('role')).toBeFalsy();
  expect(api.control.getAttribute('aria-label')).toBe('Language');
});

test('Select renders one <option> per choice, marking the current value', () => {
  const { api } = build({ value: 'de' });
  const options = fake(api.control).children;
  expect(options.map((o: FakeElement) => o.value)).toEqual(['en', 'de', 'pl']);
  expect(options.map((o: FakeElement) => o.textContent)).toEqual(['English', 'Deutsch', 'Polski']);
  expect(options.map((o: FakeElement) => o.getAttribute('selected'))).toEqual([
    null,
    'selected',
    null,
  ]);
  expect(api.value).toBe('de');
});

test('Select falls back to the first option when given no value', () => {
  const { api } = build();
  expect(api.value).toBe('en');
});

test('an empty Select is empty rather than undefined', () => {
  const el = mount();
  const api = createSelect(el, { props: { options: [] } });
  expect(api.value).toBe('');
  expect(fake(api.control).children).toEqual([]);
});

test('an individually disabled option is disabled on the node, not dropped', () => {
  const { api } = build({ options: [...LOCALES, { value: 'rm', label: 'Rumantsch', disabled: true }] });
  const options = fake(api.control).children;
  expect(options.length).toBe(4);
  expect(options.map((o: FakeElement) => o.disabled)).toEqual([false, false, false, true]);
});

test('changing the control reports the new value exactly once', () => {
  const { api, seen } = build({ value: 'en' });
  api.control.value = 'pl';
  fake(api.control).dispatch('change');
  expect(seen).toEqual(['pl']);
  expect(api.value).toBe('pl');
  // A change event that does not actually change the value is not a change.
  fake(api.control).dispatch('change');
  expect(seen).toEqual(['pl']);
});

test('setValue moves the control without re-reporting', () => {
  const { api, seen } = build({ value: 'en' });
  api.setValue('de');
  expect(api.value).toBe('de');
  expect(api.control.value).toBe('de');
  expect(seen).toEqual([]);
});

test('a disabled Select refuses the change and restores its value', () => {
  const { el, api, seen } = build({ value: 'en', disabled: true });
  expect(el.classList.contains('is-disabled')).toBe(true);
  expect(api.control.getAttribute('aria-disabled')).toBe('true');
  api.control.value = 'pl';
  fake(api.control).dispatch('change');
  expect(seen).toEqual([]);
  expect(api.value).toBe('en');
  expect(api.control.value).toBe('en');
});

test('the chrome lives on the WRAPPER, so the control carries no border classes', () => {
  const { el, api } = build();
  expect(el.classList.contains('ui-select')).toBe(true);
  expect(api.control.className).toBe('ui-select__control');
});

test('the pill variant is opt-in', () => {
  expect(build().el.classList.contains('ui-select--pill')).toBe(false);
  expect(build({ variant: 'pill' }).el.classList.contains('ui-select--pill')).toBe(true);
});

test('the optional glyph is a decorative currentColor SVG, never an emoji', () => {
  const { el } = build({ icon: 'globe' });
  const icon = must(el.query((c: FakeElement) => c.classList.contains('ui-select__icon')));
  expect(icon.getAttribute('aria-hidden')).toBe('true');
  expect(icon.innerHTML).toContain('stroke="currentColor"');
  // No icon prop → no glyph slot at all.
  expect(build().el.query((c: FakeElement) => c.classList.contains('ui-select__icon'))).toBeNull();
});
