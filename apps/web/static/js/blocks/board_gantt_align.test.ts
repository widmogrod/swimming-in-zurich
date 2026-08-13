import { expect, test } from 'vitest';
// board_gantt_align.test.js — the crown-jewel anti-desync contract (plan Risk #3),
// tested DIRECTLY at S5 (not just transitively via each renderer's own cursor test).
//
// The property: a click at time T lands on the SAME plot-x in the RibbonBoard and in
// the LaneGantt. Both renderers draw through ONE injected `timescale` (board.js →
// ts.X; gantt.js → cursorX(ts, …)); this test builds BOTH with the same instance and
// asserts board.cursorX(T) === gantt.cursorPlotX(T) for sampled minutes. The
// falsifiability test proves it is NOT a tautology: hand each its OWN scale and the
// equality breaks — exactly the regression the shared timescale forbids.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, type LanePanel } from './cursor.js';
import { createBoard, BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createGantt } from './gantt.js';
import type { BoardAnswer, Timescale } from './board.js';
import type { El } from '../domtypes.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const DAY = load<BoardAnswer>('swim_day.json');
const POOL = load<{ lane_panels: unknown[] }>('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0] as LanePanel);

// Sampled cursor minutes across the whole board window (06:00 … 22:00).
const SAMPLES = [360, 450, 540, 600, 690, 780, 870, 960, 1080, 1200, 1320];

function buildBoard(el: El, ts: Timescale) {
  return createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    timescale: ts,
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
}

test('board cursor-x EQUALS gantt cursor-x for every sampled minute (SAME injected timescale)', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const board = buildBoard(mount(), ts);
  const gantt = createGantt(mount(), { basin: BASIN, timescale: ts });
  for (const T of SAMPLES) {
    // Both go through the ONE mapping — equal by construction, asserted directly.
    expect(board.cursorX(T)).toBe(gantt.cursorPlotX(T));
    // And both equal the shared timescale's own X (no renderer re-derives it).
    expect(board.cursorX(T)).toBe(ts.X(T));
  }
});

test('falsifiable: give each renderer its OWN scale and the equality BREAKS (non-tautology)', () => {
  // This is what fails if someone stops sharing the timescale: two scales, two x's.
  const tsBoard = makeTimescale(BOARD_DAY0, BOARD_DAY1, 900);
  const tsGantt = makeTimescale(BOARD_DAY0, BOARD_DAY1, 500);
  const board = buildBoard(mount(), tsBoard);
  const gantt = createGantt(mount(), { basin: BASIN, timescale: tsGantt });
  let anyDiverged = false;
  for (const T of SAMPLES) {
    if (T === BOARD_DAY0 * 60) continue; // both map the left edge to 0 — skip the trivial tie
    if (board.cursorX(T) !== gantt.cursorPlotX(T)) anyDiverged = true;
  }
  expect(anyDiverged).toBeTruthy();
  // Spot-check the divergence explicitly at 10:00.
  expect(board.cursorX(600)).not.toBe(gantt.cursorPlotX(600));
});
