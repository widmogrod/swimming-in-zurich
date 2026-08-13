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
  dividerIndex,
  groupByOpenToday,
  isOpenToday,
  weekRows,
  boardRows,
  rowHeight,
  rowStatus,
  rowStatusLine,
  rowEligibility,
  rowBasinName,
  rowFacilityOf,
  hhmmToMin,
  BOARD_PLOT,
  type BoardAnswer,
  type BoardRow,
  type BoardWeek,
} from './board.js';
import { rowKeyFor } from './rowkey.js';
import { rowKey } from './poolrank.js';
import { laneBands, LANE_BAND_MIN_H } from './ribbonrender.js';
import { ribbonsFor } from './ribbonmodel.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const DAY = load<BoardAnswer>('swim_day.json');
const WEEK = load<BoardWeek>('swim_week_oerlikon.json');

const isCanvas = (e: FakeElement) => e.tagName === 'CANVAS';
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);
/** A canvas' INTRINSIC pixel size — the board sets `canvas.width`/`canvas.height` as plain
 *  properties, which are not part of the structural `El` surface the fake DOM declares. */
const intrinsic = (e: FakeElement) => e as unknown as { width: number; height: number };

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

// --- board-order-and-defects S2: two groups, one visible boundary (rules O2/O3) -------

const closedRow = (facility: string): BoardRow => ({
  label: facility,
  facility,
  options: [],
  statuses: [{ facility, status: 'closed' }],
});

const openRow = (facility: string): BoardRow => ({
  label: facility,
  facility,
  options: [opt(facility, undefined, undefined)],
  statuses: [],
});

test('isOpenToday asks for OPTIONS, not for the ABSENCE of a status', () => {
  // The two predicates are equivalent on every answer `dayRows` can build — there, statuses
  // and options are disjoint (board.ts:196-207) — so a `dayRows`-shaped test cannot tell them
  // apart and `row.statuses.length === 0` survives as a silent mutant. The row below is the
  // case that defensive branch exists for, and it is the one that separates them: a pool with
  // water you can plan AND a status about the same pool is OPEN. Reading the status instead
  // would file it under "nothing to plan today" while its ribbons are being drawn.
  const both: BoardRow = {
    label: 'Hallenbad City',
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
    options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')],
    statuses: [{ facility: 'Hallenbad City', status: 'closed' }],
  };
  expect(isOpenToday(both)).toBe(true);
  expect(isOpenToday({ ...both, options: [] })).toBe(false);
  // …and a row with neither is not open either — the absence of OPTIONS is the whole test.
  expect(isOpenToday({ label: 'X', facility: 'X', options: [], statuses: [] })).toBe(false);
});

test('groupByOpenToday partitions open-before-closed, stably inside each group', () => {
  // Asserted on an input `dayRows` CANNOT produce: on its output this function is the identity
  // (option rows are built before status rows), so a `dayRows`-level test proves nothing about
  // it. `dividerIndex` assumes the partition, so the partition must be a real assertion.
  const rows = [closedRow('Shut A'), openRow('Open A'), closedRow('Shut B'), openRow('Open B')];
  expect(groupByOpenToday(rows).map((r) => r.facility)).toEqual([
    'Open A',
    'Open B',
    'Shut A',
    'Shut B',
  ]);
  // Order WITHIN each group is preserved — it is the API's distance order and must not be
  // re-sorted here; a comparator on a boolean would be free to permute it.
  expect(groupByOpenToday([openRow('B'), openRow('A')]).map((r) => r.facility)).toEqual(['B', 'A']);
  expect(groupByOpenToday([]).length).toBe(0);
});

test('isOpenToday agrees with the options on every row dayRows builds', () => {
  // No `BoardRow.openToday` field exists on purpose: a stored flag can disagree with the very
  // options it describes. This is the biconditional the divider then relies on.
  const answer: BoardAnswer = {
    options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')],
    statuses: [
      { facility: 'Seebad Utoquai', status: 'closed' },
      { facility: 'Schulschwimmanlage Hardau', status: 'no_source' },
    ],
  };
  for (const row of dayRows(answer)) {
    expect(isOpenToday(row)).toBe(row.options.length > 0);
  }
  expect(dayRows(answer).filter(isOpenToday).length).toBe(1);
});

