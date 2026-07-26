import { expect, test } from 'vitest';
// honesty.test.js — the load-bearing product invariants, asserted directly on the
// LIVE blocks (plan Risk #4: honesty invariants must not erode under refactor). These
// are GATES, not nice-to-haves. Four invariants:
//   1. unknown (uncurated) renders a DISTINCT state from closed (dotted ghost vs
//      dashed-with-reason — never merged).
//   2. the three terminal states (open / closed-with-reason / hours-not-listed) are
//      never merged.
//   3. Busyness renders "not available yet" (future) and is never faked.
//   4. eligibility ? (chk) is never merged with ✕ (no).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import { must } from '../testutil.js';
import type { FakeElement } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { statusRibbon, ribbonsFor } from './ribbonmodel.js';
import { rowStatus } from './board.js';
import { legendModel, HONESTY_NOTE } from './legend.js';
import { eligForAccess, dayEligibility, ELIG_CHK, ELIG_NO, ELIG_IN } from '../eligibility.js';
import { basinFromPanel, type LanePanel } from './cursor.js';
import { createDetailPanel } from './detailpanel.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import type { FacilityDetail } from './detailpanel.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);

// --- Invariant 1: unknown (uncurated) ≠ closed ---------------------------------
test('invariant: uncurated renders a DISTINCT ghost, never merged into closed', () => {
  const closed = statusRibbon({ status: 'closed', facility: 'X', detail: 'Winterpause' });
  const ghost = statusRibbon({ status: 'uncurated', facility: 'Y', detail: null });

  // Closed = DASHED with its reason; uncurated = DOTTED ghost — different on every axis.
  expect(closed.style).toBe('dashed');
  expect(ghost.style).toBe('dotted');
  expect(closed.style).not.toBe(ghost.style);
  expect(closed.variant).toBe('closed');
  expect(ghost.variant).toBe('ghost');
  expect(closed.variant).not.toBe(ghost.variant);
  expect(closed.family).toBe('closed');
  expect(ghost.family).toBe('unknown'); // NOT 'closed'
  expect(closed.family).not.toBe(ghost.family);
  // The closed ribbon carries a REASON; the ghost is not dressed as a closure.
  expect(closed.detail).toBe('Winterpause');

  // Any non-closed status label falls back to the ghost, never to closed (honesty).
  expect(statusRibbon({ status: 'weird', facility: 'Z' }).variant).toBe('ghost');
});

// --- Invariant 2: the three terminal states are never merged -------------------
test('invariant: rowStatus yields three DISTINCT terminal states', () => {
  const open = rowStatus({ options: [{}], statuses: [] });
  const closed = rowStatus({ options: [], statuses: [{ status: 'closed' }] });
  const unknown = rowStatus({ options: [], statuses: [{ status: 'uncurated' }] });
  expect([open, closed, unknown]).toEqual(['open', 'closed', 'unknown']);
  expect(new Set([open, closed, unknown]).size).toBe(3); // none collapsed into another
});

test('invariant: a row with BOTH a closed and an uncurated status keeps them as separate ribbons', () => {
  const ribbons = ribbonsFor({
    options: [],
    statuses: [
      { status: 'closed', facility: 'A', detail: 'Renovation' },
      { status: 'uncurated', facility: 'A', detail: null },
    ],
  });
  const variants = ribbons.map((r) => (r as { variant?: string }).variant).sort();
  expect(variants).toEqual(['closed', 'ghost']); // both survive, unmerged
});

test('invariant: the legend keys the three terminal states as three distinct swatches', () => {
  const keys = legendModel().states.map((s) => s.key);
  expect(keys).toEqual(['open', 'closed', 'unknown']);
  expect(new Set(keys).size).toBe(3);
});

// --- Invariant 3: busyness is future, never faked ------------------------------
test('invariant: the DetailPanel renders Busyness as "Not available yet" (never a number)', () => {
  const pool = load<FacilityDetail & { lane_panels: unknown[] }>('pool_oerlikon.json');
  const basin = basinFromPanel(pool.lane_panels[0] as LanePanel);
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  createDetailPanel(el, { detail: pool, basin, timescale: ts, filter: { gender: '', age: null } });

  const facts = el.queryAll(hasClass('detail__fact'));
  const busyness = facts.find((f) => f.textContent.startsWith('Busyness'));
  expect(busyness).toBeTruthy();
  expect(must(busyness, 'Busyness row').textContent).toBe('BusynessNot available yet');
  // Never faked: no digit / percentage leaks into the busyness readout.
  expect(!/[0-9]|%/.test(must(busyness, 'Busyness row').textContent)).toBeTruthy();
});

test('invariant: the honesty note says thickness is NOT busyness (no implied source)', () => {
  expect(HONESTY_NOTE).toMatch(/not busyness/i);
  expect(HONESTY_NOTE).toMatch(/no source yet/i);
});

// --- Invariant 4: ? (chk) is never merged with ✕ (no) --------------------------
test('invariant: chk and no are distinct states, and unset/diverse map to chk (never no)', () => {
  expect(ELIG_CHK).not.toBe(ELIG_NO);
  // Women-only with an UNKNOWN viewer → ? (needs a human check), never ✕.
  expect(eligForAccess('WomenOnly', '', null)).toBe(ELIG_CHK);
  expect(eligForAccess('WomenOnly', 'diverse', null)).toBe(ELIG_CHK);
  // A real hard-no stays ✕ (male at a women-only session), proving chk ≠ a blanket pass.
  expect(eligForAccess('WomenOnly', 'male', null)).toBe(ELIG_NO);
  // Age-gated with unknown age → ? (never ✕ just because the age is missing).
  expect(eligForAccess('AdultsOnly', '', null)).toBe(ELIG_CHK);
});

test('invariant: dayEligibility never downgrades a ? row to ✕ (chk beats no)', () => {
  // A row whose only sessions are "check" is ?, crucially NOT ✕.
  expect(dayEligibility([ELIG_CHK, ELIG_NO])).toBe(ELIG_CHK);
  expect(dayEligibility([ELIG_NO, ELIG_NO])).toBe(ELIG_NO); // only an all-✕ row is ✕
  expect(dayEligibility([ELIG_IN, ELIG_NO])).toBe(ELIG_IN); // any attendable → ✓
});
