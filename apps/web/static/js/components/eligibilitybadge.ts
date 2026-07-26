// EligibilityBadge — ✓ in / ? check / ✕ not-for-you. Uses the MUTED --badge-*
// tokens (green / gold / grey), NEVER alarm red, and ? is a DISTINCT mark and
// colour from ✕ (they are never merged). role=img with the reason as the label /
// title. `variant: 'tag'` renders the filled board-row pill.

import { asDoc, type El } from '../domtypes.js';
import { t } from '../i18n.js';

const ELIG = {
  in: { word: t('elig.in'), cls: 'is-in', mark: '✓' },
  chk: { word: t('elig.chk.short'), cls: 'is-chk', mark: '?' },
  no: { word: t('elig.no'), cls: 'is-no', mark: '✕' },
};

export interface EligibilityBadgeProps {
  state?: string;
  reason?: string;
  variant?: string;
  [k: string]: unknown;
}

export function createEligibilityBadge<T extends El>(
  el: T,
  { props = {} }: { props?: EligibilityBadgeProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const e = (ELIG as Record<string, (typeof ELIG)['chk']>)[props.state ?? ''] ?? ELIG.chk;
  el.classList.add('ui-eligbadge', e.cls);
  if (props.variant === 'tag') el.classList.add('ui-eligbadge--tag');

  const reason = props.reason || e.word;
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', `${e.word}: ${reason}`);
  el.setAttribute('title', reason);

  const mark = doc.createElement('span');
  mark.classList.add('ui-eligbadge__mark');
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = e.mark;

  const word = doc.createElement('span');
  word.classList.add('ui-eligbadge__word');
  word.textContent = e.word;

  el.appendChild(mark);
  el.appendChild(word);
  return { el };
}
