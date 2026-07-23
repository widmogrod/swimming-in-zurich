import test from 'node:test';
import assert from 'node:assert/strict';

import { FakeDocument } from './_fakedom.js';
import { REGISTRY } from './registry.js';

// The states the Python gallery route renders per component (must stay in sync
// with apps/web/api/gallery/router.py::_COMPONENTS).
const GALLERY_STATES = {
  'segmented-control': ['default', 'selected', 'disabled'],
  'chip-group': ['default', 'selected', 'disabled'],
  combobox: ['default', 'selected', 'empty', 'disabled'],
  'place-typeahead': ['default', 'empty', 'disabled'],
  toggle: ['default', 'selected', 'disabled'],
  'date-stepper': ['default', 'disabled'],
  'state-pill': ['open', 'opens-later', 'closed', 'unknown'],
  'eligibility-badge': ['in', 'chk', 'no'],
  'length-lanes-badge': ['default', 'empty'],
  'provenance-stamp': ['curated', 'illustrative'],
  'icon-set': ['default'],
};

test('every gallery component name has a registry entry', () => {
  for (const name of Object.keys(GALLERY_STATES)) {
    assert.ok(REGISTRY[name], `missing registry entry: ${name}`);
  }
  assert.deepEqual(
    Object.keys(REGISTRY).sort(),
    Object.keys(GALLERY_STATES).sort(),
  );
});

test('every registry entry hydrates headlessly for each documented state', () => {
  for (const [name, states] of Object.entries(GALLERY_STATES)) {
    const entry = REGISTRY[name];
    for (const state of states) {
      const doc = new FakeDocument();
      const el = doc.createElement('div');
      assert.doesNotThrow(() => {
        entry.create(el, { props: entry.props(state), onChange: () => {} });
      }, `${name}/${state} threw`);
      assert.ok(el.children.length > 0, `${name}/${state} rendered nothing`);
    }
  }
});

test('every interactive primitive exposes a role on its control element', () => {
  const rootRole = { 'segmented-control': 'group', 'chip-group': 'group', 'date-stepper': 'group' };
  const inputRole = { combobox: 'combobox', 'place-typeahead': 'combobox', toggle: 'switch' };
  for (const [name, entry] of Object.entries(REGISTRY)) {
    if (!entry.interactive) continue;
    const doc = new FakeDocument();
    const el = doc.createElement('div');
    entry.create(el, { props: entry.props('default'), onChange: () => {} });
    if (rootRole[name]) {
      assert.equal(el.getAttribute('role'), rootRole[name], `${name} root role`);
    } else {
      const control = el.query((c) => c.getAttribute && c.getAttribute('role') === inputRole[name]);
      assert.ok(control, `${name} exposes role=${inputRole[name]}`);
    }
  }
});
