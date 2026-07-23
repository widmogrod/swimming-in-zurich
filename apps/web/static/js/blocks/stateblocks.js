// stateblocks.js — the StateBlocks block (plan Part 3 §8).
//
// The three terminal empty-states, each VISUALLY DISTINCT so a blank never reads
// as "closed" (honesty invariant #1):
//   - closed-with-reason  : the pool is shut, and we say why.
//   - hours-not-listed     : we have no timetable (uncurated) — may well be open.
//   - no-pools             : nothing nearby matched at all.
//
// The SELECTION is pure (`stateForStatus`, `emptyState`) so it unit-tests headless;
// `createStateBlocks` renders each selected state into its own token-styled card.
// No colour, no hex — each state's tint is a token applied via its modifier class.

// The three state keys. Exported so callers name them, never string-drift.
export const STATE_CLOSED = 'closed';
export const STATE_UNLISTED = 'hours-not-listed';
export const STATE_NONE = 'no-pools';

// The plain-language copy for each state (kept honest: unknown ≠ closed).
const COPY = {
  [STATE_CLOSED]: {
    title: 'Closed',
    body: (detail) => (detail ? `Closed — ${detail}` : 'Closed for now.'),
  },
  [STATE_UNLISTED]: {
    title: 'Hours not listed yet',
    body: () =>
      'We don’t have this pool’s timetable yet — it may well be open. This is not the same as closed.',
  },
  [STATE_NONE]: {
    title: 'No pools nearby',
    body: () => 'Nothing matched here — try a wider area or a different day. Not the same as closed.',
  },
};

/**
 * stateForStatus(status) → STATE_CLOSED | STATE_UNLISTED | null.
 * Maps a `/swim` StatusOut to its terminal-state key; anything unknown → null.
 * @param {{status:string}} status a StatusOut (`{ facility, status, detail }`).
 */
export function stateForStatus(status) {
  if (!status) return null;
  if (status.status === 'closed') return STATE_CLOSED;
  if (status.status === 'uncurated') return STATE_UNLISTED;
  return null;
}

/**
 * emptyState(answer) → STATE_NONE when a `/swim` answer carries neither options
 * NOR statuses (a truly empty result), else null. A result WITH statuses is not
 * "no pools" — those pools render as their own closed/unlisted blocks.
 */
export function emptyState(answer) {
  const opts = (answer && answer.options) || [];
  const st = (answer && answer.statuses) || [];
  return opts.length === 0 && st.length === 0 ? STATE_NONE : null;
}

// One state card: a heading + a plain body, tagged with its state modifier class
// (`.stateblock--closed` / `--hours-not-listed` / `--no-pools`) so each reads
// distinctly. `facility` is prepended to the heading when present.
function stateCard(doc, key, { facility, detail } = {}) {
  const copy = COPY[key];
  const card = doc.createElement('div');
  card.className = `stateblock stateblock--${key}`;
  card.setAttribute('role', 'note');

  const head = doc.createElement('div');
  head.className = 'stateblock__title';
  head.textContent = facility ? `${facility} — ${copy.title}` : copy.title;

  const body = doc.createElement('p');
  body.className = 'stateblock__body';
  body.textContent = copy.body(detail);

  card.appendChild(head);
  card.appendChild(body);
  return card;
}

/**
 * createStateBlocks(el, opts) — render the empty/terminal states for a `/swim`
 * answer into `el`. Renders one block per closed / uncurated status (each named),
 * or a single no-pools block when the answer is entirely empty. Returns the keys
 * rendered (for tests / callers). `update(answer)` re-renders.
 * @param {object} opts.answer a `/swim` AnswerOut.
 */
export function createStateBlocks(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  el.classList.add('stateblocks');

  function update(answer) {
    el.textContent = '';
    const rendered = [];
    const none = emptyState(answer);
    if (none) {
      el.appendChild(stateCard(doc, none));
      rendered.push(none);
      return rendered;
    }
    for (const status of (answer && answer.statuses) || []) {
      const key = stateForStatus(status);
      if (!key) continue;
      el.appendChild(stateCard(doc, key, { facility: status.facility, detail: status.detail }));
      rendered.push(key);
    }
    return rendered;
  }

  const keys = update(opts.answer || { options: [], statuses: [] });
  return { el, update, keys };
}
