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

test('createStateBlocks renders one distinct card per closed/uncurated status', () => {
  const el = mount();
  const day = load('swim_day.json');
  const { keys } = createStateBlocks(el, { answer: day });
  const closed = day.statuses.filter((s) => s.status === 'closed').length;
  const uncurated = day.statuses.filter((s) => s.status === 'uncurated').length;
  assert.equal(keys.filter((k) => k === STATE_CLOSED).length, closed);
  assert.equal(keys.filter((k) => k === STATE_UNLISTED).length, uncurated);
  // Each card carries its own modifier class (visually distinct — never a bare blank).
  const cards = el.queryAll((c) => c.classList.contains('stateblock'));
  assert.equal(cards.length, closed + uncurated);
  assert.ok(cards.every((c) => c.getAttribute('role') === 'note'));
  const closedCard = cards.find((c) => c.classList.contains(`stateblock--${STATE_CLOSED}`));
  assert.ok(closedCard, 'a closed card must carry its modifier class');
  // The closed card names its facility and its reason (not a silent blank).
  assert.ok(closedCard.textContent.includes('Closed'));
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
