import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import type { FakeElement } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, cursorX, publicAt, type LanePanel } from './cursor.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createGantt } from './gantt.js';
import { must } from '../testutil.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const POOL = load<{ lane_panels: unknown[] }>('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0] as LanePanel); // 50m-Becken, 8 lanes
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);
const textIs = (t: string) => (e: FakeElement) => e.textContent === t;

// The sampled cursor minutes for the alignment assertions (06:00 … 22:00).
const SAMPLES = [360, 450, 540, 600, 690, 780, 870, 960, 1080, 1200, 1320];

test('createGantt REQUIRES a shared timescale (refuses to re-derive its own scale)', () => {
  expect(() => createGantt(mount(), { basin: BASIN } as never)).toThrow();
});

test('(a) cursor-x equality: the Gantt cursor-x is exactly the board timescale mapping', () => {
  // The board draws its ribbons/cursor through THIS timescale (board.js → ts.X); the
  // Gantt is handed the SAME instance, so cursorPlotX(T) == board cursor-x(T) == ts.X(T).
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const g = createGantt(mount(), { basin: BASIN, timescale: ts });
  for (const T of SAMPLES) {
    expect(g.cursorPlotX(T)).toBe(ts.X(T)); // board & Gantt share the mapping
    expect(g.cursorPlotX(T)).toBe(cursorX(ts, T)); // both go through the one helper
  }
});

test('(a) non-tautology: cursorPlotX tracks the INJECTED scale, so a private scale would diverge', () => {
  // Two different scales → two different cursor-x for the same minute. This is what
  // FAILS if someone gives the Gantt its own timescale instead of the board's.
  const ts900 = makeTimescale(6, 22, 900);
  const ts500 = makeTimescale(6, 22, 500);
  const g900 = createGantt(mount(), { basin: BASIN, timescale: ts900 });
  const g500 = createGantt(mount(), { basin: BASIN, timescale: ts500 });
  const T = 600; // 10:00
  expect(g900.cursorPlotX(T)).toBe(ts900.X(T));
  expect(g500.cursorPlotX(T)).toBe(ts500.X(T));
  expect(g900.cursorPlotX(T)).not.toBe(g500.cursorPlotX(T));
});

test('(a) a click at 10:00 puts the Gantt cursor on the Gantt 10:00 gridline', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  g.setCursor(600); // 10:00
  const cursor = must(el.query(hasClass('gantt__cursor')));
  const tick = must(
    el.queryAll(hasClass('gantt__tick')).find((t) => t.textContent === '10:00'),
    '10:00 tick',
  );
  // Both the cursor and the 10:00 axis tick are placed at the SAME track x.
  expect(cursor.style.left).toBe(`${g.trackX(600)}px`);
  expect(tick.style.left).toBe(`${g.trackX(600)}px`);
});

test('(c) one lane row per lane, with owner-named reserved segments from /pools/{id}', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  createGantt(el, { basin: BASIN, timescale: ts });
  // one row per lane
  expect(el.queryAll(hasClass('gantt__lane')).length).toBe(BASIN.strips.length);
  expect(el.queryAll(hasClass('gantt__lanelabel')).length).toBe(BASIN.strips.length);
  // reserved segments carry the owner text seen in the real capture
  const reserved = el.queryAll(hasClass('is-reserved'));
  expect(reserved.length > 0).toBeTruthy();
  for (const owner of ['Limmat-Sharks', 'Schools', 'PH Zürich']) {
    expect(must(el.query(textIs(owner)))).toBeTruthy();
  }
  // public segments are labelled, never hue-only
  expect(el.queryAll(hasClass('is-public')).length > 0).toBeTruthy();
});

test('the live readout reads publicAt at the cursor, formatted "T · N of M lanes public"', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  g.setCursor(780); // 13:00
  const { public: n, total: m } = publicAt(BASIN, 780);
  expect(g.readoutAt(780)).toEqual({ public: n, total: m });
  const readout = must(el.query(hasClass('gantt__readout')));
  expect(readout.textContent).toBe(`13:00 · ${n} of ${m} lanes public`);
});
