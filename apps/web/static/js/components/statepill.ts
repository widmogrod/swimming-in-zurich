// StatePill — one of the FOUR never-merged availability states, as a coloured
// dot + a word (never opacity-only, never colour-only). role=status.

import { asDoc, type El } from '../domtypes.js';

const STATES = {
  open: { label: 'Open', cls: 'is-open' },
  'opens-later': { label: 'Opens later', cls: 'is-later' },
  closed: { label: 'Closed', cls: 'is-closed' },
  unknown: { label: 'Hours not listed', cls: 'is-unknown' },
};

export interface StatePillProps {
  state?: string;
  label?: string;
  [k: string]: unknown;
}

export function createStatePill<T extends El>(
  el: T,
  { props = {} }: { props?: StatePillProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const state =
    (STATES as Record<string, (typeof STATES)['unknown']>)[props.state ?? ''] ??
    STATES.unknown;
  el.classList.add('ui-statepill', state.cls);
  el.setAttribute('role', 'status');

  const dot = doc.createElement('span');
  dot.classList.add('ui-statepill__dot');
  dot.setAttribute('aria-hidden', 'true');

  const word = doc.createElement('span');
  word.classList.add('ui-statepill__word');
  word.textContent = props.label || state.label;

  el.appendChild(dot);
  el.appendChild(word);
  return { el };
}
