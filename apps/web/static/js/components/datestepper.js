// DateStepper — ‹ / › around an absolute, tabular day label ("Thu 23 Jul").
// value/min/max are ISO dates (YYYY-MM-DD); the nav buttons carry explicit
// labels and disable (aria-disabled) at the bounds. A `today` match shows the
// TODAY tag. Absolute dates only — never "in 2 days".

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

// Parse an ISO date as UTC midnight, so arithmetic and toISOString() never drift
// by a day in a positive-offset timezone (the label is date-only, not a moment).
function parseUtc(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** formatLabel('2026-07-23') → 'Thu 23 Jul'. Pure; unit-tested directly. */
export function formatLabel(iso) {
  const d = parseUtc(iso);
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** shiftDate('2026-07-23', 1) → '2026-07-24'. Pure; unit-tested directly. */
export function shiftDate(iso, days) {
  const d = parseUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function createDateStepper(el, { props = {}, onChange } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  let value = props.value;
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

  function step(days, guard) {
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
