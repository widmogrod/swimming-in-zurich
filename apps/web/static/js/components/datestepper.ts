// DateStepper — ‹ / › around an absolute, tabular day label ("Thu 23 Jul").
// value/min/max are ISO dates (YYYY-MM-DD); the nav buttons carry explicit
// labels and disable (aria-disabled) at the bounds. A `today` match shows the
// TODAY tag. Absolute dates only — never "in 2 days".

// The hardcoded DAYS/MONTHS tables that used to live here are gone. Weekday and month
// names come from `Intl` per locale: Polish takes a GENITIVE month (`23 lipca`, never
// `23 lipiec`) and lowercases both, which no lookup table can express.
import { formatDay, shiftIso } from '../datefmt.js';
import { asDoc, type El } from '../domtypes.js';
import { locale } from '../i18n.js';

/** formatLabel('2026-07-23') → 'Thu, 23 Jul' in `en`. Locale-aware; pure. */
export function formatLabel(iso: string): string {
  return formatDay(iso, locale());
}

/** shiftDate('2026-07-23', 1) → '2026-07-24'. Pure; unit-tested directly. */
export const shiftDate = shiftIso;

export interface DateStepperProps {
  value?: string;
  min?: string | null;
  max?: string | null;
  today?: string | null;
  label?: string;
}

export interface DateStepperOpts {
  props?: DateStepperProps;
  onChange?: (iso: string) => void;
}

export function createDateStepper<T extends El>(
  el: T,
  { props = {}, onChange }: DateStepperOpts = {},
): { el: T; readonly value: string } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  let value = props.value ?? '';
  const min = props.min || null;
  const max = props.max || null;
  const today = props.today || null;

  el.classList.add('ui-datestepper');
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', props.label || 'Selected day');

  const prev = doc.createElement('button');
  prev.setAttribute('type', 'button');
  prev.classList.add('ui-datestepper__nav');
  prev.setAttribute('aria-label', 'Previous day');
  prev.textContent = '‹';

  const labelEl = doc.createElement('span');
  labelEl.classList.add('ui-datestepper__label', 'tnum');
  labelEl.setAttribute('aria-live', 'polite');

  const todaytag = doc.createElement('span');
  todaytag.classList.add('ui-datestepper__today');
  todaytag.textContent = 'Today';

  const next = doc.createElement('button');
  next.setAttribute('type', 'button');
  next.classList.add('ui-datestepper__nav');
  next.setAttribute('aria-label', 'Next day');
  next.textContent = '›';

  const atMin = () => !!(min && value <= min);
  const atMax = () => !!(max && value >= max);

  function render() {
    labelEl.textContent = formatLabel(value);
    prev.disabled = atMin();
    prev.setAttribute('aria-disabled', String(atMin()));
    next.disabled = atMax();
    next.setAttribute('aria-disabled', String(atMax()));
    const isToday = !!(today && value === today);
    todaytag.style.display = isToday ? '' : 'none';
    todaytag.setAttribute('aria-hidden', String(!isToday));
  }

  function step(days: number, guard: () => boolean) {
    if (guard()) return;
    value = shiftDate(value, days);
    render();
    if (onChange) onChange(value);
  }

  prev.addEventListener('click', () => step(-1, atMin));
  next.addEventListener('click', () => step(1, atMax));

  el.appendChild(prev);
  el.appendChild(labelEl);
  el.appendChild(todaytag);
  el.appendChild(next);
  render();

  return {
    el,
    get value() {
      return value;
    },
  };
}
