// phonebar.ts — the phone's context bar: a day strip over a pinned filter summary.
//
// Two rules from the prototype bench are load-bearing here:
//
//   1. Only ONE thing is pinned. Two `position:sticky` bars at `top:0` stack, and the
//      taller one paints over the other — the day strip hid the filter row outright. The
//      summary wins the pin because it is the state you cannot afford to lose; the day
//      strip scrolls away, and the chosen day still rides in the summary as a tag.
//   2. "Now" is only true of TODAY. On any other day the lead tag counts the day, or the
//      bar reads "0 open to you now" for a Saturday you are planning ahead for.
//
// The summary row IS the disclosure trigger (there is no separate button), and it
// auto-dismisses on scroll — an open drawer would otherwise own the whole viewport.

import { asDoc, type Doc, type El } from '../domtypes.js';
import { formatDay, shiftIso } from '../datefmt.js';
import { locale, t } from '../i18n.js';

/** How many days the strip offers, starting one day back so "yesterday" is reachable. */
export const STRIP_BACK = 1;
export const STRIP_FORWARD = 6;

export interface PhoneBarProps {
  /** ISO date currently shown. */
  date: string;
  /** ISO date for "today" — the strip marks it, and only it may say "now". */
  today: string;
  /** Summary tags after the lead count, already-formatted whole strings. */
  tags?: string[];
  openToYou?: number;
}

export interface PhoneBarOpts {
  props?: PhoneBarProps;
  onDate?: (iso: string) => void;
  onToggleFilters?: (open: boolean) => void;
}

/** stripDates(today, back, forward) — the ISO dates the strip offers. Pure. */
export function stripDates(today: string, back = STRIP_BACK, forward = STRIP_FORWARD): string[] {
  const out: string[] = [];
  for (let i = -back; i <= forward; i += 1) out.push(shiftIso(today, i));
  return out;
}

/**
 * leadTag(count, date, today) — the summary's first tag.
 *
 * Split out because it carries rule 2 above and is worth asserting directly.
 */
export function leadTag(count: number, date: string, today: string): string {
  if (date === today) return t('mobile.openToYou', { count });
  return t('mobile.openToYouOn', { count, day: formatDay(date, locale()) });
}

function newEl(doc: Doc, tag: string, cls?: string, text?: string): El {
  const n = doc.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function createPhoneBar<T extends El>(el: T, opts: PhoneBarOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const props = opts.props ?? { date: '', today: '' };
  let date = props.date;
  let filtersOpen = false;

  el.classList.add('pbar');

  // --- day strip (scrolls away) ---
  const strip = newEl(doc, 'div', 'pbar__days');
  strip.setAttribute('role', 'tablist');
  const dayButtons: El[] = [];

  function renderStrip(): void {
    strip.textContent = '';
    dayButtons.length = 0;
    for (const iso of stripDates(props.today)) {
      const b = newEl(doc, 'button', 'pbar__day');
      b.setAttribute('type', 'button');
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(iso === date));
      if (iso === props.today) b.classList.add('is-today');
      if (iso === date) b.classList.add('is-sel');
      const label = iso === props.today ? t('mobile.today') : formatDay(iso, locale());
      b.appendChild(newEl(doc, 'span', 'pbar__dow', label));
      b.appendChild(newEl(doc, 'span', 'pbar__num tnum', String(Number(iso.slice(8, 10)))));
      b.dataset.date = iso;
      b.addEventListener('click', () => {
        date = iso;
        renderStrip();
        if (opts.onDate) opts.onDate(iso);
      });
      strip.appendChild(b);
      dayButtons.push(b);
    }
  }

  // --- filter summary (the pinned one) ---
  const summary = newEl(doc, 'button', 'pbar__summary');
  summary.setAttribute('type', 'button');
  summary.setAttribute('aria-expanded', 'false');
  const tagHost = newEl(doc, 'span', 'pbar__tags');
  const caret = newEl(doc, 'span', 'pbar__caret');
  caret.setAttribute('aria-hidden', 'true');
  summary.appendChild(tagHost);
  summary.appendChild(caret);

  function renderTags(): void {
    tagHost.textContent = '';
    const lead = newEl(
      doc,
      'span',
      'pbar__tag pbar__tag--lead',
      leadTag(props.openToYou ?? 0, date, props.today),
    );
    tagHost.appendChild(lead);
    for (const tag of props.tags ?? []) {
      tagHost.appendChild(newEl(doc, 'span', 'pbar__tag', tag));
    }
  }

  summary.addEventListener('click', () => {
    setFiltersOpen(!filtersOpen);
  });

  /** Dismiss on scroll: an open drawer owns the whole viewport on a phone. */
  function closeOnScroll(): void {
    if (filtersOpen) setFiltersOpen(false);
  }

  function setFiltersOpen(open: boolean): void {
    filtersOpen = open;
    el.classList.toggle('is-filtersopen', open);
    summary.setAttribute('aria-expanded', String(open));
    if (opts.onToggleFilters) opts.onToggleFilters(open);
  }

  // The drawer the filters live in. A plain show/hide, NOT an animated height: a
  // `grid-template-rows` transition wedges at its START value in a throttled frame and
  // would leave the drawer shut forever, which is worse than having no animation.
  const drawer = newEl(doc, 'div', 'pbar__drawer');

  el.appendChild(strip);
  el.appendChild(summary);
  el.appendChild(drawer);
  renderStrip();
  renderTags();

  return {
    closeOnScroll,
    el,
    strip,
    summary,
    drawer,
    get dayButtons() {
      return dayButtons;
    },
    get filtersOpen() {
      return filtersOpen;
    },
    setFiltersOpen,
    setDate(iso: string): void {
      date = iso;
      renderStrip();
      renderTags();
    },
    setSummary(next: { tags?: string[]; openToYou?: number }): void {
      if (next.tags) props.tags = next.tags;
      if (next.openToYou != null) props.openToYou = next.openToYou;
      renderTags();
    },
  };
}
