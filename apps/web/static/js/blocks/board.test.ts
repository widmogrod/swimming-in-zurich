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
  rowBasinName,
  rowFacilityOf,
  hhmmToMin,
  BOARD_PLOT,
  type BoardAnswer,
  type BoardWeek,
} from './board.js';
import { rowKeyFor } from './rowkey.js';
import { rowKey } from './poolrank.js';

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
  // Every row now states the pool it is about, and no label in this answer gained a
  // suffix — the committed fixture carries no basin split.
  expect(rows.every((r) => r.facility === r.label)).toBe(true);
});

// --- S3: a row is a facility AND a basin -------------------------------------------
//
// These use INLINE answers rather than the shared `swim_day.json`: that fixture is
// hand-committed, predates `basin_id` entirely, and is S4's to extend (its Touches name
// it, for `lane_day_view`). Extending it here to carry basin ids would have made every
// assertion below read a fixture written to satisfy them. The one test that DOES read it
// is the regression above — the whole real-shaped answer must keep producing exactly the
// rows and labels it produced before.

const opt = (
  facility: string,
  basin_id: string | undefined,
  basin: string | undefined,
  extra: Record<string, unknown> = {},
) => ({ facility, basin_id, basin, start: '06:00', end: '22:00', ...extra });

test('a pool contributing two basins becomes TWO rows, each naming its facility and basin', () => {
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
    ],
    statuses: [],
  });
  expect(rows.length).toBe(2);
  expect(rows.map((r) => r.facility)).toEqual(['Hallenbad City', 'Hallenbad City']);
  expect(rows.map((r) => r.basin_id)).toEqual(['city-main', 'city-50m']);
  expect(rows.map((r) => r.basin)).toEqual(['Hauptbecken', 'Schwimmerbecken']);
  // L1: the suffix appears precisely because this facility contributed two basins.
  expect(rows.map((r) => r.label)).toEqual([
    'Hallenbad City · Hauptbecken',
    'Hallenbad City · Schwimmerbecken',
  ]);
  // Two basins of one pool never share options.
  expect(rows[0].options.length).toBe(1);
  expect(rows[1].options.length).toBe(1);
});

test('two basins with the SAME name are still two rows — the id is the key, not the name', () => {
  // Basin names are not guaranteed unique within a facility; a row key that can collide
  // is a silent mis-render (the reason `basin_id` is on the wire at all).
  const rows = dayRows({
    options: [
      opt('Hallenbad Oerlikon', 'oerlikon-50m', 'Becken'),
      opt('Hallenbad Oerlikon', 'oerlikon-sprungbecken', 'Becken'),
    ],
    statuses: [],
  });
  expect(rows.length).toBe(2);
  expect(rows.map((r) => r.basin_id)).toEqual(['oerlikon-50m', 'oerlikon-sprungbecken']);
});

test('a status-only pool stays ONE facility-level row, with no basin (I3)', () => {
  const rows = dayRows({
    options: [],
    statuses: [
      { facility: 'Seebad Utoquai', status: 'closed', detail: 'Sommerpause' },
      { facility: 'Seebad Utoquai', status: 'closed', detail: 'Sommerpause' },
    ],
  });
  expect(rows.length).toBe(1);
  expect(rows[0].facility).toBe('Seebad Utoquai');
  expect(rows[0].basin_id).toBe(undefined);
  expect(rows[0].basin).toBe(undefined);
  expect(rows[0].label).toBe('Seebad Utoquai'); // no suffix — a status names no water
  expect(rows[0].statuses.length).toBe(2);
});

test('a pool that has BOTH options and a status renders no extra status row (I3)', () => {
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
    ],
    statuses: [{ facility: 'Hallenbad City', status: 'closed' }],
  });
  expect(rows.length).toBe(2); // NOT three
  expect(rows.filter((r) => r.statuses.length > 0).length).toBe(1);
});

