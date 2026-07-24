import test from 'node:test';
import assert from 'node:assert/strict';
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
} from './stateblocks.js';
import { mount } from '../components/_fakedom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

test('stateForStatus maps closed → closed, uncurated → hours-not-listed (never merged)', () => {
  assert.equal(stateForStatus({ status: 'closed' }), STATE_CLOSED);
  assert.equal(stateForStatus({ status: 'uncurated' }), STATE_UNLISTED);
  assert.notEqual(STATE_CLOSED, STATE_UNLISTED);
  assert.equal(stateForStatus({ status: 'open' }), null);
  assert.equal(stateForStatus(null), null);
});

test('emptyState is no-pools only for a truly empty answer', () => {
  assert.equal(emptyState({ options: [], statuses: [] }), STATE_NONE);
  assert.equal(emptyState({ options: [{}], statuses: [] }), null);
  assert.equal(emptyState({ options: [], statuses: [{ status: 'closed' }] }), null);
});

test('createStateBlocks keeps a named card per CLOSED pool but collapses uncurated into ONE note', () => {
  const el = mount();
  const day = load('swim_day.json');
  const { keys } = createStateBlocks(el, { answer: day });
  const closed = day.statuses.filter((s) => s.status === 'closed').length;
  const uncurated = day.statuses.filter((s) => s.status === 'uncurated').length;
  assert.ok(uncurated > 1, 'fixture must have several uncurated pools to prove collapsing');
  // Closed stays per-pool; uncurated collapses to exactly one summary card.
  assert.equal(keys.filter((k) => k === STATE_CLOSED).length, closed);
  assert.equal(keys.filter((k) => k === STATE_UNLISTED).length, 1);
  const cards = el.queryAll((c) => c.classList.contains('stateblock'));
  assert.equal(cards.length, closed + 1, 'closed cards + one collapsed unlisted note');
  assert.ok(cards.every((c) => c.getAttribute('role') === 'note'));
  // Three terminal states stay never-merged: closed cards name their reason...
  const closedCard = cards.find((c) => c.classList.contains(`stateblock--${STATE_CLOSED}`));
  assert.ok(closedCard && closedCard.textContent.includes('Closed'));
  // ...and the single unlisted note carries the COUNT + the unknown≠closed honesty line,
  // without repeating a paragraph per pool.
  const unlistedCard = cards.find((c) => c.classList.contains(`stateblock--${STATE_UNLISTED}`));
  assert.ok(unlistedCard, 'one collapsed hours-not-listed note');
  assert.ok(unlistedCard.textContent.includes(String(uncurated)), 'note states the count');
  assert.ok(unlistedCard.textContent.toLowerCase().includes('not the same as closed'));
});

test('createStateBlocks renders a SINGLE no-pools card for an empty answer', () => {
  const el = mount();
  const { keys } = createStateBlocks(el, { answer: { options: [], statuses: [] } });
  assert.deepEqual(keys, [STATE_NONE]);
  const cards = el.queryAll((c) => c.classList.contains('stateblock'));
  assert.equal(cards.length, 1);
  assert.ok(cards[0].classList.contains(`stateblock--${STATE_NONE}`));
  // "no pools" must not read as "closed".
  assert.ok(!cards[0].textContent.toLowerCase().includes('closed —'));
});

test('update() re-renders (empty → statuses)', () => {
  const el = mount();
  const blocks = createStateBlocks(el, { answer: { options: [], statuses: [] } });
  const after = blocks.update({
    options: [],
    statuses: [{ facility: 'City', status: 'closed', detail: 'renovation' }],
  });
  assert.deepEqual(after, [STATE_CLOSED]);
  const card = el.query((c) => c.classList.contains('stateblock'));
  assert.ok(card.textContent.includes('City'));
  assert.ok(card.textContent.includes('renovation'));
});
