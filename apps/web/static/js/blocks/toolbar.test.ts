import { expect, test } from 'vitest';

import type { FilterState } from '../filterstate.js';
import { createFilterToolbar } from './toolbar.js';
import { mount, type FakeElement } from '../components/_fakedom.js';
import { fake, must } from '../testutil.js';

const PROPS = {
  filter: { mode: 'day' as const, date: '2026-07-23' },
  places: [{ label: 'Zürich HB', lat: 47.3779, lon: 8.5403 }],
  pools: [
    { value: 'oer', label: 'Hallenbad Oerlikon' },
    { value: 'city', label: 'Hallenbad City', closed: true },
  ],
  dateBounds: { today: '2026-07-23', min: '2026-07-23', max: '2026-09-01' },
};

function makeToolbar() {
  const el = mount();
  const emitted: FilterState[] = [];
  const toolbar = createFilterToolbar(el, { props: PROPS, onChange: (f) => emitted.push(f) });
  return { el, toolbar, emitted };
}

test('toolbar starts in Day mode with a DateStepper in the context slot', () => {
  const { el, toolbar } = makeToolbar();
  expect(el.getAttribute('role')).toBe('group');
  expect(el.getAttribute('aria-label')).toBeTruthy();
  expect(toolbar.contextKind).toBe('date');
  expect(toolbar.getFilter().mode).toBe('day');
  const host = toolbar.controls.context.children[0];
  expect(host.classList.contains('ui-datestepper')).toBeTruthy();
  expect(!host.classList.contains('ui-combo')).toBeTruthy();
  // The mode control exposes its ARIA (role=group, aria-pressed per option).
  expect(toolbar.controls.mode.el.getAttribute('role')).toBe('group');
  expect(toolbar.controls.mode.buttons.every((b) => b.hasAttribute('aria-pressed'))).toBeTruthy();
});

test('Pool mode mounts BOTH a week stepper and the pool Combobox, and emits mode=pool', () => {
  const { toolbar, emitted } = makeToolbar();
  const poolBtn = toolbar.controls.mode.buttons[1]; // [Day, Pool]
  poolBtn.click();

  const last = emitted[emitted.length - 1];
  expect(last.mode).toBe('pool');
  expect(toolbar.contextKind).toBe('pool');
  // The pool combobox is present…
  expect(fake(toolbar.controls.context).queryAll((c: FakeElement) => c.classList.contains('ui-combo')).length).toBe(1);
  // …ALONGSIDE a week stepper (so the user can move week-to-week — plan item 2).
  const weekSteppers = fake(toolbar.controls.context).queryAll((c: FakeElement) => c.classList.contains('ui-weekstepper'));
  expect(weekSteppers.length).toBe(1);
  expect(weekSteppers[0].classList.contains('ui-datestepper')).toBeTruthy(); // reuses the stepper look
  expect(toolbar.controls.weekControl).toBeTruthy();
  // Stepping a week emits a new (Monday) date without leaving Pool mode.
  const before = emitted.length;
  const nextWeekBtn = must(
    weekSteppers[0].query((c: FakeElement) => c.getAttribute('aria-label') === 'Next week'),
    'Next week button',
  );
  nextWeekBtn.click();
  expect(emitted.length > before).toBeTruthy();
  expect(emitted[emitted.length - 1].mode).toBe('pool');
  expect(emitted[emitted.length - 1].date).not.toBe(undefined);
});

test('switching to Pool mode and back leaves a day stepper (no combobox) in Day mode', () => {
  const { toolbar } = makeToolbar();
  toolbar.controls.mode.buttons[1].click(); // Pool
  toolbar.controls.mode.buttons[0].click(); // Day
  expect(toolbar.contextKind).toBe('date');
  const host = toolbar.controls.context.children[0];
  expect(host.classList.contains('ui-datestepper')).toBeTruthy();
  expect(!host.classList.contains('ui-weekstepper')).toBeTruthy();
  expect(fake(toolbar.controls.context).queryAll((c: FakeElement) => c.classList.contains('ui-combo')).length).toBe(0);
});

test('gender / age / lap edits each emit the merged FilterState', () => {
  const { toolbar, emitted } = makeToolbar();

  toolbar.controls.gender.buttons[1].click(); // [Any, Female, …]
  expect(emitted[emitted.length - 1].gender).toBe('female');

  toolbar.controls.age.buttons[3].click(); // [Any, Child, Teen, Adult(34), Senior]
  const afterAge = emitted[emitted.length - 1];
  expect(afterAge.age).toBe(34);
  expect(typeof afterAge.age).toBe('number');

  const lapInput = fake(toolbar.controls.lap.input);
  lapInput.checked = true;
  lapInput.dispatch('change');
  const afterLap = emitted[emitted.length - 1];
  expect(afterLap.lapOnly).toBe(true);
  // The single emitted state is cumulative (still female + adult).
  expect(afterLap.gender).toBe('female');
  expect(afterLap.age).toBe(34);
});

test('the busyness toggle is disabled and exposes its reason (honesty invariant)', () => {
  const { toolbar } = makeToolbar();
  const input = fake(toolbar.controls.busyness.input);
  expect(input.disabled).toBe(true);
  expect(input.getAttribute('aria-disabled')).toBe('true');
  expect(input.getAttribute('aria-description')).toBeTruthy();
  // Toggling it changes nothing (no data source yet).
  input.checked = true;
  input.dispatch('change');
  expect(toolbar.controls.busyness.checked).toBe(false);
});

// The pool combobox is the READ/WRITE surface for the ONE shared `selectedPool`
// (retiring the old smuggled `filter.pool`). Its value must read selectedPool.id, and
// picking an option must write `{ id, name }` back — never a `pool` key.
test('pool combobox reads selectedPool.id and writes selectedPool on pick (no filter.pool)', () => {
  const el = mount();
  const emitted: FilterState[] = [];
  const toolbar = createFilterToolbar(el, {
    props: { ...PROPS, filter: { mode: 'pool', selectedPool: { id: 'oer', name: 'Hallenbad Oerlikon' } } },
    onChange: (f) => emitted.push(f),
  });
  // The combobox mounts with the selected pool's NAME shown (value read from its id).
  const combo = must(fake(toolbar.controls.context).query((c) => c.classList.contains('ui-combo')));
  const input = must(
    combo.query((c) => c.tagName === 'INPUT' || c.classList.contains('ui-combo__input')),
  );
  expect(input.value).toBe('Hallenbad Oerlikon');

  // Picking another option emits selectedPool = { id, name } and NO `pool` key.
  const opt = must(
    combo
      .queryAll((c) => c.classList.contains('ui-combo__opt'))
      .find((li) => li.dataset.value === 'city'),
    'city option',
  );
  opt.dispatch('mousedown');
  const last = emitted[emitted.length - 1];
  expect(last.selectedPool).toEqual({ id: 'city', name: 'Hallenbad City' });
  // `pool` is not a FilterState key at all — the selection lives in `selectedPool`.
  expect('pool' in last).toBe(false);
});

test('place selection emits lat/lon/label into the merged state', () => {
  const { toolbar, emitted } = makeToolbar();
  // The PlaceTypeahead renders one <li> per preset; selecting it fires onChange.
  const opt = must(fake(toolbar.controls.place.el).query((c) => c.classList.contains('ui-place__opt')));
  opt.dispatch('mousedown');
  const last = emitted[emitted.length - 1];
  const place = last.place as { lat: number; lon: number; label: string };
  expect(place.lat).toBe(47.3779);
  expect(place.lon).toBe(8.5403);
  expect(place.label).toBe('Zürich HB');
});
