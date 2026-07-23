import test from 'node:test';
import assert from 'node:assert/strict';

import { createFilterToolbar } from './toolbar.js';
import { mount } from '../components/_fakedom.js';

const PROPS = {
  filter: { mode: 'day', date: '2026-07-23' },
  places: [{ label: 'Zürich HB', lat: 47.3779, lon: 8.5403 }],
  pools: [
    { value: 'oer', label: 'Hallenbad Oerlikon' },
    { value: 'city', label: 'Hallenbad City', closed: true },
  ],
  dateBounds: { today: '2026-07-23', min: '2026-07-23', max: '2026-09-01' },
};

function makeToolbar() {
  const el = mount();
  const emitted = [];
  const toolbar = createFilterToolbar(el, { props: PROPS, onChange: (f) => emitted.push(f) });
  return { el, toolbar, emitted };
}

test('toolbar starts in Day mode with a DateStepper in the context slot', () => {
  const { el, toolbar } = makeToolbar();
  assert.equal(el.getAttribute('role'), 'group');
  assert.ok(el.getAttribute('aria-label'));
  assert.equal(toolbar.contextKind, 'date');
  assert.equal(toolbar.getFilter().mode, 'day');
  const host = toolbar.controls.context.children[0];
  assert.ok(host.classList.contains('ui-datestepper'));
  assert.ok(!host.classList.contains('ui-combo'));
  // The mode control exposes its ARIA (role=group, aria-pressed per option).
  assert.equal(toolbar.controls.mode.el.getAttribute('role'), 'group');
  assert.ok(toolbar.controls.mode.buttons.every((b) => b.hasAttribute('aria-pressed')));
});

test('Pool mode mounts BOTH a week stepper and the pool Combobox, and emits mode=pool', () => {
  const { toolbar, emitted } = makeToolbar();
  const poolBtn = toolbar.controls.mode.buttons[1]; // [Day, Pool]
  poolBtn.click();

  const last = emitted[emitted.length - 1];
  assert.equal(last.mode, 'pool');
  assert.equal(toolbar.contextKind, 'pool');
  // The pool combobox is present…
  assert.equal(
    toolbar.controls.context.queryAll((c) => c.classList.contains('ui-combo')).length,
    1,
  );
  // …ALONGSIDE a week stepper (so the user can move week-to-week — plan item 2).
  const weekSteppers = toolbar.controls.context.queryAll((c) => c.classList.contains('ui-weekstepper'));
  assert.equal(weekSteppers.length, 1);
  assert.ok(weekSteppers[0].classList.contains('ui-datestepper')); // reuses the stepper look
  assert.ok(toolbar.controls.weekControl, 'the week stepper is exposed on controls');
  // Stepping a week emits a new (Monday) date without leaving Pool mode.
  const before = emitted.length;
  const nextWeekBtn = weekSteppers[0].query((c) => c.getAttribute('aria-label') === 'Next week');
  nextWeekBtn.click();
  assert.ok(emitted.length > before);
  assert.equal(emitted[emitted.length - 1].mode, 'pool');
  assert.notEqual(emitted[emitted.length - 1].date, undefined);
});

test('switching to Pool mode and back leaves a day stepper (no combobox) in Day mode', () => {
  const { toolbar } = makeToolbar();
  toolbar.controls.mode.buttons[1].click(); // Pool
  toolbar.controls.mode.buttons[0].click(); // Day
  assert.equal(toolbar.contextKind, 'date');
  const host = toolbar.controls.context.children[0];
  assert.ok(host.classList.contains('ui-datestepper'));
  assert.ok(!host.classList.contains('ui-weekstepper'));
  assert.equal(
    toolbar.controls.context.queryAll((c) => c.classList.contains('ui-combo')).length,
    0,
  );
});

test('gender / age / lap edits each emit the merged FilterState', () => {
  const { toolbar, emitted } = makeToolbar();

  toolbar.controls.gender.buttons[1].click(); // [Any, Female, …]
  assert.equal(emitted[emitted.length - 1].gender, 'female');

  toolbar.controls.age.buttons[3].click(); // [Any, Child, Teen, Adult(34), Senior]
  const afterAge = emitted[emitted.length - 1];
  assert.equal(afterAge.age, 34);
  assert.equal(typeof afterAge.age, 'number');

  const lapInput = toolbar.controls.lap.input;
  lapInput.checked = true;
  lapInput.dispatch('change');
  const afterLap = emitted[emitted.length - 1];
  assert.equal(afterLap.lapOnly, true);
  // The single emitted state is cumulative (still female + adult).
  assert.equal(afterLap.gender, 'female');
  assert.equal(afterLap.age, 34);
});

test('the busyness toggle is disabled and exposes its reason (honesty invariant)', () => {
  const { toolbar } = makeToolbar();
  const input = toolbar.controls.busyness.input;
  assert.equal(input.disabled, true);
  assert.equal(input.getAttribute('aria-disabled'), 'true');
  assert.ok(input.getAttribute('aria-description'));
  // Toggling it changes nothing (no data source yet).
  input.checked = true;
  input.dispatch('change');
  assert.equal(toolbar.controls.busyness.checked, false);
});

test('place selection emits lat/lon/label into the merged state', () => {
  const { toolbar, emitted } = makeToolbar();
  // The PlaceTypeahead renders one <li> per preset; selecting it fires onChange.
  const opt = toolbar.controls.place.el.query((c) => c.classList.contains('ui-place__opt'));
  opt.dispatch('mousedown');
  const last = emitted[emitted.length - 1];
  assert.equal(last.place.lat, 47.3779);
  assert.equal(last.place.lon, 8.5403);
  assert.equal(last.place.label, 'Zürich HB');
});
