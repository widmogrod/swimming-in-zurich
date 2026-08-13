// legend.js — the BoardLegend block (plan Part 3 §7).
//
// The metro-style key that decodes the board: the access-family swatches, the
// three never-merged terminal states (open / closed-with-reason / hours-not-listed),
// the eligibility key (✓/?/✕), and the honesty note about ribbon thickness.
//
// The legend MODEL is pure data (`legendModel`) so it unit-tests headless; the
// swatch/badge hues are tokens applied via `.fam-*` and the eligibility badge
// classes — no colour, no hex lives here.

import { asDoc, type Doc, type El } from '../domtypes.js';
import { t } from '../i18n.js';
import { createEligibilityBadge } from '../components/eligibilitybadge.js';
import { ELIG_IN, ELIG_CHK, ELIG_NO } from '../eligibility.js';

// The honesty note is a constant so a test can pin it (the invariant can't be
// silently reworded to imply a busyness source that does not exist).
/** The honesty note. Now a CATALOG lookup, but still exported as a constant so the
 *  invariant test can pin it: it must never be reworded to imply a busyness source that
 *  does not exist. */
export const HONESTY_NOTE = t('legend.honestyNote');

// The eleven access families (each maps to a `.fam-*` colour token) + their words.
// Key-only: the label is resolved from the catalog at render, so the legend is
// translatable without the model changing shape (legend.test asserts on KEYS).
const FAMILIES = [
  { family: 'public', label: t('access.public') },
  { family: 'lane', label: t('access.lane') },
  { family: 'family', label: t('access.family') },
  { family: 'women', label: t('access.women') },
  { family: 'seniors', label: t('access.seniors') },
  { family: 'adults', label: t('access.adults') },
  { family: 'school', label: t('access.school') },
  { family: 'club', label: t('access.club') },
  { family: 'girls', label: t('access.girls') },
  { family: 'diverse', label: t('access.genderDiverse') },
  { family: 'accompanied', label: t('access.accompanied') },
];

// The three terminal states, each its own swatch class (never merged).
const STATES = [
  { key: 'open', label: t('legend.state.open') },
  { key: 'closed', label: t('legend.state.closed') },
  { key: 'unknown', label: t('legend.state.unknown') },
];

// The lane stack's key (lane-stack-board S4). A row whose basin has a published
// Belegungsplan is drawn as one hairline sub-row per lane, so the board now carries an
// encoding the original three groups do not decode: which lane, whose, and when the water
// is freest.
//
// The fourth row is the honesty floor (invariant I5): most pools publish no lane split at
// all, and their hatched bar must read as ITS OWN state — not as a stack with nothing free.
const LANE_STACK = [
  { key: 'public', label: t('legend.lane.public') },
  { key: 'reserved', label: t('legend.lane.reserved') },
  { key: 'best', label: t('legend.lane.best') },
  { key: 'unpublished', label: t('legend.lane.unpublished') },
];

// The eligibility key — ? is DISTINCT from ✕ (never merged), and colours are the
// muted badge tokens (never alarm red).
const ELIGIBILITY = [
  { state: ELIG_IN, label: t('elig.in') },
  { state: ELIG_CHK, label: t('elig.chk') },
  { state: ELIG_NO, label: t('elig.no') },
];

/**
 * legendModel() → the pure legend data (families, states, eligibility, note).
 * The renderer walks this; a test asserts completeness without touching the DOM.
 */
export function legendModel() {
  return {
    families: FAMILIES.slice(),
    states: STATES.slice(),
    laneStack: LANE_STACK.slice(),
    eligibility: ELIGIBILITY.slice(),
    note: HONESTY_NOTE,
  };
}

function swatchRow(doc: Doc, swatchClass: string, label: string): El {
  const row = doc.createElement('div');
  row.className = 'legend__row';
  const sw = doc.createElement('span');
  sw.className = `legend__swatch ${swatchClass}`;
  sw.setAttribute('aria-hidden', 'true');
  const text = doc.createElement('span');
  text.className = 'legend__label';
  text.textContent = label;
  row.appendChild(sw);
  row.appendChild(text);
  return row;
}

function group(doc: Doc, title: string): El {
  const g = doc.createElement('div');
  g.className = 'legend__group';
  const h = doc.createElement('div');
  h.className = 'legend__grouptitle';
  h.textContent = title;
  g.appendChild(h);
  return g;
}

/**
 * createBoardLegend(el, opts) — render the legend into `el` from `legendModel()`.
 * @returns {{el}}
 */
export function createBoardLegend<T extends El>(el: T): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const model = legendModel();
  el.classList.add('legend');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', t('legend.label'));

  // Access families.
  const fams = group(doc, t('legend.group.sessionType'));
  for (const f of model.families) fams.appendChild(swatchRow(doc, `fam-${f.family}`, f.label));
  el.appendChild(fams);

  // The three terminal states.
  const states = group(doc, t('legend.group.availability'));
  for (const s of model.states) {
    states.appendChild(swatchRow(doc, `legend__state legend__state--${s.key}`, s.label));
  }
  el.appendChild(states);

  // The lane stack — the encoding a row with a published plan actually paints.
  const lanes = group(doc, t('legend.group.laneStack'));
  for (const l of model.laneStack) {
    lanes.appendChild(swatchRow(doc, `legend__lane legend__lane--${l.key}`, l.label));
  }
  el.appendChild(lanes);

  // Eligibility key — reuse the EligibilityBadge primitive so the key can't drift.
  const elig = group(doc, t('legend.group.forYou'));
  for (const e of model.eligibility) {
    const row = doc.createElement('div');
    row.className = 'legend__row';
    const badgeHost = doc.createElement('span');
    createEligibilityBadge(badgeHost, { props: { state: e.state } });
    const text = doc.createElement('span');
    text.className = 'legend__label';
    text.textContent = e.label;
    row.appendChild(badgeHost);
    row.appendChild(text);
    elig.appendChild(row);
  }
  el.appendChild(elig);

  // Honesty note.
  const note = doc.createElement('p');
  note.className = 'legend__note';
  note.textContent = model.note;
  el.appendChild(note);

  return { el };
}
