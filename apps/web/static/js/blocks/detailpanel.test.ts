import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import type { FakeElement } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, publicAt, peakPublic } from './cursor.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createGantt } from './gantt.js';
import { createDetailPanel } from './detailpanel.js';
import type { FacilityDetail } from './detailpanel.js';
import type { LanePanel } from './cursor.js';
import { fake, must } from '../testutil.js';


const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const POOL = load<FacilityDetail & { lane_panels: LanePanel[] }>('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0]); // 50m-Becken, 8 lanes
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);
const newTs = () => makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
const SAMPLES = [360, 540, 600, 690, 780, 900, 1080, 1200];

// A cursor minute where the public count is NOT the day's peak (cursor-driven proof).
function belowPeakMinute() {
  const peak = peakPublic(BASIN);
  const boundaries = new Set<number>();
  for (const strip of BASIN.strips) for (const s of strip.segments) boundaries.add(hhmmToMinLocal(s.start));
  return [...boundaries].find((min) => publicAt(BASIN, min).public !== peak);
}
function hhmmToMinLocal(hhmm: string) {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

test('(b) readout equality: panel headline == Gantt readout == publicAt for sampled cursors', () => {
  const ts = newTs();
  const g = createGantt(mount(), { basin: BASIN, timescale: ts });
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  for (const T of SAMPLES) {
    g.setCursor(T);
    p.setCursor(T);
    const expected = publicAt(BASIN, T);
    expect(g.readoutAt(T)).toEqual(expected); // Gantt readout
    expect(p.headlineAt(T)).toEqual(expected); // panel headline
    expect(g.readoutAt(T).public).toBe(p.headlineAt(T).public); // and they agree
  }
});

test('(b) the headline is CURSOR-driven, not PEAK-driven (the bug the prototype fixed)', () => {
  const ts = newTs();
  const peak = peakPublic(BASIN);
  const T = must(belowPeakMinute(), 'a below-peak minute');
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts, cursorMin: T });
  const n = p.headlineAt(T).public;
  expect(n).toBe(publicAt(BASIN, T).public);
  expect(n).not.toBe(peak); // a peak-driven headline would (wrongly) show `peak` here
  // the rendered headline number reflects the cursor, and the pip count matches it
  const bignum = must(fake(p.el).query(hasClass('detail__bignum')));
  expect(bignum.textContent).toBe(String(n));
  expect(fake(p.el).queryAll((e) => e.classList.contains('detail__pip') && e.classList.contains('is-on')).length).toBe(n);
});

test('the panel reuses the S1 primitives (StatePill, LengthLanesBadge, EligibilityBadge)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), {
    detail: POOL,
    basin: BASIN,
    timescale: ts,
    filter: { gender: 'female', age: 30 },
  });
  expect(must(fake(p.el).query(hasClass('ui-statepill')))).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('ui-lenlanes')))).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('ui-eligbadge')))).toBeTruthy();
});

test('(d) provenance is present, carrying the source', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  const prov = must(fake(p.el).query(hasClass('ui-provstamp')));
  expect(prov).toBeTruthy();
  expect(prov.textContent.includes(String(POOL.provenance?.source))).toBeTruthy();
});

test('price shows "Not listed" when the facility has no price table', () => {
  const ts = newTs();
  const noPrice = { ...POOL, prices: null };
  const p = createDetailPanel(mount(), { detail: noPrice, basin: BASIN, timescale: ts });
  const priceRow = p.el
    .queryAll(hasClass('detail__fact'))
    .find((r: FakeElement) => r.textContent.startsWith('Price'));
  expect(must(priceRow, 'Price row').textContent.includes('Not listed')).toBeTruthy();
});

test('busyness is always "Not available yet" (future, never faked)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  const row = p.el
    .queryAll(hasClass('detail__fact'))
    .find((r: FakeElement) => r.textContent.startsWith('Busyness'));
  expect(must(row, 'Busyness row').textContent.includes('Not available yet')).toBeTruthy();
});