test('a SINGLE-basin pool keeps its label byte-identical to the pool name (L1)', () => {
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken', { start: '18:00', end: '22:00' }),
      opt('Hallenbad Bläsi', 'blaesi-25m', 'Schwimmerbecken'),
    ],
    statuses: [],
  });
  expect(rows.length).toBe(2);
  expect(rows.map((r) => r.label)).toEqual(['Hallenbad City', 'Hallenbad Bläsi']);
  expect(rows[0].options.length).toBe(2); // both sessions of the one basin, one row
});

test('L1 is per-ANSWER: the same pool loses its suffix on a day one basin is closed', () => {
  // Precisely why no code may key on a label (I6).
  const twoBasins = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
    ],
    statuses: [],
  });
  const oneBasin = dayRows({
    options: [opt('Hallenbad City', 'city-main', 'Hauptbecken')],
    statuses: [],
  });
  expect(twoBasins[0].label).toBe('Hallenbad City · Hauptbecken');
  expect(oneBasin[0].label).toBe('Hallenbad City');
  // …while the IDENTITY of that row is unchanged across the two answers.
  expect(oneBasin[0].facility).toBe(twoBasins[0].facility);
  expect(oneBasin[0].basin_id).toBe(twoBasins[0].basin_id);
});

test('`basinInLabel` is set on exactly the rows whose LABEL carries the basin (L1)', () => {
  // The biconditional the phone list depends on. `poollist.ts` used to re-read the label
  // (`label.endsWith('· ' + basin)`) to decide whether to repeat the basin on the fact
  // line; it now reads this flag, so the flag must agree with the label on EVERY shape a
  // row comes in — suffixed, unsuffixed, nameless-basin, and status-only.
  const answers: BoardAnswer[] = [
    // two named basins: both suffixed
    {
      options: [
        opt('Hallenbad City', 'city-main', 'Hauptbecken'),
        opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
      ],
      statuses: [],
    },
    // one basin: no suffix
    { options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')], statuses: [] },
    // two basins, one unnamed: only the named one is suffixed
    {
      options: [
        opt('Hallenbad City', 'city-main', 'Hauptbecken'),
        opt('Hallenbad City', 'city-50m', ''),
      ],
      statuses: [],
    },
    // status only: names no water at all
    { options: [], statuses: [{ facility: 'Seebad Utoquai', status: 'closed' }] },
  ];
  for (const answer of answers) {
    for (const row of dayRows(answer)) {
      const suffixed = row.label !== row.facility;
      expect(row.basinInLabel === true).toBe(suffixed);
      if (suffixed) expect(row.label).toBe(`${row.facility} \u00b7 ${row.basin}`);
    }
  }
});

test('a Pool-mode week row never claims a basin in its label', () => {
  // Week rows are days, not basins (I4), and they skip `applyLabelRule` entirely — so the
  // flag must be absent rather than stale-true from some earlier answer.
  const rows = weekRows(WEEK);
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) expect(row.basinInLabel).toBe(undefined);
});

test('the phone list keys a row exactly as the board grouped it — ONE definition', () => {
  // `board.ts` mints the grouping key and `poolrank.ts` re-derives it for the open-card
  // state. The two strings never meet at runtime, so only a test can catch them drifting.
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
      opt('Hallenbad Bläsi', undefined, undefined),
    ],
    statuses: [],
  });
  for (const row of rows) expect(rowKey(row)).toBe(rowKeyFor(row.facility, row.basin_id));
  expect(new Set(rows.map(rowKey)).size).toBe(rows.length);
});

test('the row key separator cannot let two different rows collide', () => {
  // A space separator would make `facility="A B" + basin="C"` and `facility="A" +
  // basin="B C"` the same string — one row silently rendered as the other.
  expect(rowKeyFor('A B', 'C')).not.toBe(rowKeyFor('A', 'B C'));
  // …and an absent basin is its own row, not a prefix of a named one.
  expect(rowKeyFor('A', undefined)).toBe(rowKeyFor('A', ''));
  expect(rowKeyFor('A', undefined)).not.toBe(rowKeyFor('A', 'main'));
});

