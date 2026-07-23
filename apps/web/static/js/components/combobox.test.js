import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createCombobox } from './combobox.js';

const POOLS = [
  { value: 'oerlikon', label: 'Hallenbad Oerlikon' },
  { value: 'city', label: 'Hallenbad City' },
  { value: 'bungert', label: 'Bungertwies', closed: true },
];

function build(extra = {}) {
  const el = mount();
  const seen = [];
  const api = createCombobox(el, {
    props: { options: POOLS, label: 'Pool', ...extra },
    onChange: (v) => seen.push(v),
  });
  return { el, api, seen };
}

test('Combobox input carries the documented combobox ARIA', () => {
  const { api } = build();
  assert.equal(api.input.getAttribute('role'), 'combobox');
  assert.equal(api.input.getAttribute('aria-expanded'), 'false');
  assert.equal(api.input.getAttribute('aria-autocomplete'), 'list');
  assert.equal(api.input.getAttribute('aria-controls'), api.list.getAttribute('id'));
  assert.equal(api.list.getAttribute('role'), 'listbox');
});

test('Combobox options are role=option with aria-selected on the value', () => {
  const { api } = build({ value: 'city' });
  api.open();
  const opts = api.list.children;
  assert.deepEqual(opts.map((o) => o.getAttribute('role')), ['option', 'option', 'option']);
  assert.deepEqual(
    opts.map((o) => o.getAttribute('aria-selected')),
    ['false', 'true', 'false'],
  );
  // The closed option renders its badge.
  assert.ok(opts[2].query((c) => c.classList.contains('ui-combo__closed')));
});

test('Combobox type-filter narrows the listbox', () => {
  const { api } = build();
  api.input.focus();
  api.input.value = 'oer';
  api.input.dispatch('input');
  assert.deepEqual(api.state().filtered.map((o) => o.value), ['oerlikon']);
  assert.equal(api.list.children.length, 1);
});

test('Combobox shows an explicit empty row when nothing matches', () => {
  const { api } = build({ emptyText: 'No pools match' });
  api.input.focus();
  api.input.value = 'zzz';
  api.input.dispatch('input');
  assert.equal(api.state().filtered.length, 0);
  const empty = api.list.query((c) => c.classList.contains('ui-combo__empty'));
  assert.ok(empty);
  assert.equal(empty.textContent, 'No pools match');
});

test('Combobox ArrowDown/Up drive aria-activedescendant; Enter commits; Esc closes', () => {
  const { api, seen } = build();
  api.input.focus();
  assert.equal(api.input.getAttribute('aria-expanded'), 'true');
  api.input.keydown('ArrowDown'); // active 0
  assert.equal(api.input.getAttribute('aria-activedescendant'), api.list.children[0].getAttribute('id'));
  api.input.keydown('ArrowDown'); // active 1
  assert.equal(api.state().active, 1);
  api.input.keydown('Enter');
  assert.deepEqual(seen, ['city']);
  assert.equal(api.value, 'city');
  assert.equal(api.input.value, 'Hallenbad City');
  assert.equal(api.input.getAttribute('aria-expanded'), 'false');
  // Reopen then Escape closes without committing.
  api.input.focus();
  api.input.keydown('Escape');
  assert.equal(api.input.getAttribute('aria-expanded'), 'false');
  assert.deepEqual(seen, ['city']);
});

test('Disabled Combobox is aria-disabled and does not open on focus', () => {
  const { api } = build({ disabled: true });
  assert.equal(api.input.getAttribute('aria-disabled'), 'true');
  api.input.focus();
  assert.equal(api.input.getAttribute('aria-expanded'), 'false');
});