test('(c) a pool with NO lane plan still renders the full facts block, not a dead line (FIX 3)', () => {
  const ts = newTs();
  // Aemtler-shaped: curated hours but no lane_panels (basin=null → lanes-unknown).
  const noPlan = { ...POOL, lane_panels: [] };
  const p = createDetailPanel(mount(), {
    detail: noPlan,
    basin: null,
    timescale: ts,
    accessTypes: ['LaneSwim'],
    distanceKm: 1.2,
  });
  // Facts + provenance are present (the panel is populated, never a bare message).
  expect(must(fake(p.el).query(hasClass('ui-statepill')))).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('ui-lenlanes')))).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('ui-eligbadge')))).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('ui-provstamp')))).toBeTruthy();
  const facts = fake(p.el).queryAll(hasClass('detail__fact'));
  expect(
    must(facts.find((r) => r.textContent.startsWith('Distance'))).textContent.includes('1.2 km'),
  ).toBeTruthy();
  expect(
    must(facts.find((r) => r.textContent.startsWith('Busyness'))).textContent.includes(
      'Not available yet',
    ),
  ).toBeTruthy();
  // The lane absence is a NOTE inside the populated panel — never the whole panel,
  // and there is NO Gantt to desync.
  const pill = must(fake(p.el).query(hasClass('ui-statepill')));
  expect(pill.textContent.includes('lane split not published')).toBeTruthy();
  const note = must(fake(p.el).query(hasClass('detail__note')));
  expect(note && note.textContent.toLowerCase().includes('no published lane plan')).toBeTruthy();
  expect(p.gantt).toBe(null);
});

test('closed / uncurated panels keep their honesty (FIX 3): closed reason kept, uncurated ≠ closed', () => {
  const ts = newTs();
  const closed = createDetailPanel(mount(), {
    detail: POOL,
    basin: null,
    timescale: ts,
    state: 'closed',
    reason: 'Sommerpause',
  });
  const closedPill = must(fake(closed.el).query(hasClass('ui-statepill')));
  expect(closedPill.textContent.includes('Closed')).toBeTruthy();
  expect(must(fake(closed.el).query(hasClass('detail__note'))).textContent.includes('Sommerpause')).toBeTruthy();

  const uncurated = createDetailPanel(mount(), {
    detail: POOL,
    basin: null,
    timescale: ts,
    state: 'uncurated',
  });
  const uncPill = must(fake(uncurated.el).query(hasClass('ui-statepill')));
  expect(uncPill.textContent.toLowerCase().includes('hours not listed')).toBeTruthy();
  expect(must(fake(uncurated.el).query(hasClass('detail__note'))).textContent.toLowerCase().includes('not the same as closed')).toBeTruthy();
  // Both still carry facts + provenance (populated panels), and neither has a Gantt.
  expect(must(fake(closed.el).query(hasClass('ui-provstamp'))) && must(fake(uncurated.el).query(hasClass('ui-provstamp')))).toBeTruthy();
  expect(closed.gantt).toBe(null);
  expect(uncurated.gantt).toBe(null);
});

// The Day→Pool continuity affordance: a header button that carries the selected pool
// into Pool view. Rendered ONLY when opts.onOpenWeek is supplied, inside the header,
// and invokes the callback on click (the app leaves selectedPool untouched so Pool view
// opens on the SAME pool).
test('onOpenWeek renders a header button that invokes the callback', () => {
  const ts = newTs();
  let opened = 0;
  const p = createDetailPanel(mount(), {
    detail: POOL,
    basin: BASIN,
    timescale: ts,
    onOpenWeek: () => {
      opened += 1;
    },
  });
  const head = must(fake(p.el).query(hasClass('detail__head')));
  const btn = must(head.query(hasClass('detail__weekbtn')));
  expect(btn).toBeTruthy();
  expect(btn.tagName).toBe('BUTTON');
  expect(btn.textContent.toLowerCase().includes("week")).toBeTruthy();
  btn.dispatch('click');
  expect(opened).toBe(1);
});