test('a basin with no NAME is labelled by its pool alone — never by its internal id', () => {
  // `OptionOut.basin` is a plain `str` the wire does not constrain non-empty. Falling back
  // to `basin_id` would put "Hallenbad City \u00b7 city-50m" — a database key — in front of a
  // reader. A basin we cannot name is a basin we say nothing about.
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', ''),
    ],
    statuses: [],
  });
  expect(rows.length).toBe(2); // still two rows — the SPLIT does not depend on the name
  expect(rows[1].label).toBe('Hallenbad City');
  expect(rows[1].label).not.toContain('city-50m');
  expect(rows.some((r) => r.label.includes('city-'))).toBe(false);
  // the named sibling still earns its suffix
  expect(rows[0].label).toBe('Hallenbad City \u00b7 Hauptbecken');
});

test('an answer with no basin_id at all degrades to one row per facility, unsuffixed', () => {
  // Pre-S2 payloads (and the committed `swim_day.json`) carry no basin id.
  const rows = dayRows({
    options: [
      { facility: 'Hallenbad City', basin: 'Hauptbecken' },
      { facility: 'Hallenbad City', basin: 'Schwimmerbecken' },
    ],
    statuses: [],
  });
  expect(rows.length).toBe(1);
  expect(rows[0].label).toBe('Hallenbad City');
});

// --- rowFacilityOf: the pure seam behind app.ts's row → pool join --------------------

test('rowFacilityOf reads a Day row straight off its own facility', () => {
  const rows = dayRows({
    options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')],
    statuses: [],
  });
  expect(rowFacilityOf(rows[0])).toBe('Hallenbad City');
});

test("a week that does NOT name its pool still names it from the day's own sessions", () => {
  // `BoardRow.facility` is required, so `weekRows` writes `''` for a week with no facility
  // — a URL-restored `?view=pool&pool=<id>` arrives with an id and no name until /pools
  // backfills it. `''` must read as ABSENT, not as an answer: `??` here instead of `||`
  // would hand the panel a nameless pool and it would find no facts and no official link.
  const rows = weekRows({
    days: [
      {
        label: 'Monday',
        date: '2026-08-10',
        answer: { options: [opt('Hallenbad Oerlikon', 'oerlikon-50m', '50m-Becken')], statuses: [] },
      },
    ],
  });
  expect(rows[0].facility).toBe('');
  expect(rowFacilityOf(rows[0])).toBe('Hallenbad Oerlikon');
});

test('a row with nothing naming a pool answers null rather than an empty name', () => {
  const rows = weekRows({
    days: [{ label: 'Monday', date: '2026-08-10', answer: { options: [], statuses: [] } }],
  });
  expect(rowFacilityOf(rows[0])).toBeNull();
});

test('a nameless week falls back to a STATUS facility when it has no options', () => {
  // A shut pool's week is all statuses and no sessions — the case that would otherwise
  // render a pool page with no pool name on it.
  const rows = weekRows({
    days: [
      {
        label: 'Monday',
        date: '2026-08-10',
        answer: { options: [], statuses: [{ facility: 'Seebad Utoquai', status: 'closed' }] },
      },
    ],
  });
  expect(rowFacilityOf(rows[0])).toBe('Seebad Utoquai');
});

// --- rowBasinName: the pure seam behind app.ts's row → panelForBasin join (AC4) -------

test('rowBasinName names the CLICKED row\'s basin for a multi-basin pool', () => {
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-main', 'Hauptbecken'),
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken'),
    ],
    statuses: [],
  });
  expect(rowBasinName(rows[0])).toBe('Hauptbecken');
  expect(rowBasinName(rows[1])).toBe('Schwimmerbecken');
});

