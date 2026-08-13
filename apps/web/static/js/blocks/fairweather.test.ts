// fairweather.test.ts — the fair-weather conditional, from the pure rule to both renders.
//
// Zürich's lidos publish a guaranteed block and a fair-weather-only block on the SAME day
// (Heuried: 09:00–14:00 unconditionally, 14:00–21:00 only in good weather). Before this the
// two rendered identically, so the app promised water the city does not promise. The gate
// is mechanical: a marker element exists for a `fair_only` session and does NOT exist when
// every session is `any` — the "omits it" half is the one that can silently rot.
//
// Headless, over `_fakedom` (the repo convention): no jsdom, no browser.

import { expect, test } from 'vitest';

import { mount, type FakeElement } from '../components/_fakedom.js';
import { fake } from '../testutil.js';
import { fairWeatherSpans, fairWeatherText } from '../appdata.js';
import { createBoard, type BoardAnswer } from './board.js';
import { createPoolList } from './poollist.js';
import type { RankRow } from './poolrank.js';

const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);

// The real Heuried July shape, as `/swim` serves it (verified against the built store).
const GUARANTEED = {
  facility: 'Freibad Heuried',
  basin: 'Hauptbecken',
  access: 'PublicSwim',
  start: '09:00',
  end: '14:00',
  weather: 'any',
};
const CONDITIONAL = { ...GUARANTEED, start: '14:00', end: '21:00', weather: 'fair_only' };

// ---- the pure rule ---------------------------------------------------------------

test('fairWeatherSpans names the CONDITIONAL block and only that block', () => {
  // Per-session, never per-day: the morning is a known fact and must not be swept into
  // the caveat. That is the whole reason this returns spans instead of a boolean.
  expect(fairWeatherSpans([GUARANTEED, CONDITIONAL])).toEqual(['14:00–21:00']);
});

test('fairWeatherSpans is empty when every session is unconditional', () => {
  expect(fairWeatherSpans([GUARANTEED])).toEqual([]);
  expect(fairWeatherSpans([])).toEqual([]);
  expect(fairWeatherSpans(null)).toEqual([]);
});

test('an option with no `weather` field at all is treated as unconditional', () => {
  // An older payload (or a `/pools`-shaped row) must not sprout a caveat we cannot support.
  expect(fairWeatherSpans([{ start: '09:00', end: '14:00' }])).toEqual([]);
});

test('two basins publishing the same conditional block say it once', () => {
  const other = { ...CONDITIONAL, basin: 'Nichtschwimmerbecken' };
  expect(fairWeatherSpans([CONDITIONAL, other])).toEqual(['14:00–21:00']);
});

test('fairWeatherText renders the spans, and is null when there are none', () => {
  expect(fairWeatherText([GUARANTEED, CONDITIONAL])).toBe(
    'Fair weather only · 14:00–21:00',
  );
  expect(fairWeatherText([GUARANTEED])).toBe(null);
});

// ---- the board render ------------------------------------------------------------

function board(options: unknown[]) {
  const el = mount();
  createBoard(el, {
    data: { day: { options, statuses: [] } as BoardAnswer },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: true }),
  });
  return fake(el);
}

test('the board emits a fair-weather marker for a FAIR_ONLY session', () => {
  const marker = board([GUARANTEED, CONDITIONAL]).query(hasClass('board__rowfair'));
  expect(marker).not.toBe(null);
  expect(marker?.textContent).toContain('14:00–21:00');
});

test('the board emits NO marker when every session is unconditional', () => {
  expect(board([GUARANTEED]).queryAll(hasClass('board__rowfair')).length).toBe(0);
});

test('the marker does not change the row status — the pool IS open', () => {
  // The conditional block qualifies an open row; it must never demote the row to a
  // closed/unknown terminal state (that is the day-level "maybe" the model forbids).
  const el = board([GUARANTEED, CONDITIONAL]);
  expect(el.queryAll(hasClass('board__dot--open')).length).toBe(1);
  expect(el.queryAll(hasClass('board__rowsub')).length).toBe(0);
});

// ---- the phone card render -------------------------------------------------------

function phoneCard(options: RankRow['options']) {
  const el = mount();
  const rows: RankRow[] = [{ label: 'Freibad Heuried', options, statuses: [] }];
  createPoolList(el, { rows, nowMin: 10 * 60, reducedMotion: true });
  return fake(el);
}

test('the phone card emits a fair-weather marker for a FAIR_ONLY session', () => {
  const marker = phoneCard([GUARANTEED, CONDITIONAL]).query(hasClass('plist__fair'));
  expect(marker).not.toBe(null);
  expect(marker?.textContent).toContain('14:00–21:00');
});

test('the phone card emits NO marker when every session is unconditional', () => {
  expect(phoneCard([GUARANTEED]).queryAll(hasClass('plist__fair')).length).toBe(0);
});
