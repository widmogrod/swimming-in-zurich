// legend.js — the BoardLegend block (plan Part 3 §7).
//
// The metro-style key that decodes the board: the access-family swatches, the
// three never-merged terminal states (open / closed-with-reason / hours-not-listed),
// the eligibility key (✓/?/✕), and the honesty note about ribbon thickness.
//
// The legend MODEL is pure data (`legendModel`) so it unit-tests headless; the
// swatch/badge hues are tokens applied via `.fam-*` and the eligibility badge
// classes — no colour, no hex lives here.

import { createEligibilityBadge } from '../components/eligibilitybadge.js';
import { ELIG_IN, ELIG_CHK, ELIG_NO } from '../eligibility.js';

// The honesty note is a constant so a test can pin it (the invariant can't be
// silently reworded to imply a busyness source that does not exist).
export const HONESTY_NOTE =
  'Ribbon thickness is today’s real public-lane split — not busyness, which has no source yet.';

// The eight access families (each maps to a `.fam-*` colour token) + their words.
const FAMILIES = [
  { family: 'public', label: 'Public swim' },
  { family: 'lane', label: 'Lane swim' },
  { family: 'family', label: 'Family time' },
  { family: 'women', label: 'Women only' },
  { family: 'seniors', label: 'Seniors only' },
  { family: 'adults', label: 'Adults only' },
  { family: 'school', label: 'School reserved' },
  { family: 'club', label: 'Club reserved' },
];

// The three terminal states, each its own swatch class (never merged).
const STATES = [
  { key: 'open', label: 'Open (public lanes)' },
  { key: 'closed', label: 'Closed — with reason' },
  { key: 'unknown', label: 'Hours not listed yet' },
];

// The eligibility key — ? is DISTINCT from ✕ (never merged), and colours are the
// muted badge tokens (never alarm red).
const ELIGIBILITY = [
  { state: ELIG_IN, label: 'You’re in' },
  { state: ELIG_CHK, label: 'Check with the venue' },
  { state: ELIG_NO, label: 'Not for you' },
];

/**
 * legendModel() → the pure legend data (families, states, eligibility, note).
 * The renderer walks this; a test asserts completeness without touching the DOM.
 */
export function legendModel() {
  return {
    families: FAMILIES.slice(),
    states: STATES.slice(),
    eligibility: ELIGIBILITY.slice(),
    note: HONESTY_NOTE,
  };
}

function swatchRow(doc, swatchClass, label) {
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

function group(doc, title) {
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
export function createBoardLegend(el) {
  const doc = el.ownerDocument || globalThis.document;
  const model = legendModel();
  el.classList.add('legend');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', 'Board legend');

  // Access families.
  const fams = group(doc, 'Session type');
  for (const f of model.families) fams.appendChild(swatchRow(doc, `fam-${f.family}`, f.label));
  el.appendChild(fams);

  // The three terminal states.
  const states = group(doc, 'Availability');
  for (const s of model.states) {
    states.appendChild(swatchRow(doc, `legend__state legend__state--${s.key}`, s.label));
  }
  el.appendChild(states);

  // Eligibility key — reuse the EligibilityBadge primitive so the key can't drift.
  const elig = group(doc, 'For you');
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
