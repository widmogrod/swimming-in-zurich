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
import { asDoc, type Doc, type El } from '../domtypes.js';
import { t } from '../i18n.js';
import { closureLabel } from './board.js';

export const STATE_CLOSED = 'closed';
export const STATE_UNLISTED = 'hours-not-listed';
export const STATE_NONE = 'no-pools';

/** A `/swim` status row, read structurally. */
export interface StatusLike {
  facility?: string;
  status?: string;
  closure_code?: string | null;
  detail_params?: Record<string, string>;
}

export interface AnswerLike {
  options?: unknown[];
  statuses?: StatusLike[];
}

// The plain-language copy for each state (kept honest: unknown ≠ closed).
const COPY = {
  [STATE_CLOSED]: {
    title: t('state.closed.title'),
    body: (detail?: string | null) =>
      detail ? t('state.closed.body', { detail }) : t('state.closed.bodyNoReason'),
  },
  [STATE_UNLISTED]: {
    title: t('state.unlisted.title'),
    body: () => t('state.unlisted.body'),
  },
  [STATE_NONE]: {
    title: t('state.none.title'),
    body: () => 'Nothing matched here — try a wider area or a different day. Not the same as closed.',
  },
};

/**
 * stateForStatus(status) → STATE_CLOSED | STATE_UNLISTED | null.
 * Maps a `/swim` StatusOut to its terminal-state key; anything unknown → null.
 * @param {{status:string}} status a StatusOut (`{ facility, status, detail }`).
 */
export function stateForStatus(
  status: StatusLike | null | undefined,
): string | null {
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
export function emptyState(answer: AnswerLike | null | undefined): string | null {
  const opts = (answer && answer.options) || [];
  const st = (answer && answer.statuses) || [];
  return opts.length === 0 && st.length === 0 ? STATE_NONE : null;
}

// One state card: a heading + a plain body, tagged with its state modifier class
// (`.stateblock--closed` / `--hours-not-listed` / `--no-pools`) so each reads
// distinctly. `facility` is prepended to the heading when present.
function stateCard(
  doc: Doc,
  key: string,
  { facility, detail }: { facility?: string; detail?: string | null } = {},
): El {
  const copy = (COPY as Record<string, (typeof COPY)[typeof STATE_CLOSED]>)[key];
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

// One compact note summarising the N uncurated pools, instead of N identical cards.
// The pools themselves are named on the board above; this states the honesty fact once.
function unlistedSummaryCard(doc: Doc, count: number): El {
  const card = doc.createElement('div');
  card.className = `stateblock stateblock--${STATE_UNLISTED}`;
  card.setAttribute('role', 'note');
  const head = doc.createElement('div');
  head.className = 'stateblock__title';
  head.textContent = t('state.unlisted.summary', { count });
  const body = doc.createElement('p');
  body.className = 'stateblock__body';
  body.textContent =
    'We don’t have their timetables yet — they may well be open. This is not the same as closed. They’re listed on the board above.';
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
export function createStateBlocks<T extends El>(
  el: T,
  opts: { answer?: AnswerLike } = {},
) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  el.classList.add('stateblocks');

  function update(answer: AnswerLike) {
    el.textContent = '';
    const rendered: string[] = [];
    const none = emptyState(answer);
    if (none) {
      el.appendChild(stateCard(doc, none));
      rendered.push(none);
      return rendered;
    }
    const statuses = (answer && answer.statuses) || [];
    // Closed-with-reason: keep one named card per pool — there are few and each carries
    // its own reason (Sommerpause / Revision) worth stating.
    for (const status of statuses) {
      if (stateForStatus(status) !== STATE_CLOSED) continue;
      el.appendChild(
        stateCard(doc, STATE_CLOSED, {
          facility: status.facility,
          detail: closureLabel(status),
        }),
      );
      rendered.push(STATE_CLOSED);
    }
    // Hours-not-listed: collapse the (many, identical) uncurated pools into ONE count note.
    // They are already listed BY NAME on the board above as dotted "hours not listed" rows;
    // repeating the same paragraph 50+ times here is noise, not honesty.
    const unlisted = statuses.filter(
      (s: StatusLike) => stateForStatus(s) === STATE_UNLISTED,
    ).length;
    if (unlisted) {
      el.appendChild(unlistedSummaryCard(doc, unlisted));
      rendered.push(STATE_UNLISTED);
    }
    return rendered;
  }

  const keys = update(opts.answer || { options: [], statuses: [] });
  return { el, update, keys };
}