test('dayRows puts every open row before every row with nothing to plan (O2)', () => {
  // The statuses below are NEARER than the options (1.22 / 1.43 km against 2.59 / 3.12), so the
  // answer's own distance order would interleave them. The board still shows every open pool
  // first: O2 groups, and ranks only INSIDE a group.
  //
  // This is `dividerIndex`'s PRECONDITION — that the list is partitioned before a boundary is
  // drawn into it — asserted on the OUTPUT rather than assumed from how `dayRows` happens to
  // loop. See the note on `groupByOpenToday`'s call site: today the loops guarantee it and the
  // grouping call is provably the identity here, so this test cannot redden on that call alone.
  // It reddens the moment the guarantee AND the call are both gone, which is the actual hole.
  const rows = dayRows({
    options: [
      opt('Hallenbad City', 'city-50m', 'Schwimmerbecken', { distance_km: 2.59 }),
      opt('Hallenbad Oerlikon', 'oerlikon-50m', '50m-Becken', { distance_km: 3.12 }),
    ],
    statuses: [
      { facility: 'Seebad Utoquai', status: 'closed', distance_km: 1.22 },
      { facility: 'Schulschwimmanlage Hardau', status: 'no_source', distance_km: 1.43 },
    ],
  });
  const groups = rows.map(isOpenToday);
  expect(groups).toEqual([true, true, false, false]);
  // …and the API's order is preserved INSIDE each group — since S2 that order is distance.
  expect(rows.map((r) => r.facility)).toEqual([
    'Hallenbad City',
    'Hallenbad Oerlikon',
    'Seebad Utoquai',
    'Schulschwimmanlage Hardau',
  ]);
});

test('dividerIndex points at the first closed row — and is null unless BOTH groups exist (O3)', () => {
  // O3 in full: an empty group must never leave a dangling header. Both empty cases are
  // pinned, because they are the two the boundary is most likely to be drawn wrongly in.
  expect(dividerIndex([openRow('A'), openRow('B'), closedRow('C')])).toBe(2);
  expect(dividerIndex([closedRow('C'), closedRow('D')])).toBeNull(); // nothing open above it
  expect(dividerIndex([openRow('A'), openRow('B')])).toBeNull(); // nothing closed below it
  expect(dividerIndex([])).toBeNull();
  // The very smallest board that HAS a boundary still gets one.
  expect(dividerIndex([openRow('A'), closedRow('C')])).toBe(1);
});

test('the board draws the divider once, between the groups, in BOTH columns', () => {
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  expect(el.queryAll(hasClass('board__divider')).length).toBe(1);
  // The track spacer is not decoration: the label stack and the canvas track are PARALLEL
  // lists, so a divider in only the label column would drift every row below it out of line
  // with its own canvas — the desync the whole shared-scroll layout exists to prevent.
  expect(el.queryAll(hasClass('board__dividergap')).length).toBe(1);
  const labelsBody = must(el.query(hasClass('board__labelsbody')), 'labels body');
  const trackBody = must(el.query(hasClass('board__trackbody')), 'track body');
  expect(labelsBody.children.length).toBe(trackBody.children.length);
  const at = dividerIndex(dayRows(DAY));
  expect(at).not.toBeNull();
  const boundary = at as number;
  expect(labelsBody.children[boundary].classList.contains('board__divider')).toBe(true);
  expect(trackBody.children[boundary].classList.contains('board__dividergap')).toBe(true);
  // The row that follows it is the FIRST row with nothing to plan, not some later one.
  expect(isOpenToday(dayRows(DAY)[boundary])).toBe(false);
  expect(isOpenToday(dayRows(DAY)[boundary - 1])).toBe(true);
});

