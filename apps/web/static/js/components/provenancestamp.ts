// ProvenanceStamp — one calm line stating how far to trust the schedule:
// curated ("Official schedule") vs illustrative ("read from the pool's website"),
// with the source and the last-checked date. role=note.

import { formatDate } from '../datefmt.js';
import { asDoc, type El } from '../domtypes.js';
import { locale } from '../i18n.js';

export interface ProvenanceProps {
  curated?: boolean;
  source?: string;
  valid_as_of?: string;
}

export function createProvenanceStamp<T extends El>(
  el: T,
  { props = {} }: { props?: ProvenanceProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const curated = !!props.curated;
  el.classList.add('ui-provstamp', curated ? 'is-curated' : 'is-illustrative');
  el.setAttribute('role', 'note');

  const icon = doc.createElement('span');
  icon.classList.add('ui-provstamp__icon');
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = 'ⓘ';

  const text = doc.createElement('span');
  text.classList.add('ui-provstamp__text');
  const trust = curated
    ? 'Official schedule'
    : "Illustrative — read from the pool's website";
  const src = props.source ? ` · ${props.source}` : '';
  // A raw ISO date was shown here; render it in the viewer's locale.
  const when = props.valid_as_of
    ? ` · last checked ${formatDate(props.valid_as_of, locale())}`
    : '';
  text.textContent = `${trust}${src}${when}`;

  el.appendChild(icon);
  el.appendChild(text);
  return { el };
}