test('the week button is absent when no onOpenWeek callback is given', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  expect(fake(p.el).query(hasClass('detail__weekbtn'))).toBe(null);
});

// --- S2: the SourceStrip is wired into the panel in every state ---
const laneChips = (p: { el: FakeElement }) =>
  fake(p.el).queryAll((e) => e.classList.contains('ui-sourcestrip__chip--lane'));
const officialChip = (p: { el: FakeElement }) =>
  must(fake(p.el).query((e) => e.classList.contains('ui-sourcestrip__chip--official')));

test('S2: no selected basin → Official-page chip + BOTH distinct lane-plan PDFs (all-basins branch)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), {
    detail: POOL,
    basin: null,
    timescale: ts,
    accessTypes: ['LaneSwim'],
    officialUrl: 'https://official.example/oerlikon',
  });
  const official = officialChip(p);
  expect(official).toBeTruthy();
  expect(official.getAttribute('href')).toBe('https://official.example/oerlikon');
  const lanes = laneChips(p);
  expect(lanes.length).toBe(2);
  expect(lanes.map((c: FakeElement) => c.getAttribute('href')).sort()).toEqual((POOL.basins ?? []).map((b) => b.lane_plan_url).sort());
});

test('S2: WITH a selected basin → exactly that one basin lane-plan chip', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), {
    detail: POOL,
    basin: BASIN,
    timescale: ts,
    officialUrl: 'https://official.example/oerlikon',
  });
  const lanes = laneChips(p);
  expect(lanes.length).toBe(1);
  const selected = (POOL.basins ?? []).find((b) => b.basin_id === BASIN.id);
  expect(lanes[0].getAttribute('href')).toBe(must(selected, 'selected basin').lane_plan_url);
});

test('S2: uncurated panel (detail = {}) still shows the Official-page chip and nothing else', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), {
    detail: {},
    basin: null,
    timescale: ts,
    state: 'uncurated',
    officialUrl: 'https://official.example/somepool',
  });
  const chips = fake(p.el).queryAll((e) => e.classList.contains('ui-sourcestrip__chip'));
  expect(chips.length).toBe(1);
  expect(chips[0].classList.contains('ui-sourcestrip__chip--official')).toBeTruthy();
  expect(chips[0].getAttribute('href')).toBe('https://official.example/somepool');
});

test('the panel embeds the LaneGantt on the SAME timescale instance (no desync possible)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  expect(p.gantt).toBeTruthy();
  expect(must(p.gantt).timescale).toBe(ts); // literally the same object
  expect(must(fake(p.el).query(hasClass('gantt')))).toBeTruthy();
});

// --- S4: the facility-level LIVE water temperature (Baditicker), rendered honestly ---
const liveRow = (p: { el: FakeElement }) =>
  fake(p.el).queryAll(hasClass('detail__fact')).find((r: FakeElement) => r.textContent.startsWith('Live water'));

test('S4: a live reading with a temp shows "23 °C · measured N min ago" (Heuried-shaped)', () => {
  const detail = {
    ...POOL,
    live_water_temp: {
      available: true,
      celsius: 23,
      measured_at: '2026-07-25T20:39:00+02:00',
      age_min: 7,
      is_open: false,
      is_stale: false,
      source: 'baditicker',
      reason: null,
    },
  };
  const p = createDetailPanel(mount(), { detail, basin: null, state: 'uncurated' });
  const row = must(liveRow(p), 'Live water row');
  expect(row).toBeTruthy();
  expect(row.textContent.includes('23 °C')).toBeTruthy();
  expect(row.textContent.includes('measured 7 min ago')).toBeTruthy();
  // a fresh reading is NOT marked stale.
  expect(fake(p.el).query(hasClass('detail__live--stale'))).toBe(null);
});

