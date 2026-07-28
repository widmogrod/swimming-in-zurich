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
import { t } from '../i18n.js';
import { createDateStepper, formatLabel, shiftDate } from '../components/datestepper.js';
import { createCombobox } from '../components/combobox.js';
import { createPlaceTypeahead } from '../components/placetypeahead.js';
import { createChipGroup } from '../components/chipgroup.js';
import { createToggle } from '../components/toggle.js';
import { createFilterState, merge, type FilterState } from '../filterstate.js';
import { mondayOf } from '../datefmt.js';
import { asDoc, type Doc, type El } from '../domtypes.js';

export interface DateBounds {
  min?: string;
  max?: string;
  today?: string;
}

export interface WeekStepperProps extends DateBounds {
  value?: string;
  label?: string;
}

export interface ChipItem {
  value: string;
  label: string;
}

export interface ToolbarProps {
  filter?: Partial<FilterState>;
  pools?: { value: string; label: string; closed?: boolean }[];
  places?: { label: string; lat: number; lon: number }[];
  ages?: ChipItem[];
  dateBounds?: DateBounds;
}

// mondayOf was duplicated here, in api and in urlstate; it now has one home.

/**
 * createWeekStepper(el, { props, onChange }) — a "‹ Week of Mon 20 Jul ›" pager for
 * Pool mode: it steps a WHOLE week at a time (±7 days, snapped to Monday) and shows a
 * TODAY tag when the shown week contains today. It reuses the DateStepper's DOM/classes
 * for a consistent look; `onChange(mondayIso)` fires with the new week's Monday.
 * Absolute dates only — never "this week".
 */
export function createWeekStepper<T extends El>(
  el: T,
  { props = {}, onChange }: { props?: WeekStepperProps; onChange?: (iso: string) => void } = {},
): { el: T; readonly value: string } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  let monday = mondayOf(props.value || props.today || '');
  const minMon = props.min ? mondayOf(props.min) : null;
  const maxMon = props.max ? mondayOf(props.max) : null;
  const todayMon = props.today ? mondayOf(props.today) : null;

  el.classList.add('ui-datestepper', 'ui-weekstepper');
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', props.label || t('date.selectedWeek'));

  const prev = doc.createElement('button');
  prev.type = 'button';
  prev.className = 'ui-datestepper__nav';
  prev.setAttribute('aria-label', t('date.previousWeek'));
  prev.textContent = '‹';

  const labelEl = doc.createElement('span');
  labelEl.className = 'ui-datestepper__label tnum';
  labelEl.setAttribute('aria-live', 'polite');

  const todaytag = doc.createElement('span');
  todaytag.className = 'ui-datestepper__today';
  todaytag.textContent = t('common.today');

  const next = doc.createElement('button');
  next.type = 'button';
  next.className = 'ui-datestepper__nav';
  next.setAttribute('aria-label', t('date.nextWeek'));
  next.textContent = '›';

  const atMin = () => !!(minMon && monday <= minMon);
  const atMax = () => !!(maxMon && monday >= maxMon);

  function render() {
    labelEl.textContent = t('date.weekOf', { date: formatLabel(monday) });
    prev.disabled = atMin();
    prev.setAttribute('aria-disabled', String(atMin()));
    next.disabled = atMax();
    next.setAttribute('aria-disabled', String(atMax()));
    const isThisWeek = !!(todayMon && monday === todayMon);
    todaytag.style.display = isThisWeek ? '' : 'none';
    todaytag.setAttribute('aria-hidden', String(!isThisWeek));
  }

  function step(days: number, guard: () => boolean) {
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
  { value: 'day', label: t('toolbar.mode.day') },
  { value: 'pool', label: t('toolbar.mode.pool') },
];
const GENDER_ITEMS = [
  { value: '', label: t('toolbar.gender.any') },
  { value: 'female', label: t('toolbar.gender.female') },
  { value: 'male', label: t('toolbar.gender.male') },
  { value: 'diverse', label: t('toolbar.gender.diverse') },
];
// Age chips carry a REPRESENTATIVE age for the range (plan Part 2), '' = unset.
export const DEFAULT_AGE_CHIPS = [
  { value: '', label: t('toolbar.age.any') },
  { value: '8', label: t('toolbar.age.child') },
  { value: '16', label: t('toolbar.age.teen') },
  { value: '34', label: t('toolbar.age.adult') },
  { value: '70', label: t('toolbar.age.senior') },
];
const BUSYNESS_REASON = t('toolbar.busynessReason');

