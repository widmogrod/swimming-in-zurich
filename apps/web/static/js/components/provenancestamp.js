// ProvenanceStamp — one calm line stating how far to trust the schedule:
// curated ("Official schedule") vs illustrative ("read from the pool's website"),
// with the source and the last-checked date. role=note.

export function createProvenanceStamp(el, { props = {} } = {}) {
  const doc = el.ownerDocument || globalThis.document;
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
  const when = props.valid_as_of ? ` · last checked ${props.valid_as_of}` : '';
  text.textContent = `${trust}${src}${when}`;

  el.appendChild(icon);
  el.appendChild(text);
  return { el };
}
