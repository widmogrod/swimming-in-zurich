// EligibilityBadge — ✓ in / ? check / ✕ not-for-you. Uses the MUTED --badge-*
// tokens (green / gold / grey), NEVER alarm red, and ? is a DISTINCT mark and
// colour from ✕ (they are never merged). role=img with the reason as the label /
// title. `variant: 'tag'` renders the filled board-row pill.

const ELIG = {
  in: { word: "You're in", cls: 'is-in', mark: '✓' },
  chk: { word: 'Check', cls: 'is-chk', mark: '?' },
  no: { word: 'Not for you', cls: 'is-no', mark: '✕' },
};

export function createEligibilityBadge(el, { props = {} } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const e = ELIG[props.state] || ELIG.chk;
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