// A labelled field wrapper so controls read (and stack full-width on a phone).
function field(doc: Doc, caption: string | null, control: El, key?: string): El {
  const wrap = doc.createElement('div');
  // The modifier lets a surface hide a field it owns by other means — the phone drawer
  // hides `--view` and `--context` because the day strip IS the date control there, and
  // two date controls over one FilterState is how the chosen day got silently reset.
  wrap.className = key ? `toolbar__field toolbar__field--${key}` : 'toolbar__field';
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
export function createFilterToolbar<T extends El>(
  el: T,
  opts: { props?: ToolbarProps; onChange?: (f: FilterState) => void } = {},
) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const props = opts.props || {};
  const onChange = opts.onChange;
  const pools = props.pools || [];
  const places = props.places || [];
  const ages = props.ages || DEFAULT_AGE_CHIPS;
  const bounds = props.dateBounds || {};

  let filter = createFilterState(props.filter || {});

  el.classList.add('toolbar');
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', t('toolbar.label'));

  function emit() {
    if (onChange) onChange(filter);
  }
  function update(patch: Record<string, unknown>) {
    filter = merge(filter, patch);
    emit();
  }

  // --- mode Day/Pool (the pivot) ---
  const mode = createSegmentedControl(doc.createElement('div'), {
    props: { items: MODE_ITEMS, selected: filter.mode, variant: 'mode', label: t('toolbar.viewMode') },
    onChange: (v: string) => setMode(v as FilterState['mode']),
  });

  // --- context slot: DateStepper (Day) ↔ pool Combobox (Pool) ---
  const contextSlot = doc.createElement('div');
  contextSlot.className = 'toolbar__context';
  let contextKind: string | null = null;
  let contextControl: { el: El; [k: string]: unknown } | null = null;
  let weekControl: { el: El; readonly value: string } | null = null;

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
          label: t('date.selectedWeek'),
        },
        onChange: (mondayIso) => update({ date: mondayIso }),
      });
      const comboHost = doc.createElement('div');
      contextSlot.appendChild(comboHost);
      contextControl = createCombobox(comboHost, {
        props: {
          options: pools,
          value: filter.selectedPool?.id ?? null,
          label: t('toolbar.pool'),
          placeholder: t('toolbar.searchPool'),
        },
        onChange: (value: string) => {
          const opt = pools.find((p) => p.value === value) || null;
          update({ selectedPool: opt ? { id: opt.value, name: opt.label } : null });
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
          label: t('date.selectedDay'),
        },
        onChange: (iso) => update({ date: iso }),
      });
    }
  }

  function setMode(v: FilterState['mode']) {
    if (v === filter.mode) return;
    filter = merge(filter, { mode: v });
    renderContext();
    emit();
  }

  // --- place ---
  const place = createPlaceTypeahead(doc.createElement('div'), {
    props: { presets: places, label: t('toolbar.near'), placeholder: t('toolbar.wherefrom') },
    onChange: ({ lat, lon, label }: { lat: number; lon: number; label: string }) =>
      update({ place: { lat, lon, label } }),
  });

  // --- gender ---
  const gender = createSegmentedControl(doc.createElement('div'), {
    props: { items: GENDER_ITEMS, selected: filter.gender || '', label: t('toolbar.gender') },
    onChange: (v: string) => update({ gender: v }),
  });

  // --- age chips ---
  const age = createChipGroup(doc.createElement('div'), {
    props: {
      items: ages,
      selected: filter.age != null ? String(filter.age) : '',
      label: t('toolbar.age'),
    },
    onChange: (v: string) => update({ age: v === '' ? null : Number(v) }),
  });

  // --- lap-only ---
  const lap = createToggle(doc.createElement('div'), {
    props: { checked: !!filter.lapOnly, label: t('toolbar.lapOnly') },
    onChange: (checked: boolean) => update({ lapOnly: checked }),
  });

  // --- busyness (DISABLED — no data source yet; the honesty invariant made visible) ---
  const busyness = createToggle(doc.createElement('div'), {
    props: { checked: false, disabled: true, label: t('toolbar.busyness'), reason: BUSYNESS_REASON },
  });

  // Assemble the strip.
  renderContext();
  el.appendChild(field(doc, t('toolbar.view'), mode.el, 'view'));
  el.appendChild(field(doc, null, contextSlot, 'context'));
  el.appendChild(field(doc, t('toolbar.near'), place.el, 'near'));
  el.appendChild(field(doc, t('toolbar.gender'), gender.el, 'gender'));
  el.appendChild(field(doc, t('toolbar.age'), age.el, 'age'));
  el.appendChild(field(doc, null, lap.el, 'lap'));
  el.appendChild(field(doc, null, busyness.el, 'busyness'));

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
