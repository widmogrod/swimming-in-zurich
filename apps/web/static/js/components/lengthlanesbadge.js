// LengthLanesBadge — basin physicals: "25 m · 6 lanes". Lanes render only when
// known (honest degrade, never a faked N). With no length at all the badge
// degrades to a plain "Teaching pool" label rather than fabricating a size.

export function createLengthLanesBadge(el, { props = {} } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  el.classList.add('ui-lenlanes');
  el.setAttribute('role', 'group');

  const lengthM = props.length_m != null ? props.length_m : props.lengthM;
  const lanes = props.lanes != null ? props.lanes : null;

  if (lengthM == null) {
    el.classList.add('is-degraded');
    const degrade = doc.createElement('span');
    degrade.classList.add('ui-lenlanes__degrade');
    degrade.textContent = props.degradeLabel || 'Teaching pool';
    el.setAttribute('aria-label', degrade.textContent);
    el.appendChild(degrade);
    return { el };
  }

  const len = doc.createElement('span');
  len.classList.add('ui-lenlanes__len', 'tnum');
  len.textContent = `${lengthM} m`;
  el.appendChild(len);

  if (lanes != null) {
    const laneWord = `${lanes} lane${lanes === 1 ? '' : 's'}`;
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
