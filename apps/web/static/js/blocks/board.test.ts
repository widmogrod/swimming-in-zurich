import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import type { FakeElement } from '../components/_fakedom.js';
import { must } from '../testutil.js';
import {
  createBoard,
  dayRows,
  weekRows,
  boardRows,
  rowStatus,
  rowStatusLine,
  rowEligibility,
  hhmmToMin,
  BOARD_PLOT,
  type BoardAnswer,
  type BoardWeek,
} from './board.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const DAY = load<BoardAnswer>('swim_day.json');
const WEEK = load<BoardWeek>('swim_week_oerlikon.json');

const isCanvas = (e: FakeElement) => e.tagName === 'CANVAS';
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);

test('hhmmToMin parses times to minutes-of-day', () => {
  expect(hhmmToMin('06:00')).toBe(360);
  expect(hhmmToMin('09:30')).toBe(570);
});

test('dayRows groups a /swim answer into one row per facility', () => {
  const rows = dayRows(DAY);
  const facilities = new Set([
    ...DAY.options.map((o) => o.facility),
    ...DAY.statuses.map((s) => s.facility),
  ]);
  expect(rows.length).toBe(facilities.size);
  const oerlikon = must(rows.find((r) => r.label === 'Hallenbad Oerlikon'), 'Oerlikon row');
  expect(oerlikon.options.length >= 1).toBeTruthy();
});

test('weekRows yields one row per captured day', () => {
  const rows = weekRows(WEEK);
  expect(rows.length).toBe(WEEK.days.length);
  expect(rows[0].label).toBe(WEEK.days[0].label);
});

test('boardRows honours FilterState.mode (day vs pool)', () => {
  const data = { day: DAY, week: WEEK };
  expect(boardRows(data, { mode: 'day' }).length).toBe(dayRows(DAY).length);
  expect(boardRows(data, { mode: 'pool' }).length).toBe(weekRows(WEEK).length);
});

test('rowStatus: open when options, closed/unknown from statuses', () => {
  expect(rowStatus({ options: [{}], statuses: [] })).toBe('open');
  expect(rowStatus({ options: [], statuses: [{ status: 'closed' }] })).toBe('closed');
  expect(rowStatus({ options: [], statuses: [{ status: 'awaiting_scrape' }] })).toBe('unknown');
});

test('rowStatusLine folds the terminal state onto the row (FIX 1): closed keeps reason, schedule-less is distinct', () => {
  // Closed keeps its stated reason; a schedule-less status reads its own freshness label
  // (awaiting_scrape → "Hours not published yet"), never "closed".
  expect(rowStatusLine({ options: [], statuses: [{ status: 'closed', detail: 'Sommerpause' }] })).toEqual({
    kind: 'closed',
    text: 'Closed · Sommerpause',
  });
  expect(rowStatusLine({ options: [], statuses: [{ status: 'awaiting_scrape' }] })).toEqual({
    kind: 'unknown',
    text: 'Hours not published yet',
  });
  // no_source renders its own label, distinct from awaiting_scrape — three states, never merged.
  expect(rowStatusLine({ options: [], statuses: [{ status: 'no_source' }] })).toEqual({
    kind: 'unknown',
    text: 'Hours not listed',
  });
  // Closed with no detail still says Closed; an OPEN row (has options) has no sub-line.
  expect(must(rowStatusLine({ options: [], statuses: [{ status: 'closed' }] })).text).toBe(
    'Closed',
  );
  expect(rowStatusLine({ options: [{}], statuses: [] })).toBe(null);
});

test('a closed/uncurated row shows its state sub-line ON the label (FIX 1), open rows do not', () => {
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const subs = el.queryAll(hasClass('board__rowsub'));
  const nonOpen = dayRows(DAY).filter((r) => r.options.length === 0).length;
  expect(subs.length).toBe(nonOpen);
  // The three terminal states stay distinct: at least one closed keeps its reason.
  const closedSub = subs.find((s) => s.classList.contains('board__rowsub--closed'));
  expect(closedSub && closedSub.textContent.startsWith('Closed')).toBeTruthy();
  const unknownSub = subs.find((s) => s.classList.contains('board__rowsub--unknown'));
  // The fixture's schedule-less rows are `awaiting_scrape` → their own freshness label.
  expect(unknownSub && unknownSub.textContent === 'Hours not published yet').toBeTruthy();
});

test('rowEligibility reacts to the FilterState gender/age', () => {
  const row = { options: [{ access: 'WomenOnly' }] };
  expect(rowEligibility(row, { gender: 'female', age: null })).toBe('in');
  expect(rowEligibility(row, { gender: 'male', age: null })).toBe('no');
  expect(rowEligibility(row, { gender: '', age: null })).toBe('chk');
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
  expect(canvases.length).toBe(expected + 1);
  expect(el.queryAll(hasClass('board__axiscanvas')).length).toBe(1);
  expect(el.queryAll(hasClass('board__canvas')).length).toBe(expected);
  // one rowlabel per data row (the axis header spacer has no rowname)
  expect(el.queryAll(hasClass('board__rowname')).length).toBe(expected);
  // SHARED SCROLL: there is exactly ONE scroll cell + ONE max-content track holding
  // the axis canvas AND every row canvas — so axis + rows scroll together (the old
  // per-row scroll had one track per row; that structural contract changed with the
  // single-shared-scroll layout, plan item 1).
  expect(el.queryAll(hasClass('board__scrollx')).length).toBe(1);
  const tracks = el.queryAll(hasClass('board__track'));
  expect(tracks.length).toBe(1);
  // The track carries NO inline width — `.board__track { width: max-content }`
  // (blocks.css) governs it from the canvases' intrinsic width.
  expect(tracks[0].style.width).toBe(undefined);
  // the one track holds the axis canvas + every row canvas.
  expect(tracks[0].queryAll(isCanvas).length).toBe(expected + 1);
  // the canvases inside carry the intrinsic plot width they draw at.
  const firstCanvas = must(tracks[0].query(isCanvas), 'row canvas');
  expect(firstCanvas.style.width).toBe(`${BOARD_PLOT}px`);
});

