import { expect, test } from 'vitest';

import { FakeDocument } from './_fakedom.js';
import { REGISTRY } from './registry.js';
import { must } from '../testutil.js';

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
    expect(REGISTRY[name as keyof typeof REGISTRY]).toBeTruthy();
  }
  expect(Object.keys(REGISTRY).sort()).toEqual(Object.keys(GALLERY_STATES).sort());
});

test('every registry entry hydrates headlessly for each documented state', () => {
  for (const [name, states] of Object.entries(GALLERY_STATES)) {
    const entry = REGISTRY[name as keyof typeof REGISTRY];
    for (const state of states) {
      const doc = new FakeDocument();
      const el = doc.createElement('div');
      expect(() => {
        entry.create(el, { props: entry.props(state), onChange: () => {} });
      }).not.toThrow();
      expect(el.children.length > 0).toBeTruthy();
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
    const wantRootRole = (rootRole as Record<string, string | undefined>)[name];
    if (wantRootRole) {
      expect(el.getAttribute('role')).toBe(wantRootRole);
    } else {
      const control = must(el.query((c) => c.getAttribute && c.getAttribute('role') === (inputRole as Record<string, string | undefined>)[name]));
      expect(control).toBeTruthy();
    }
  }
});