test('rowBasinName reports the ROW\'s basin, not whichever option happens to be first', () => {
  // The seam exists to answer "which basin is this ROW about". Every realistic fixture has
  // row.basin === options[0].basin, so deleting the row-field read leaves the suite green
  // while the seam has silently become "ask the first option" — which is the pre-S3
  // behaviour app.ts had, and the wrong answer the moment a row holds a stray option.
  const row = {
    label: 'Hallenbad City \u00b7 Schwimmerbecken',
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
    basin: 'Schwimmerbecken',
    options: [opt('Hallenbad City', 'city-main', 'Hauptbecken')],
    statuses: [],
  };
  expect(rowBasinName(row)).toBe('Schwimmerbecken');
  expect(rowBasinName(row)).not.toBe('Hauptbecken');
});

test('rowBasinName is null for a status row — it is about no particular water', () => {
  const rows = dayRows({
    options: [],
    statuses: [{ facility: 'Seebad Utoquai', status: 'closed' }],
  });
  expect(rowBasinName(rows[0])).toBeNull();
});

test('rowBasinName falls back to the row\'s own options (Pool-mode day rows)', () => {
  const rows = weekRows({
    facility: 'Hallenbad City',
    days: [
      {
        label: 'Mon',
        iso: '2026-08-10',
        answer: { options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')], statuses: [] },
      },
    ],
  });
  expect(rowBasinName(rows[0])).toBe('Schwimmerbecken');
});

test('weekRows yields one row per captured day', () => {
  const rows = weekRows(WEEK);
  expect(rows.length).toBe(WEEK.days.length);
  expect(rows[0].label).toBe(WEEK.days[0].label);
});

test('Pool mode is UNCHANGED by the row split: same labels, dates still populated (I4)', () => {
  // weekRows' rows are DAYS, not pools. Splitting the week per basin is out of scope, so
  // its projection must survive S3 untouched — `date` above all, which the today-marker,
  // the Pool-view panel and the auto-open all read.
  const rows = weekRows(WEEK);
  expect(rows.length).toBe(WEEK.days.length);
  expect(rows.map((r) => r.label)).toEqual(WEEK.days.map((d) => d.label));
  expect(rows.map((r) => r.date)).toEqual(WEEK.days.map((d) => d.date ?? d.iso));
  expect(rows.every((r) => r.date != null && r.date !== '')).toBe(true);
  expect(rows.map((r) => r.options)).toEqual(WEEK.days.map((d) => d.answer.options ?? []));
  expect(rows.map((r) => r.statuses)).toEqual(WEEK.days.map((d) => d.answer.statuses ?? []));
  // No week row is per-basin, and every one names the pool the week is about.
  expect(rows.every((r) => r.basin_id === undefined)).toBe(true);
  expect(rows.every((r) => r.facility === WEEK.facility)).toBe(true);
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

test("the board row for aemtler's Thursday girls-only session never badges ✓ for an adult man", () => {
  // The harm named in the school-access-vocabulary plan's Context, proven in the UI LAYER:
  // the option below is a real captured `/swim` response (generated by
  // apps/web/tests/test_eligibility_ui_contract.py from an offline `swimzh build`), and this
  // is the exact function that paints the row's badge. Before this slice the badge said ✓
  // while `poolrank` read the server's `eligible: false` — the UI contradicting itself.
  const { viewer, option } = load<{
    viewer: { gender: string; age: number };
    option: { access: string; eligible: boolean; start: string; end: string };
  }>('aemtler_girls_only.json');
  expect(option.access).toBe('GirlsOnly');
  expect(option.start).toBe('17:15');
  expect(option.eligible).toBe(false);

  const row = { options: [option] };
  expect(rowEligibility(row, viewer)).not.toBe('in');
  expect(rowEligibility(row, viewer)).toBe('no');
  // A row that ALSO holds a public session still reads ✓ — the fix restricts the girls-only
  // band, it does not blanket the pool.
  expect(rowEligibility({ options: [option, { access: 'PublicSwim' }] }, viewer)).toBe('in');
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
