// ProvenanceStamp — one calm line stating how far to trust the schedule, with the source
// and the last-checked date. role=note.
//
// It reads the API's three-state `freshness`, the SAME signal `/pools` rows and the board's
// ghost states use — not the old `curated` boolean. Since every schedule is now scraped from
// the operator's own page, `curated` is False for every pool, so the stamp called a real
// official timetable "illustrative" while the row beside it read `scraped`.

import { formatDate } from '../datefmt.js';
import { asDoc, type El } from '../domtypes.js';
import { locale, t, type MessageKey } from '../i18n.js';

export interface ProvenanceProps {
  /** The API's `freshness`: 'scraped' | 'awaiting_scrape' | 'no_source'. An absent/unknown
   *  value is treated as schedule-less rather than as an official schedule — the stamp never
   *  claims more trust than it was handed. */
  freshness?: string;
  source?: string;
  valid_as_of?: string;
}

const TRUST: Readonly<Record<string, MessageKey>> = {
  scraped: 'prov.scraped',
  awaiting_scrape: 'prov.awaiting',
  no_source: 'prov.noSource',
};

export function createProvenanceStamp<T extends El>(
  el: T,
  { props = {} }: { props?: ProvenanceProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const scraped = props.freshness === 'scraped';
  // The class keeps its name: `is-illustrative` is the CSS hook for "this line is not a real
  // schedule" (it italicises), and both schedule-less states are exactly that.
  el.classList.add('ui-provstamp', scraped ? 'is-curated' : 'is-illustrative');
  el.setAttribute('role', 'note');

  const icon = doc.createElement('span');
  icon.classList.add('ui-provstamp__icon');
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = 'ⓘ';

  const text = doc.createElement('span');
  text.classList.add('ui-provstamp__text');
  const trust = t(TRUST[props.freshness ?? ''] ?? 'prov.noSource');
  // eslint-disable-next-line i18next/no-literal-string -- punctuation + a source name, not copy
  const src = props.source ? ` · ${props.source}` : '';
  // A raw ISO date was shown here; render it in the viewer's locale.
  const when = props.valid_as_of
    ? t('prov.lastChecked', { date: formatDate(props.valid_as_of, locale()) })
    : '';
  text.textContent = `${trust}${src}${when}`;

  el.appendChild(icon);
  el.appendChild(text);
  return { el };
}