test('option rows carry an EligibilityBadge once a gender/age filter is engaged', () => {
  const el = mount();
  // A gender/age filter engaged → each row with sessions is stamped with its badge
  // (Anyone + Any age shows NO badge, so toggling a filter visibly changes the board).
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: 'female', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const optionRowCount = dayRows(DAY).filter((r) => r.options.length > 0).length;
  expect(el.queryAll(hasClass('board__rowbadge')).length).toBe(optionRowCount);
  // status dots: one per row
  expect(el.queryAll(hasClass('board__dot')).length).toBe(dayRows(DAY).length);
});

test('with NO gender/age filter engaged, no eligibility badges are stamped', () => {
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  expect(el.queryAll(hasClass('board__rowbadge')).length).toBe(0);
  // but the status dots are always present.
  expect(el.queryAll(hasClass('board__dot')).length).toBe(dayRows(DAY).length);
});

test('Pool mode builds one row per day of the week', () => {
  const el = mount();
  createBoard(el, {
    data: { week: WEEK },
    filter: { mode: 'pool', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  expect(el.queryAll(hasClass('board__canvas')).length).toBe(WEEK.days.length);
  expect(el.queryAll(hasClass('board__rowname')).length).toBe(WEEK.days.length);
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
  expect(board.reducedMotion).toBe(true);
  expect(rafCalls).toBe(0); // frozen waterline, no animation loop
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
  expect(board.reducedMotion).toBe(false);
  expect(rafCalls >= 1).toBeTruthy();
});

test('setFilter re-renders the board for the new mode', () => {
  const el = mount();
  const board = createBoard(el, {
    data: { day: DAY, week: WEEK },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  expect(board.rows.length).toBe(dayRows(DAY).length);
  board.setFilter({ mode: 'pool', gender: '', age: null });
  expect(board.rows.length).toBe(weekRows(WEEK).length);
  expect(el.queryAll(hasClass('board__canvas')).length).toBe(weekRows(WEEK).length);
});

// --- S4: closure codes ---------------------------------------------------------------

test('a classified closure renders its translated word, not the curated German', () => {
  const line = rowStatusLine({
    options: [],
    statuses: [
      {
        status: 'closed',
        detail: 'Sommerpause',
        detail_code: 'closed_reason',
        closure_code: 'seasonal_break',
        detail_params: {},
      },
    ],
  });
  expect(line).toEqual({ kind: 'closed', text: 'Closed · Summer break' });
});

test('an UNMAPPED closure still reads as the truth, never as a blank', () => {
  // The fail-safe: `swimzh build` could not classify this phrase (and said so on stderr),
  // so the German rides through verbatim. Showing nothing would be a worse answer than
  // showing a word the reader may not know.
  const line = rowStatusLine({
    options: [],
    statuses: [
      {
        status: 'closed',
        detail: 'Wasserschaden',
        detail_code: 'closed_reason',
        closure_code: 'unmapped',
        detail_params: { text: 'Wasserschaden' },
      },
    ],
  });
  expect(line).toEqual({ kind: 'closed', text: 'Closed · Wasserschaden' });
});

test('a payload with no closure code at all degrades to the server prose', () => {
  // Older/other payloads: fall back rather than blank. Never invent a reason.
  const line = rowStatusLine({
    options: [],
    statuses: [{ status: 'closed', detail: 'Sommerpause' }],
  });
  expect(line).toEqual({ kind: 'closed', text: 'Closed · Sommerpause' });
});

test('a public holiday names ITSELF, in each of the three tiers', () => {
  const closure = (holiday: string, holiday_code: string) =>
    rowStatusLine({
      options: [],
      statuses: [
        {
          status: 'closed',
          detail: `closed (${holiday})`,
          detail_code: 'closed_reason',
          closure_code: 'public_holiday',
          detail_params: { holiday, holiday_code },
        },
      ],
    })?.text;

  // Tier 1 — a shared feast, translated.
  expect(closure('Weihnachten', 'christmas')).toBe('Closed · Christmas Day');
  // Tier 2 — nameable descriptively, like Bastille Day abroad.
  expect(closure('Bundesfeier', 'national_day')).toBe('Closed · Swiss National Day');
  // Tier 3 — Swiss-only, no equivalent: keep the German and GLOSS it. Inventing an
  // English name here would be a worse answer than admitting it has none.
  expect(closure('Berchtoldstag', 'berchtoldstag')).toBe(
    'Closed · Berchtoldstag (2 January, Swiss public holiday)',
  );
  // Unrecognised — the curated name rides through verbatim, never a blank.
  expect(closure('Sechseläuten', 'unknown')).toBe('Closed · Sechseläuten');
});
