// toolbar.js — the FilterToolbar block (plan Part 3 §2).
//
// The global context spine: it composes the S1 primitives into ONE control strip
// and emits ONE `FilterState` (the S0 filterstate module) that drives every other
// block. Layout only — it owns no colour, no hex; each primitive is already
// token-styled by components.css and the strip is laid out via blocks.css.
//
//   [ mode Day|Pool ] [ DateStepper (Day) / Combobox pool (Pool) ] [ Place ]
//   [ gender ]        [ age chips ]        [ lap-only ] [ busyness (disabled) ]
//
// Mode is the pivot: switching Day↔Pool SWAPS the second field between the
// DateStepper and the pool Combobox (the two are never both mounted). Every child
// onChange merges a patch into the single filter and re-emits.

import { createSegmentedControl } from '../components/segmentedcontrol.js';
import { createDateStepper, formatLabel, shiftDate } from '../components/datestepper.js';
import { createCombobox } from '../components/combobox.js';
import { createPlaceTypeahead } from '../components/placetypeahead.js';
import { createChipGroup } from '../components/chipgroup.js';
import { createToggle } from '../components/toggle.js';
import { createFilterState, merge } from '../filterstate.js';

// The ISO Monday of a date's week (Mon=0). Pure UTC arithmetic (mirrors api.js).
function mondayOf(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  const dow = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  return shiftDate(iso, -dow);
}

/**
 * createWeekStepper(el, { props, onChange }) — a "‹ Week of Mon 20 Jul ›" pager for
 * Pool mode: it steps a WHOLE week at a time (±7 days, snapped to Monday) and shows a
 * TODAY tag when the shown week contains today. It reuses the DateStepper's DOM/classes
 * for a consistent look; `onChange(mondayIso)` fires with the new week's Monday.
 * Absolute dates only — never "this week".
 */
export function createWeekStepper(el, { props = {}, onChange } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  let monday = mondayOf(props.value || props.today);
  const minMon = props.min ? mondayOf(props.min) : null;
  const maxMon = props.max ? mondayOf(props.max) : null;
  const todayMon = props.today ? mondayOf(props.today) : null;

  el.classList.add('ui-datestepper', 'ui-weekstepper');
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', props.label || 'Selected week');

  const prev = doc.createElement('button');
  prev.type = 'button';
  prev.className = 'ui-datestepper__nav';
  prev.setAttribute('aria-label', 'Previous week');
  prev.textContent = '‹';

  const labelEl = doc.createElement('span');
  labelEl.className = 'ui-datestepper__label tnum';
  labelEl.setAttribute('aria-live', 'polite');

  const todaytag = doc.createElement('span');
  todaytag.className = 'ui-datestepper__today';
  todaytag.textContent = 'Today';

  const next = doc.createElement('button');
  next.type = 'button';
  next.className = 'ui-datestepper__nav';
  next.setAttribute('aria-label', 'Next week');
  next.textContent = '›';

  const atMin = () => !!(minMon && monday <= minMon);
  const atMax = () => !!(maxMon && monday >= maxMon);

  function render() {
    labelEl.textContent = `Week of ${formatLabel(monday)}`;
    prev.disabled = atMin();
    prev.setAttribute('aria-disabled', String(atMin()));
    next.disabled = atMax();
    next.setAttribute('aria-disabled', String(atMax()));
    const isThisWeek = !!(todayMon && monday === todayMon);
    todaytag.style.display = isThisWeek ? '' : 'none';
    todaytag.setAttribute('aria-hidden', String(!isThisWeek));
  }

  function step(days, guard) {
    if (guard()) return;
    monday = mondayOf(shiftDate(monday, days));
    render();
    if (onChange) onChange(monday);
  }

  prev.addEventListener('click', () => step(-7, atMin));
  next.addEventListener('click', () => step(7, atMax));

  el.appendChild(prev);
  el.appendChild(labelEl);
  el.appendChild(todaytag);
  el.appendChild(next);
  render();
  return {
    el,
    get value() {
      return monday;
    },
  };
}

const MODE_ITEMS = [
  { value: 'day', label: 'Day' },
  { value: 'pool', label: 'Pool' },
];
const GENDER_ITEMS = [
  { value: '', label: 'Any' },
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
  { value: 'diverse', label: 'Diverse' },
];
// Age chips carry a REPRESENTATIVE age for the range (plan Part 2), '' = unset.
export const DEFAULT_AGE_CHIPS = [
  { value: '', label: 'Any age' },
  { value: '8', label: 'Child' },
  { value: '16', label: 'Teen' },
  { value: '34', label: 'Adult' },
  { value: '70', label: 'Senior' },
];
const BUSYNESS_REASON = 'Busyness has no data source yet — not available.';

// A labelled field wrapper so controls read (and stack full-width on a phone).
function field(doc, caption, control) {
  const wrap = doc.createElement('div');
  wrap.className = 'toolbar__field';
  if (caption) {
    const cap = doc.createElement('span');
    cap.className = 'toolbar__caption';
    cap.textContent = caption;
    wrap.appendChild(cap);
  }
  wrap.appendChild(control);
  return wrap;
}

