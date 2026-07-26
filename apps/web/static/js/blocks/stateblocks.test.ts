import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  stateForStatus,
  emptyState,
  createStateBlocks,
  STATE_CLOSED,
  STATE_UNLISTED,
  STATE_NONE,
  type StatusLike,
  type AnswerLike,
} from './stateblocks.js';
import { mount } from '../components/_fakedom.js';
import { must } from '../testutil.js';
import type { FakeElement } from '../components/_fakedom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

test('stateForStatus maps closed → closed, uncurated → hours-not-listed (never merged)', () => {
  expect(stateForStatus({ status: 'closed' })).toBe(STATE_CLOSED);
  expect(stateForStatus({ status: 'uncurated' })).toBe(STATE_UNLISTED);
  expect(STATE_CLOSED).not.toBe(STATE_UNLISTED);
  expect(stateForStatus({ status: 'open' })).toBe(null);
  expect(stateForStatus(null)).toBe(null);
});

test('emptyState is no-pools only for a truly empty answer', () => {
  expect(emptyState({ options: [], statuses: [] })).toBe(STATE_NONE);
  expect(emptyState({ options: [{}], statuses: [] })).toBe(null);
  expect(emptyState({ options: [], statuses: [{ status: 'closed' }] })).toBe(null);
});

test('createStateBlocks keeps a named card per CLOSED pool but collapses uncurated into ONE note', () => {
  const el = mount();
  const day = load<Required<AnswerLike>>('swim_day.json');
  const { keys } = createStateBlocks(el, { answer: day });
  const closed = day.statuses.filter((s: StatusLike) => s.status === 'closed').length;
  const uncurated = day.statuses.filter((s: StatusLike) => s.status === 'uncurated').length;
  expect(uncurated > 1).toBeTruthy();
  // Closed stays per-pool; uncurated collapses to exactly one summary card.
  expect(keys.filter((k: string) => k === STATE_CLOSED).length).toBe(closed);
  expect(keys.filter((k: string) => k === STATE_UNLISTED).length).toBe(1);
  const cards = el.queryAll((c: FakeElement) => c.classList.contains('stateblock'));
  expect(cards.length).toBe(closed + 1);
  expect(cards.every((c: FakeElement) => c.getAttribute('role') === 'note')).toBeTruthy();
  // Three terminal states stay never-merged: closed cards name their reason...
  const closedCard = must(cards.find((c: FakeElement) => c.classList.contains(`stateblock--${STATE_CLOSED}`)));
  expect(closedCard && closedCard.textContent.includes('Closed')).toBeTruthy();
  // ...and the single unlisted note carries the COUNT + the unknown≠closed honesty line,
  // without repeating a paragraph per pool.
  const unlistedCard = must(cards.find((c: FakeElement) => c.classList.contains(`stateblock--${STATE_UNLISTED}`)));
  expect(unlistedCard).toBeTruthy();
  expect(unlistedCard.textContent.includes(String(uncurated))).toBeTruthy();
  expect(unlistedCard.textContent.toLowerCase().includes('not the same as closed')).toBeTruthy();
});

test('createStateBlocks renders a SINGLE no-pools card for an empty answer', () => {
  const el = mount();
  const { keys } = createStateBlocks(el, { answer: { options: [], statuses: [] } });
  expect(keys).toEqual([STATE_NONE]);
  const cards = el.queryAll((c: FakeElement) => c.classList.contains('stateblock'));
  expect(cards.length).toBe(1);
  expect(cards[0].classList.contains(`stateblock--${STATE_NONE}`)).toBeTruthy();
  // "no pools" must not read as "closed".
  expect(!cards[0].textContent.toLowerCase().includes('closed —')).toBeTruthy();
});

test('update() re-renders (empty → statuses)', () => {
  const el = mount();
  const blocks = createStateBlocks(el, { answer: { options: [], statuses: [] } });
  const after = blocks.update({
    options: [],
    statuses: [
      {
        facility: 'City',
        status: 'closed',
        closure_code: 'maintenance',
        detail_params: {},
      },
    ],
  });
  expect(after).toEqual([STATE_CLOSED]);
  const card = must(el.query((c: FakeElement) => c.classList.contains('stateblock')));
  expect(card.textContent.includes('City')).toBeTruthy();
  // The reason is rendered from the CLOSURE CODE now, not the server's prose.
  expect(card.textContent.includes('Maintenance')).toBeTruthy();
});
