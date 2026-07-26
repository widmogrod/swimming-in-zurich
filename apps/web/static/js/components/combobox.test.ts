import { expect, test } from 'vitest';

import { mount, type FakeElement } from './_fakedom.js';
import { fake, must } from '../testutil.js';
import { createCombobox } from './combobox.js';

const POOLS = [
  { value: 'oerlikon', label: 'Hallenbad Oerlikon' },
  { value: 'city', label: 'Hallenbad City' },
  { value: 'bungert', label: 'Bungertwies', closed: true },
];

function build(extra = {}) {
  const el = mount();
  const seen: unknown[] = [];
  const api = createCombobox(el, {
    props: { options: POOLS, label: 'Pool', ...extra },
    onChange: (v) => seen.push(v),
  });
  return { el, api, seen };
}

test('Combobox input carries the documented combobox ARIA', () => {
  const { api } = build();
  expect(api.input.getAttribute('role')).toBe('combobox');
  expect(api.input.getAttribute('aria-expanded')).toBe('false');
  expect(api.input.getAttribute('aria-autocomplete')).toBe('list');
  expect(api.input.getAttribute('aria-controls')).toBe(api.list.getAttribute('id'));
  expect(api.list.getAttribute('role')).toBe('listbox');
});

test('Combobox options are role=option with aria-selected on the value', () => {
  const { api } = build({ value: 'city' });
  api.open();
  const opts = fake(api.list).children;
  expect(opts.map((o: FakeElement) => o.getAttribute('role'))).toEqual(['option', 'option', 'option']);
  expect(opts.map((o: FakeElement) => o.getAttribute('aria-selected'))).toEqual(['false', 'true', 'false']);
  // The closed option renders its badge.
  expect(opts[2].query((c: FakeElement) => c.classList.contains('ui-combo__closed'))).toBeTruthy();
});

test('Combobox type-filter narrows the listbox', () => {
  const { api } = build();
  fake(api.input).focus();
  api.input.value = 'oer';
  fake(api.input).dispatch('input');
  expect(api.state().filtered.map((o) => o.value)).toEqual(['oerlikon']);
  expect(fake(api.list).children.length).toBe(1);
});

test('Combobox shows an explicit empty row when nothing matches', () => {
  const { api } = build({ emptyText: 'No pools match' });
  fake(api.input).focus();
  api.input.value = 'zzz';
  fake(api.input).dispatch('input');
  expect(api.state().filtered.length).toBe(0);
  const empty = must(fake(api.list).query((c: FakeElement) => c.classList.contains('ui-combo__empty')));
  expect(empty).toBeTruthy();
  expect(empty.textContent).toBe('No pools match');
});

test('Combobox ArrowDown/Up drive aria-activedescendant; Enter commits; Esc closes', () => {
  const { api, seen } = build();
  fake(api.input).focus();
  expect(api.input.getAttribute('aria-expanded')).toBe('true');
  fake(api.input).keydown('ArrowDown'); // active 0
  expect(api.input.getAttribute('aria-activedescendant')).toBe(api.list.children[0].getAttribute('id'));
  fake(api.input).keydown('ArrowDown'); // active 1
  expect(api.state().active).toBe(1);
  fake(api.input).keydown('Enter');
  expect(seen).toEqual(['city']);
  expect(api.value).toBe('city');
  expect(api.input.value).toBe('Hallenbad City');
  expect(api.input.getAttribute('aria-expanded')).toBe('false');
  // Reopen then Escape closes without committing.
  fake(api.input).focus();
  fake(api.input).keydown('Escape');
  expect(api.input.getAttribute('aria-expanded')).toBe('false');
  expect(seen).toEqual(['city']);
});

test('Disabled Combobox is aria-disabled and does not open on focus', () => {
  const { api } = build({ disabled: true });
  expect(api.input.getAttribute('aria-disabled')).toBe('true');
  fake(api.input).focus();
  expect(api.input.getAttribute('aria-expanded')).toBe('false');
});