/**
 * createFilterToolbar(el, opts) — mount the toolbar and drive one FilterState.
 * @param {object} opts.props
 *   `{ filter, pools:[{value,label,closed?}], places:[{label,lat,lon}],
 *      ages:[{value,label}], dateBounds:{min,max,today} }`.
 * @param {function} opts.onChange called with the merged FilterState on every edit.
 * @returns {{el, controls, getFilter, contextKind}}
 */
export function createFilterToolbar(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const props = opts.props || {};
  const onChange = opts.onChange;
  const pools = props.pools || [];
  const places = props.places || [];
  const ages = props.ages || DEFAULT_AGE_CHIPS;
  const bounds = props.dateBounds || {};

  let filter = createFilterState(props.filter || {});

  el.classList.add('toolbar');
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', 'Search filters');

  function emit() {
    if (onChange) onChange(filter);
  }
  function update(patch) {
    filter = merge(filter, patch);
    emit();
  }

  // --- mode Day/Pool (the pivot) ---
  const mode = createSegmentedControl(doc.createElement('div'), {
    props: { items: MODE_ITEMS, selected: filter.mode, variant: 'mode', label: 'View mode' },
    onChange: (v) => setMode(v),
  });

  // --- context slot: DateStepper (Day) ↔ pool Combobox (Pool) ---
  const contextSlot = doc.createElement('div');
  contextSlot.className = 'toolbar__context';
  let contextKind = null;
  let contextControl = null;
  let weekControl = null;

  function renderContext() {
    contextSlot.textContent = '';
    if (filter.mode === 'pool') {
      contextKind = 'pool';
      // Pool mode carries BOTH a WEEK stepper (move week-to-week — plan item 2) AND
      // the pool Combobox, side by side. The stepper drives filter.date (its Monday);
      // the board renders whichever week contains it.
      const weekHost = doc.createElement('div');
      contextSlot.appendChild(weekHost);
      weekControl = createWeekStepper(weekHost, {
        props: {
          value: filter.date || bounds.today,
          min: bounds.min,
          max: bounds.max,
          today: bounds.today,
          label: 'Selected week',
        },
        onChange: (mondayIso) => update({ date: mondayIso }),
      });
      const comboHost = doc.createElement('div');
      contextSlot.appendChild(comboHost);
      contextControl = createCombobox(comboHost, {
        props: {
          options: pools,
          value: filter.pool ? filter.pool.value : null,
          label: 'Pool',
          placeholder: 'Search a pool…',
        },
        onChange: (value) => {
          const opt = pools.find((p) => p.value === value) || null;
          update({ pool: opt ? { value: opt.value, label: opt.label } : null });
        },
      });
    } else {
      contextKind = 'date';
      weekControl = null;
      const host = doc.createElement('div');
      contextSlot.appendChild(host);
      contextControl = createDateStepper(host, {
        props: {
          value: filter.date || bounds.today,
          min: bounds.min,
          max: bounds.max,
          today: bounds.today,
          label: 'Selected day',
        },
        onChange: (iso) => update({ date: iso }),
      });
    }
  }

  function setMode(v) {
    if (v === filter.mode) return;
    filter = merge(filter, { mode: v });
    renderContext();
    emit();
  }

  // --- place ---
  const place = createPlaceTypeahead(doc.createElement('div'), {
    props: { presets: places, label: 'Near', placeholder: 'Where from?' },
    onChange: ({ lat, lon, label }) => update({ place: { lat, lon, label } }),
  });

  // --- gender ---
  const gender = createSegmentedControl(doc.createElement('div'), {
    props: { items: GENDER_ITEMS, selected: filter.gender || '', label: 'Gender' },
    onChange: (v) => update({ gender: v }),
  });

  // --- age chips ---
  const age = createChipGroup(doc.createElement('div'), {
    props: {
      items: ages,
      selected: filter.age != null ? String(filter.age) : '',
      label: 'Age',
    },
    onChange: (v) => update({ age: v === '' ? null : Number(v) }),
  });

  // --- lap-only ---
  const lap = createToggle(doc.createElement('div'), {
    props: { checked: !!filter.lapOnly, label: 'Lap lanes only' },
    onChange: (checked) => update({ lapOnly: checked }),
  });

  // --- busyness (DISABLED — no data source yet; the honesty invariant made visible) ---
  const busyness = createToggle(doc.createElement('div'), {
    props: { checked: false, disabled: true, label: 'Busyness', reason: BUSYNESS_REASON },
  });

  // Assemble the strip.
  renderContext();
  el.appendChild(field(doc, 'View', mode.el));
  el.appendChild(field(doc, null, contextSlot));
  el.appendChild(field(doc, 'Near', place.el));
  el.appendChild(field(doc, 'Gender', gender.el));
  el.appendChild(field(doc, 'Age', age.el));
  el.appendChild(field(doc, null, lap.el));
  el.appendChild(field(doc, null, busyness.el));

  return {
    el,
    controls: {
      mode,
      context: contextSlot,
      place,
      gender,
      age,
      lap,
      busyness,
      get contextControl() {
        return contextControl;
      },
      get weekControl() {
        return weekControl;
      },
    },
    getFilter: () => filter,
    get contextKind() {
      return contextKind;
    },
  };
}
