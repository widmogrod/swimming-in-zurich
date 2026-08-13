// LengthLanesBadge — basin physicals: "25 m · 6 lanes". Lanes render only when
// known (honest degrade, never a faked N). With no length at all the badge
// degrades to a plain "Teaching pool" label rather than fabricating a size.

import { asDoc, type El } from '../domtypes.js';
import { t } from '../i18n.js';

export interface LengthLanesProps {
  length_m?: number | null;
  lanes?: number | null;
  [k: string]: unknown;
}

export function createLengthLanesBadge<T extends El>(
  el: T,
  { props = {} }: { props?: LengthLanesProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  el.classList.add('ui-lenlanes');
  el.setAttribute('role', 'group');

  const lengthM = props.length_m != null ? props.length_m : props.lengthM;
  const lanes = props.lanes != null ? props.lanes : null;

  if (lengthM == null) {
    el.classList.add('is-degraded');
    const degrade = doc.createElement('span');
    degrade.classList.add('ui-lenlanes__degrade');
    degrade.textContent = String(props.degradeLabel ?? t('badge.teachingPool'));
    el.setAttribute('aria-label', degrade.textContent);
    el.appendChild(degrade);
    return { el };
  }

  const len = doc.createElement('span');
  len.classList.add('ui-lenlanes__len', 'tnum');
  len.textContent = `${lengthM} m`;
  el.appendChild(len);

  if (lanes != null) {
    const laneWord = t('basin.laneCount', { count: lanes });
    const lanesEl = doc.createElement('span');
    lanesEl.classList.add('ui-lenlanes__lanes', 'tnum');
    lanesEl.textContent = laneWord;
    el.appendChild(lanesEl);
    el.setAttribute('aria-label', `${lengthM} metre pool, ${laneWord}`);
  } else {
    el.setAttribute('aria-label', `${lengthM} metre pool`);
  }
  return { el };
}
