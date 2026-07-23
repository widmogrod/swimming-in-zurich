// honesty.test.js — the load-bearing product invariants, asserted directly on the
// LIVE blocks (plan Risk #4: honesty invariants must not erode under refactor). These
// are GATES, not nice-to-haves. Four invariants:
//   1. unknown (uncurated) renders a DISTINCT state from closed (dotted ghost vs
//      dashed-with-reason — never merged).
//   2. the three terminal states (open / closed-with-reason / hours-not-listed) are
//      never merged.
//   3. Busyness renders "not available yet" (future) and is never faked.
//   4. eligibility ? (chk) is never merged with ✕ (no).

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { statusRibbon, ribbonsFor } from './ribbonmodel.js';
import { rowStatus } from './board.js';
import { legendModel, HONESTY_NOTE } from './legend.js';
import { eligForAccess, dayEligibility, ELIG_CHK, ELIG_NO, ELIG_IN } from '../eligibility.js';
import { basinFromPanel } from './cursor.js';
import { createDetailPanel } from './detailpanel.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));
const hasClass = (c) => (e) => e.classList.contains(c);

// --- Invariant 1: unknown (uncurated) ≠ closed ---------------------------------
test('invariant: uncurated renders a DISTINCT ghost, never merged into closed', () => {
  const closed = statusRibbon({ status: 'closed', facility: 'X', detail: 'Winterpause' });
  const ghost = statusRibbon({ status: 'uncurated', facility: 'Y', detail: null });

  // Closed = DASHED with its reason; uncurated = DOTTED ghost — different on every axis.
  assert.equal(closed.style, 'dashed');
  assert.equal(ghost.style, 'dotted');
  assert.notEqual(closed.style, ghost.style);
  assert.equal(closed.variant, 'closed');
  assert.equal(ghost.variant, 'ghost');
  assert.notEqual(closed.variant, ghost.variant);
  assert.equal(closed.family, 'closed');
  assert.equal(ghost.family, 'unknown'); // NOT 'closed'
  assert.notEqual(closed.family, ghost.family);
  // The closed ribbon carries a REASON; the ghost is not dressed as a closure.
  assert.equal(closed.detail, 'Winterpause');

  // Any non-closed status label falls back to the ghost, never to closed (honesty).
  assert.equal(statusRibbon({ status: 'weird', facility: 'Z' }).variant, 'ghost');
});

// --- Invariant 2: the three terminal states are never merged -------------------
test('invariant: rowStatus yields three DISTINCT terminal states', () => {
  const open = rowStatus({ options: [{}], statuses: [] });
  const closed = rowStatus({ options: [], statuses: [{ status: 'closed' }] });
  const unknown = rowStatus({ options: [], statuses: [{ status: 'uncurated' }] });
  assert.deepEqual([open, closed, unknown], ['open', 'closed', 'unknown']);
  assert.equal(new Set([open, closed, unknown]).size, 3); // none collapsed into another
});

test('invariant: a row with BOTH a closed and an uncurated status keeps them as separate ribbons', () => {
  const ribbons = ribbonsFor({
    options: [],
    statuses: [
      { status: 'closed', facility: 'A', detail: 'Renovation' },
      { status: 'uncurated', facility: 'A', detail: null },
    ],
  });
  const variants = ribbons.map((r) => r.variant).sort();
  assert.deepEqual(variants, ['closed', 'ghost']); // both survive, unmerged
});

test('invariant: the legend keys the three terminal states as three distinct swatches', () => {
  const keys = legendModel().states.map((s) => s.key);
  assert.deepEqual(keys, ['open', 'closed', 'unknown']);
  assert.equal(new Set(keys).size, 3);
});

// --- Invariant 3: busyness is future, never faked ------------------------------
test('invariant: the DetailPanel renders Busyness as "Not available yet" (never a number)', () => {
  const pool = load('pool_oerlikon.json');
  const basin = basinFromPanel(pool.lane_panels[0]);
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  createDetailPanel(el, { detail: pool, basin, timescale: ts, filter: { gender: '', age: null } });

  const facts = el.queryAll(hasClass('detail__fact'));
  const busyness = facts.find((f) => f.textContent.startsWith('Busyness'));
  assert.ok(busyness, 'a Busyness fact row must be present');
  assert.equal(busyness.textContent, 'BusynessNot available yet');
  // Never faked: no digit / percentage leaks into the busyness readout.
  assert.ok(!/[0-9]|%/.test(busyness.textContent), 'busyness must not carry a fabricated figure');
});

test('invariant: the honesty note says thickness is NOT busyness (no implied source)', () => {
  assert.match(HONESTY_NOTE, /not busyness/i);
  assert.match(HONESTY_NOTE, /no source yet/i);
});

// --- Invariant 4: ? (chk) is never merged with ✕ (no) --------------------------
test('invariant: chk and no are distinct states, and unset/diverse map to chk (never no)', () => {
  assert.notEqual(ELIG_CHK, ELIG_NO);
  // Women-only with an UNKNOWN viewer → ? (needs a human check), never ✕.
  assert.equal(eligForAccess('WomenOnly', '', null), ELIG_CHK);
  assert.equal(eligForAccess('WomenOnly', 'diverse', null), ELIG_CHK);
  // A real hard-no stays ✕ (male at a women-only session), proving chk ≠ a blanket pass.
  assert.equal(eligForAccess('WomenOnly', 'male', null), ELIG_NO);
  // Age-gated with unknown age → ? (never ✕ just because the age is missing).
  assert.equal(eligForAccess('AdultsOnly', '', null), ELIG_CHK);
});

test('invariant: dayEligibility never downgrades a ? row to ✕ (chk beats no)', () => {
  // A row whose only sessions are "check" is ?, crucially NOT ✕.
  assert.equal(dayEligibility([ELIG_CHK, ELIG_NO]), ELIG_CHK);
  assert.equal(dayEligibility([ELIG_NO, ELIG_NO]), ELIG_NO); // only an all-✕ row is ✕
  assert.equal(dayEligibility([ELIG_IN, ELIG_NO]), ELIG_IN); // any attendable → ✓
});