test('S4: an empty feed cell reads "Not yet measured" (+ closed), never a number or 0', () => {
  const detail = {
    ...POOL,
    live_water_temp: {
      available: true,
      celsius: null, // open, but the feed cell is empty — a live answer, not unavailable
      measured_at: '2026-06-05T14:02:00+02:00',
      age_min: 99999,
      is_open: false,
      is_stale: true,
      source: 'baditicker',
      reason: null,
    },
  };
  const p = createDetailPanel(mount(), { detail, basin: null, state: 'uncurated' });
  const row = must(liveRow(p), 'Live water row');
  expect(row.textContent.includes('Not yet measured')).toBeTruthy();
  expect(row.textContent.includes('closed')).toBeTruthy();
  expect(!/°C/.test(row.textContent)).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('detail__live--muted')))).toBeTruthy();
});

test('S4: unavailable shows the reason and NEVER a stale number', () => {
  const detail = {
    ...POOL,
    live_water_temp: {
      available: false,
      celsius: null,
      measured_at: null,
      age_min: null,
      is_open: null,
      is_stale: null,
      source: null,
      reason: 'no baditicker key',
    },
  };
  const p = createDetailPanel(mount(), { detail, basin: null, state: 'uncurated' });
  const row = must(liveRow(p), 'Live water row');
  expect(row.textContent.includes('no baditicker key')).toBeTruthy();
  expect(!/°C/.test(row.textContent)).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('detail__live--muted')))).toBeTruthy();
});

test('S4: a stale reading (older than the freshness limit) is visibly marked', () => {
  const detail = {
    ...POOL,
    live_water_temp: {
      available: true,
      celsius: 22,
      measured_at: '2026-07-23T09:00:00+02:00',
      age_min: 3000, // ~2 days → past the 6h freshness limit
      is_open: true,
      is_stale: true,
      source: 'baditicker',
      reason: null,
    },
  };
  const p = createDetailPanel(mount(), { detail, basin: null, state: 'uncurated' });
  const row = must(liveRow(p), 'Live water row');
  expect(row.textContent.includes('22 °C')).toBeTruthy();
  expect(row.textContent.includes('measured 2 days ago')).toBeTruthy();
  expect(must(fake(p.el).query(hasClass('detail__live--stale')))).toBeTruthy();
});

test('S4: no live_water_temp block → the Live water row is simply omitted', () => {
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: newTs() });
  expect(liveRow(p)).toBe(undefined);
});

test('S1: a basin-less location-only detail (Heuried-shaped) renders without error', () => {
  // A universal-detail pool (S1): the `/pools/{id}` response carries name + location but an
  // EMPTY basins list. The panel must render its facts + the honest "uncurated" note without
  // throwing on the zero-basin facility (no basin, no timescale, no lane plan).
  const detail = {
    facility_id: 'freibad-heuried',
    facility_name: 'Freibad Heuried',
    address: '8055 Zürich',
    basins: [],
    features: [],
    lane_panels: [],
    prices: null,
    provenance: { curated: false, source: 'catalog', valid_as_of: null },
  };
  const p = createDetailPanel(mount(), {
    detail,
    basin: null,
    state: 'uncurated',
    officialUrl: 'https://official.example/heuried',
  });
  // Title reflects the pool; the facts block rendered.
  expect(must(fake(p.el).query(hasClass('detail__title'))).textContent).toBe('Freibad Heuried');
  expect(must(fake(p.el).query(hasClass('detail__facts')))).toBeTruthy();
  // No per-lane headline for a basin-less panel, and no Gantt was built.
  expect(fake(p.el).query(hasClass('detail__headline'))).toBe(null);
  expect(p.gantt).toBe(null);
  // Water temp degrades honestly to "Not listed" (no basin to read a temperature from).
  const water = fake(p.el).queryAll(hasClass('detail__factval')).map((e) => e.textContent);
  expect(water.some((t) => t.includes('Not listed'))).toBeTruthy();
  // The uncurated honesty note is present (location known, timetable not).
  expect(must(fake(p.el).query((e) => e.classList.contains('detail__note--uncurated')))).toBeTruthy();
  // headlineAt is safe to call on a basin-less panel (returns the zero reading, no throw).
  expect(p.headlineAt(600)).toEqual({ public: 0, total: 0 });
});