test('the divider heading never calls an unknown schedule "closed"', () => {
  // The group below it holds shut pools AND pools whose hours we simply do not have. This UI
  // refuses to render an unknown as a closure anywhere else; the heading may not do it either.
  const el = mount();
  createBoard(el, {
    data: { day: DAY },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const divider = must(el.query(hasClass('board__divider')), 'divider');
  expect(divider.textContent).toBe('No sessions published today');
  expect(divider.textContent.toLowerCase()).not.toContain('closed');
});

test('a board with only one group carries no divider at all (O3, through the DOM)', () => {
  const build = (day: BoardAnswer) => {
    const el = mount();
    createBoard(el, {
      data: { day },
      filter: { mode: 'day', gender: '', age: null },
      matchMedia: () => ({ matches: false }),
      requestAnimationFrame: () => {},
    });
    return el;
  };
  const allOpen = build({ options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')], statuses: [] });
  expect(allOpen.queryAll(hasClass('board__divider')).length).toBe(0);
  expect(allOpen.queryAll(hasClass('board__dividergap')).length).toBe(0);
  const allClosed = build({ options: [], statuses: [{ facility: 'Seebad Utoquai', status: 'closed' }] });
  expect(allClosed.queryAll(hasClass('board__divider')).length).toBe(0);
  expect(allClosed.queryAll(hasClass('board__dividergap')).length).toBe(0);
});

test('Pool mode draws no divider — its rows are days of ONE pool, not two groups (I4)', () => {
  // The week MUST have an open day followed by a shut one, or this test cannot fail: the
  // committed `swim_week_oerlikon.json` has options on all seven days, so `dividerIndex` would
  // answer null whatever the mode guard did. Pool mode focuses the week on ONE pool
  // (`appdata.focusWeekOnPool`), so a day that pool is shut yields `options: []` — against the
  // shipped store for week 2026-08-10 that is Bungertwies [4,4,4,2,0,0,2], Riedtli [2,0,0,1,0,
  // 0,0], Tannenrauch [1,1,2,0,2,0,0] and Aemtler [3,0,0,2,2,0,0]. Each would otherwise draw
  // "No sessions published today" across the middle of one pool's own week, which says nothing
  // true: these rows are DAYS, and Thursday is not a different pool from Monday.
  const week: BoardWeek = {
    facility: 'Hallenbad Bungertwies',
    days: [
      { label: 'Mon', iso: '2026-08-10', answer: { options: [opt('Hallenbad Bungertwies', 'bungertwies-25m', '25m')], statuses: [] } },
      { label: 'Tue', iso: '2026-08-11', answer: { options: [], statuses: [{ facility: 'Hallenbad Bungertwies', status: 'closed' }] } },
      { label: 'Wed', iso: '2026-08-12', answer: { options: [opt('Hallenbad Bungertwies', 'bungertwies-25m', '25m')], statuses: [] } },
    ],
  };
  // The guard is load-bearing precisely because this is NOT null.
  expect(dividerIndex(weekRows(week))).toBe(1);

  const el = mount();
  createBoard(el, {
    data: { week },
    filter: { mode: 'pool', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  expect(el.queryAll(hasClass('board__divider')).length).toBe(0);
  expect(el.queryAll(hasClass('board__dividergap')).length).toBe(0);
  // …and the shut Tuesday stays IN THE MIDDLE of the week: week rows are never regrouped.
  expect(weekRows(week).map((r) => r.label)).toEqual(['Mon', 'Tue', 'Wed']);
  expect(el.queryAll(hasClass('board__rowname')).map((n) => n.textContent)).toEqual([
    'Mon · 10 Aug',
    'Tue · 11 Aug',
    'Wed · 12 Aug',
  ]);
});

// --- board-order-and-defects S3: the owner name renders (height is the fix) ----------
//
// [[lane-stack-board]] shipped `ROW_H = 46` AND "the owner is written inside its lane
// block". From five lanes up those two are arithmetically incompatible, so the owner
// rendered on NO real Zürich basin — City has 6 lanes, Oerlikon 8. The fix is the row's
// HEIGHT, which is the only free variable: `laneBands` divides `h * 0.8` between the lanes.

/** An option with a `lane_day_view` of `lanes` lanes, the last two held by a named club.
 *  The strips span the option's OWN window (`laneStackFor` clips the day view to the
 *  session, so a plan written over some other hours would arrive as empty lanes). */
const laneOpt = (lanes: number, extra: Record<string, unknown> = {}) => {
  const start = typeof extra.start === 'string' ? extra.start : '09:00';
  const end = typeof extra.end === 'string' ? extra.end : '12:00';
  return {
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
    basin: 'Schwimmerbecken',
    access: 'PublicSwim',
    start,
    end,
    lane_day_view: {
      weekday: 2,
      lane_count: lanes,
      strips: Array.from({ length: lanes }, (_, i) => ({
        lane: i + 1,
        segments: [
          i + 2 < lanes
            ? { start, end, access: 'PublicSwim', owner: null }
            : { start, end, access: 'ClubReserved', owner: 'SC Uster' },
        ],
      })),
    },
    ...extra,
  };
};

const stackRow = (lanes: number, extra: Record<string, unknown> = {}): BoardRow => ({
  label: 'Hallenbad City',
  facility: 'Hallenbad City',
  basin_id: 'city-50m',
  options: [laneOpt(lanes, extra)],
  statuses: [],
});

test('AC2 · rowHeight is max(46, 10 × lanes) — the floor holds to 4 lanes, then it grows', () => {
  // Every case, n = 1..10, spelled out rather than recomputed from the same formula the
  // implementation uses: a test that re-derives `10 * n` cannot catch `10` becoming 9 or 11.
  const heights = Array.from({ length: 10 }, (_, i) => rowHeight(stackRow(i + 1)));
  expect(heights).toEqual([46, 46, 46, 46, 50, 60, 70, 80, 90, 100]);
  // The four real shapes, named: this is the table the plan was approved on.
  expect(rowHeight(stackRow(8))).toBe(80); // Oerlikon 50m
  expect(rowHeight(stackRow(6))).toBe(60); // City Schwimmerbecken
  expect(rowHeight(stackRow(5))).toBe(50); // Bläsi 25m, Leimbach 25m
  expect(rowHeight(stackRow(4))).toBe(46); // Bungertwies, Käferberg — unchanged
  expect(rowHeight(stackRow(2))).toBe(46); // Oerlikon Sprungbecken — unchanged
});

test('AC2 · a row with no lane plan keeps ROW_H — 46, byte-identical to before', () => {
  const plain: BoardRow = {
    label: 'Hallenbad City',
    facility: 'Hallenbad City',
    options: [opt('Hallenbad City', 'city-50m', 'Schwimmerbecken')],
    statuses: [],
  };
  expect(rowHeight(plain)).toBe(46);
  expect(rowHeight(closedRow('Seebad Utoquai'))).toBe(46);
  expect(rowHeight({ label: 'x', facility: 'x', options: [], statuses: [] })).toBe(46);
  // ~50 of 57 pools will never have a lane plan. The board they see must not move at all.
  for (const row of dayRows(DAY).filter((r) => !r.options.some((o) => o.lane_day_view))) {
    expect(rowHeight(row)).toBe(46);
  }
});

test('AC2 · rowHeight is PURE: same row, same answer, and the row is not touched', () => {
  const row = stackRow(6);
  const before = JSON.stringify(row);
  expect(rowHeight(row)).toBe(rowHeight(row));
  expect(JSON.stringify(row)).toBe(before);
});

test('the height is read from the ribbons the row PAINTS, never from its raw options', () => {
  // `optionRibbon` refuses to build a stack for a session with no hours (invariant I5) and
  // falls back to the "not published" ribbon. A height derived from `option.lane_day_view`
  // instead would grow this row to 80px and then paint a 46px-worth hatch in it — a hole
  // in the board explained by nothing. Same row, same lane_day_view, no hours.
  const noHours = stackRow(8, { start: undefined, end: undefined });
  expect(noHours.options[0].lane_day_view).toBeTruthy();
  expect(rowHeight(noHours)).toBe(46);
  // …and with the hours present it is the one that grows, so the difference is the HOURS.
  expect(rowHeight(stackRow(8))).toBe(80);
});

test('a row with two plan-bearing sessions is sized by the TALLEST stack, not the first', () => {
  // A row is a BASIN, and a basin's day carries as many sessions as the city publishes —
  // the committed answer gives Hallenbad Oerlikon two, both 8-lane. They need not agree:
  // a morning block on 4 lanes and an afternoon one on the full 8 is one row that has to
  // hold 8 bands. Sized by the first (or the last) it would clip half the plan.
  const twoSessions: BoardRow = {
    label: 'Hallenbad City',
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
    options: [laneOpt(4, { start: '06:00', end: '09:00' }), laneOpt(8, { start: '09:00', end: '12:00' })],
    statuses: [],
  };
  expect(rowHeight(twoSessions)).toBe(80);
  // …and the same row with the sessions the other way round answers the same.
  expect(rowHeight({ ...twoSessions, options: [...twoSessions.options].reverse() })).toBe(80);
});

test('the height follows the PAINTER\'s dispatch — only a lanestack ribbon carries a lane count', () => {
  // `stackLaneCount` gates on `variant === 'lanestack'`, the very key `drawRibbons`
  // dispatches on, and only then reads `lane_count`. Today the gate is REDUNDANT: the stack
  // branch of `optionRibbon` is the only one that emits a `lane_count`, so deleting it
  // changes no answer and no test could kill that mutant through `rowHeight` — the same
  // shape of hole S2 hit with `groupByOpenToday`. So the identity it is redundant under is
  // asserted directly instead of left implicit. The day a `lanes` ribbon hoists its
  // `segments[].lane_count` to the top level, this reddens and the gate starts carrying
  // weight — a counts-only ribbon draws ONE body about the mid-line and must NOT grow a row.
  const shapes = [
    laneOpt(6), // → lanestack
    opt('P', 'p-1', 'b', {
      lane_timeline: { segments: [{ start: '09:00', end: '12:00', lane_count: 6, public_lanes: 3, reserved_lanes: 3 }] },
    }), // → lanes
    opt('P', 'p-1', 'b'), // → unpublished
  ];
  const ribbons = ribbonsFor({
    options: shapes,
    statuses: [{ facility: 'P', status: 'closed' }, { facility: 'P', status: 'no_source' }],
  });
  expect(ribbons.map((r) => r.variant)).toEqual([
    'closed',
    'ghost',
    'lanestack',
    'lanes',
    'unpublished',
  ]);
  for (const r of ribbons) {
    expect('lane_count' in r, `${String(r.variant)} carries a lane_count`).toBe(
      r.variant === 'lanestack',
    );
  }
});

test('the grown height is exactly what a LEGIBLE BAND needs — no more, no less', () => {
  // SUPERSEDED IN ITS REASON, not its arithmetic. As shipped this was "the grown height is
  // exactly what the owner-label gate needs" and measured against `OWNER_LABEL_MIN_H` — the
  // height a club name needed to be set in type inside its block. The board no longer writes
  // owner names (the DetailPanel's Gantt does; the stack is text-free), so that gate is gone
  // and with it the constant. The row height STAYS, re-founded on `LANE_BAND_MIN_H`: the
  // shortest a band may be and still read as its own lane rather than one stripe of a hatch.
  //
  // The two constants are still set in two different files (`rowHeight`'s 10 here,
  // `STACK_BOX`/`LANE_BAND_MIN_H` in ribbonrender.ts) and only agree by arithmetic:
  // band = h·0.8/n − 1 ≥ 7 ⟺ h ≥ 10n. Moving one without the other silently shrinks the
  // bands back to mush, so the relation is asserted rather than written in a comment.
  for (let n = 1; n <= 12; n += 1) {
    const h = rowHeight(stackRow(n));
    const band = laneBands(n, h / 2, h)[0];
    expect(band.height, `${n} lanes at ${h}px`).toBeGreaterThanOrEqual(LANE_BAND_MIN_H);
  }
  // And the counterfactual that makes the growth load-bearing: at the old fixed 46 a
  // five-lane band is 6.36px and a six-lane one 5.13. That is the row the user was reading.
  expect(laneBands(5, 23, 46)[0].height).toBeLessThan(LANE_BAND_MIN_H);
  expect(laneBands(6, 23, 46)[0].height).toBeLessThan(LANE_BAND_MIN_H);
  expect(laneBands(8, 23, 46)[0].height).toBeLessThan(LANE_BAND_MIN_H);
});

test('AC3/H1 · every label cell is exactly as tall as its own canvas, at MIXED heights', () => {
  // The real desync risk under variable height is NOT the x-mapping (`ts.X` takes no height,
  // and the cursor routes through the shared `cursorX`, so a test on those is vacuous by
  // construction). It is column 1 drifting from column 2: the label stack and the canvas
  // track are PARALLEL lists rendered into two scroll boxes, so one cell that is a different
  // height from its twin shifts every row below it against the wrong pool's ribbons.
  const day: BoardAnswer = {
    options: [
      laneOpt(8, { facility: 'Hallenbad Oerlikon', basin_id: 'oerlikon-50m' }), // 80
      laneOpt(6), // City — 60
      opt('Hallenbad Bungertwies', 'bungertwies-25m', '25m'), // no plan — 46
    ],
    statuses: [{ facility: 'Seebad Utoquai', status: 'closed' }], // 46, below the divider
  };
  const el = mount();
  createBoard(el, {
    data: { day },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  const labelsBody = must(el.query(hasClass('board__labelsbody')), 'labels body');
  const trackBody = must(el.query(hasClass('board__trackbody')), 'track body');
  expect(labelsBody.children.length).toBe(trackBody.children.length);
  // The divider is in BOTH columns (S2), so the two lists stay index-aligned and the pair
  // at the boundary is compared like any other — its two cells are the one place where the
  // equality was previously unpinned (both read DIVIDER_H, and nothing said they must).
  expect(labelsBody.children.length).toBe(5); // 3 open rows + divider + 1 closed row
  const heights = labelsBody.children.map((c) => c.style.height);
  expect(heights).toEqual(['80px', '60px', '46px', '22px', '46px']);
  // MIXED — an all-46 board would make every assertion below true for the wrong reason.
  expect(new Set(heights).size).toBeGreaterThan(1);
  // …and each row cell is the height `rowHeight` answers for ITS row, so the exported pure
  // function and the one the DOM is actually built from cannot drift apart.
  expect(heights.filter((_, i) => i !== 3)).toEqual(
    dayRows(day).map((r) => `${rowHeight(r)}px`),
  );
  for (const [i, label] of labelsBody.children.entries()) {
    const twin = trackBody.children[i];
    expect(twin.style.height, `column 2 cell ${i}`).toBe(label.style.height);
    // The canvas' INTRINSIC height is the third copy of the same number: a canvas sized in
    // CSS but not in pixels would rescale the ribbon rather than move it.
    if (twin.tagName === 'CANVAS') expect(`${intrinsic(twin).height}px`).toBe(label.style.height);
  }
  // The divider pair, named: a separator for assistive tech in column 1, and a silent
  // spacer in column 2 (the boundary is a fact about the LIST, not about a time of day).
  expect(labelsBody.children[3].attributes.role).toBe('separator');
  expect(trackBody.children[3].attributes['aria-hidden']).toBe('true');
  expect(trackBody.children[3].attributes.role).toBe(undefined);
  // H1: taller rows do not move the shared timescale. The axis header keeps its own height
  // and the plot its width, so no mark moves sideways.
  const axis = must(el.query(hasClass('board__axiscanvas')), 'axis canvas');
  expect(intrinsic(axis).height).toBe(20);
  expect(axis.style.width).toBe(`${BOARD_PLOT}px`);
  for (const canvas of el.queryAll(hasClass('board__canvas'))) {
    expect(intrinsic(canvas).width).toBe(BOARD_PLOT);
  }
});

test('AC3 · a rebuild re-derives every height — a filter change cannot strand a tall row', () => {
  // `buildRows` runs again on setFilter/setData with a fresh `h` per row. If the height were
  // captured once at mount, switching filters would leave 80px labels beside 46px canvases.
  const el = mount();
  const board = createBoard(el, {
    data: { day: { options: [laneOpt(8), opt('Hallenbad Bungertwies', 'b-25m', '25m')], statuses: [] } },
    filter: { mode: 'day', gender: '', age: null },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => {},
  });
  board.setData({ day: { options: [opt('Hallenbad Bungertwies', 'b-25m', '25m'), laneOpt(6)], statuses: [] } });
  const labelsBody = must(el.query(hasClass('board__labelsbody')), 'labels body');
  const trackBody = must(el.query(hasClass('board__trackbody')), 'track body');
  expect(labelsBody.children.map((c) => c.style.height)).toEqual(['46px', '60px']);
  expect(trackBody.children.map((c) => c.style.height)).toEqual(['46px', '60px']);
  expect(trackBody.children.map((c) => intrinsic(c).height)).toEqual([46, 60]);
});
