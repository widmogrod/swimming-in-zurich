import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import {
  createBoard,
  dayRows,
  weekRows,
  boardRows,
  rowStatus,
  rowEligibility,
  hhmmToMin,
  BOARD_PLOT,
} from './board.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

const DAY = load('swim_day.json');
const WEEK = load('swim_week_oerlikon.json');

const isCanvas = (e) => e.tagName === 'CANVAS';
const hasClass = (c) => (e) => e.classList.contains(c);

test('hhmmToMin parses times to minutes-of-day', () => {
  assert.equal(hhmmToMin('06:00'), 360);
  assert.equal(hhmmToMin('09:30'), 570);
});

test('dayRows groups a /swim answer into one row per facility', () => {
  const rows = dayRows(DAY);
  const facilities = new Set([
    ...DAY.options.map((o) => o.facility),
    ...DAY.statuses.map((s) => s.facility),
  ]);
  assert.equal(rows.length, facilities.size);
  const oerlikon = rows.find((r) => r.label === 'Hallenbad Oerlikon');
  assert.ok(oerlikon.options.length >= 1);
});

test('weekRows yields one row per captured day', () => {
  const rows = weekRows(WEEK);
  assert.equal(rows.length, WEEK.days.length);
  assert.equal(rows[0].label, WEEK.days[0].label);
});

test('boardRows honours FilterState.mode (day vs pool)', () => {
  const data = { day: DAY, week: WEEK };
  assert.equal(boardRows(data, { mode: 'day' }).length, dayRows(DAY).length);
  assert.equal(boardRows(data, { mode: 'pool' }).length, weekRows(WEEK).length);
});

test('rowStatus: open when options, closed/unknown from statuses', () => {
  assert.equal(rowStatus({ options: [{}], statuses: [] }), 'open');
  assert.equal(rowStatus({ options: [], statuses: [{ status: 'closed' }] }), 'closed');
  assert.equal(rowStatus({ options: [], statuses: [{ status: 'uncurated' }] }), 'unknown');
});

test('rowEligibility reacts to the FilterState gender/age', () => {
  const row = { options: [{ access: 'WomenOnly' }] };
  assert.equal(rowEligibility(row, { gender: 'female', age: null }), 'in');
  assert.equal(rowEligibility(row, { gender: 'male', age: null }), 'no');
  assert.equal(rowEligibility(row, { gender: '', age: null }), 'chk');
});

test('Day mode builds: axis row + one row/canvas/rowlabel per facility', () => {
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const expected = dayRows(DAY).length;
  // one axis canvas + one canvas per data row
  const canvases = el.queryAll(isCanvas);
  assert.equal(canvases.length, expected + 1);
  assert.equal(el.queryAll(hasClass('board__axiscanvas')).length, 1);
  assert.equal(el.queryAll(hasClass('board__canvas')).length, expected);
  // one rowlabel per data row (+ the axis header spacer)
  assert.equal(el.queryAll(hasClass('board__rowname')).length, expected);
  // every data row's canvas lives inside a scroll cell → a max-content track
  const tracks = el.queryAll(hasClass('board__track'));
  assert.equal(tracks.length, expected + 1);
  // The track carries NO inline width now — `.board__track { width: max-content }`
  // (blocks.css) governs it from the canvas' intrinsic width (F carried nit).
  assert.equal(tracks[0].style.width, undefined);
  // the canvas inside still carries the intrinsic plot width it draws at.
  const firstCanvas = tracks[0].query(isCanvas);
  assert.equal(firstCanvas.style.width, `${BOARD_PLOT}px`);
});

test('option rows carry an EligibilityBadge; option-less rows carry only a status dot', () => {
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const optionRowCount = dayRows(DAY).filter((r) => r.options.length > 0).length;
  assert.equal(el.queryAll(hasClass('board__rowbadge')).length, optionRowCount);
  // status dots: one per row
  assert.equal(el.queryAll(hasClass('board__dot')).length, dayRows(DAY).length);
});

test('Pool mode builds one row per day of the week', () => {
  const el = mount();
  createBoard(el, {
    data: { week: WEEK },
    filter: { mode: 'pool', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  assert.equal(el.queryAll(hasClass('board__canvas')).length, WEEK.days.length);
  assert.equal(el.queryAll(hasClass('board__rowname')).length, WEEK.days.length);
});

test('reduced-motion: the RAF loop is NOT started when the media query matches', () => {
  let rafCalls = 0;
  const el = mount();
  const board = createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: (q) => ({ matches: q.includes('reduced-motion') }),
    requestAnimationFrame: () => {
      rafCalls += 1;
    },
  });
  assert.equal(board.reducedMotion, true);
  assert.equal(rafCalls, 0); // frozen waterline, no animation loop
});

test('motion allowed: the RAF loop IS started when the media query does not match', () => {
  let rafCalls = 0;
  const el = mount();
  const board = createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {
      rafCalls += 1;
    }, // records the call but does not recurse → the loop runs exactly once
  });
  assert.equal(board.reducedMotion, false);
  assert.ok(rafCalls >= 1);
});

test('setFilter re-renders the board for the new mode', () => {
  const el = mount();
  const board = createBoard(el, {
    data: { day: DAY, week: WEEK },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  assert.equal(board.rows.length, dayRows(DAY).length);
  board.setFilter({ mode: 'pool', gender: '', age: null });
  assert.equal(board.rows.length, weekRows(WEEK).length);
  assert.equal(el.queryAll(hasClass('board__canvas')).length, weekRows(WEEK).length);
});
