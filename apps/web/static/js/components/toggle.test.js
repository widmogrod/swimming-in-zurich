import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createToggle } from './toggle.js';

test('Toggle uses the switch role and reflects aria-checked on change', () => {
  const el = mount();
  const seen = [];
  const api = createToggle(el, {
    props: { label: 'Lap only' },
    onChange: (v) => seen.push(v),
  });
  assert.equal(api.input.getAttribute('role'), 'switch');
  assert.equal(api.input.getAttribute('aria-checked'), 'false');
  api.input.checked = true;
  api.input.dispatch('change');
  assert.deepEqual(seen, [true]);
  assert.equal(api.input.getAttribute('aria-checked'), 'true');
  assert.ok(el.classList.contains('is-on'));
});

test('Toggle starts checked when props.checked is set', () => {
  const el = mount();
  const api = createToggle(el, { props: { label: 'Lap only', checked: true } });
  assert.equal(api.checked, true);
  assert.equal(api.input.getAttribute('aria-checked'), 'true');
  assert.ok(el.classList.contains('is-on'));
});

test('Disabled Toggle is aria-disabled, carries its reason, and refuses change', () => {
  const el = mount();
  const seen = [];
  const api = createToggle(el, {
    props: { label: 'Busyness', disabled: true, reason: 'Busyness data is not available yet' },
    onChange: (v) => seen.push(v),
  });
  assert.equal(api.input.getAttribute('aria-disabled'), 'true');
  assert.equal(el.getAttribute('title'), 'Busyness data is not available yet');
  assert.equal(api.input.getAttribute('aria-description'), 'Busyness data is not available yet');
  // A change event on a disabled toggle is refused and the state restored.
  api.input.checked = true;
  api.input.dispatch('change');
  assert.deepEqual(seen, []);
  assert.equal(api.input.checked, false);
});
