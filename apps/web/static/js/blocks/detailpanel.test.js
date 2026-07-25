import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, publicAt, peakPublic } from './cursor.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createGantt } from './gantt.js';
import { createDetailPanel } from './detailpanel.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

const POOL = load('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0]); // 50m-Becken, 8 lanes
const hasClass = (c) => (e) => e.classList.contains(c);
const newTs = () => makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
const SAMPLES = [360, 540, 600, 690, 780, 900, 1080, 1200];

// A cursor minute where the public count is NOT the day's peak (cursor-driven proof).
function belowPeakMinute() {
  const peak = peakPublic(BASIN);
  const boundaries = new Set();
  for (const strip of BASIN.strips) for (const s of strip.segments) boundaries.add(hhmmToMinLocal(s.start));
  return [...boundaries].find((min) => publicAt(BASIN, min).public !== peak);
}
function hhmmToMinLocal(hhmm) {
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
    assert.deepEqual(g.readoutAt(T), expected); // Gantt readout
    assert.deepEqual(p.headlineAt(T), expected); // panel headline
    assert.equal(g.readoutAt(T).public, p.headlineAt(T).public); // and they agree
  }
});

test('(b) the headline is CURSOR-driven, not PEAK-driven (the bug the prototype fixed)', () => {
  const ts = newTs();
  const peak = peakPublic(BASIN);
  const T = belowPeakMinute();
  assert.ok(T != null, 'fixture must have a minute below peak');
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts, cursorMin: T });
  const n = p.headlineAt(T).public;
  assert.equal(n, publicAt(BASIN, T).public);
  assert.notEqual(n, peak); // a peak-driven headline would (wrongly) show `peak` here
  // the rendered headline number reflects the cursor, and the pip count matches it
  const bignum = p.el.query(hasClass('detail__bignum'));
  assert.equal(bignum.textContent, String(n));
  assert.equal(p.el.queryAll((e) => e.classList.contains('detail__pip') && e.classList.contains('is-on')).length, n);
});

test('the panel reuses the S1 primitives (StatePill, LengthLanesBadge, EligibilityBadge)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), {
    detail: POOL,
    basin: BASIN,
    timescale: ts,
    filter: { gender: 'female', age: 30 },
  });
  assert.ok(p.el.query(hasClass('ui-statepill')));
  assert.ok(p.el.query(hasClass('ui-lenlanes')));
  assert.ok(p.el.query(hasClass('ui-eligbadge')));
});

test('(d) provenance is present, carrying the source', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  const prov = p.el.query(hasClass('ui-provstamp'));
  assert.ok(prov);
  assert.ok(prov.textContent.includes(POOL.provenance.source));
});

test('price shows "Not listed" when the facility has no price table', () => {
  const ts = newTs();
  const noPrice = { ...POOL, prices: null };
  const p = createDetailPanel(mount(), { detail: noPrice, basin: BASIN, timescale: ts });
  const priceRow = p.el
    .queryAll(hasClass('detail__fact'))
    .find((r) => r.textContent.startsWith('Price'));
  assert.ok(priceRow.textContent.includes('Not listed'));
});

test('busyness is always "Not available yet" (future, never faked)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  const row = p.el
    .queryAll(hasClass('detail__fact'))
    .find((r) => r.textContent.startsWith('Busyness'));
  assert.ok(row.textContent.includes('Not available yet'));
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
  assert.ok(p.el.query(hasClass('ui-statepill')), 'StatePill present');
  assert.ok(p.el.query(hasClass('ui-lenlanes')), 'length·lanes present');
  assert.ok(p.el.query(hasClass('ui-eligbadge')), 'eligibility present');
  assert.ok(p.el.query(hasClass('ui-provstamp')), 'provenance present');
  const facts = p.el.queryAll(hasClass('detail__fact'));
  assert.ok(facts.find((r) => r.textContent.startsWith('Distance')).textContent.includes('1.2 km'));
  assert.ok(facts.find((r) => r.textContent.startsWith('Busyness')).textContent.includes('Not available yet'));
  // The lane absence is a NOTE inside the populated panel — never the whole panel,
  // and there is NO Gantt to desync.
  const pill = p.el.query(hasClass('ui-statepill'));
  assert.ok(pill.textContent.includes('lane split not published'));
  const note = p.el.query(hasClass('detail__note'));
  assert.ok(note && note.textContent.toLowerCase().includes('no published lane plan'));
  assert.equal(p.gantt, null);
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
  const closedPill = closed.el.query(hasClass('ui-statepill'));
  assert.ok(closedPill.textContent.includes('Closed'));
  assert.ok(closed.el.query(hasClass('detail__note')).textContent.includes('Sommerpause'));

  const uncurated = createDetailPanel(mount(), {
    detail: POOL,
    basin: null,
    timescale: ts,
    state: 'uncurated',
  });
  const uncPill = uncurated.el.query(hasClass('ui-statepill'));
  assert.ok(uncPill.textContent.toLowerCase().includes('hours not listed'));
  assert.ok(uncurated.el.query(hasClass('detail__note')).textContent.toLowerCase().includes('not the same as closed'));
  // Both still carry facts + provenance (populated panels), and neither has a Gantt.
  assert.ok(closed.el.query(hasClass('ui-provstamp')) && uncurated.el.query(hasClass('ui-provstamp')));
  assert.equal(closed.gantt, null);
  assert.equal(uncurated.gantt, null);
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
  const head = p.el.query(hasClass('detail__head'));
  const btn = head.query(hasClass('detail__weekbtn'));
  assert.ok(btn, 'the week button is inside the panel header');
  assert.equal(btn.tagName, 'BUTTON');
  assert.ok(btn.textContent.toLowerCase().includes("week"));
  btn.dispatch('click');
  assert.equal(opened, 1);
});

test('the week button is absent when no onOpenWeek callback is given', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  assert.equal(p.el.query(hasClass('detail__weekbtn')), null);
});

// --- S2: the SourceStrip is wired into the panel in every state ---
const laneChips = (p) =>
  p.el.queryAll((e) => e.classList.contains('ui-sourcestrip__chip--lane'));
const officialChip = (p) =>
  p.el.query((e) => e.classList.contains('ui-sourcestrip__chip--official'));

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
  assert.ok(official, 'Official-page chip present');
  assert.equal(official.getAttribute('href'), 'https://official.example/oerlikon');
  const lanes = laneChips(p);
  assert.equal(lanes.length, 2, "oerlikon's two distinct PDFs → two lane chips");
  assert.deepEqual(
    lanes.map((c) => c.getAttribute('href')).sort(),
    POOL.basins.map((b) => b.lane_plan_url).sort(),
  );
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
  assert.equal(lanes.length, 1, 'only the selected basin contributes a lane chip');
  const selected = POOL.basins.find((b) => b.basin_id === BASIN.id);
  assert.equal(lanes[0].getAttribute('href'), selected.lane_plan_url);
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
  const chips = p.el.queryAll((e) => e.classList.contains('ui-sourcestrip__chip'));
  assert.equal(chips.length, 1);
  assert.ok(chips[0].classList.contains('ui-sourcestrip__chip--official'));
  assert.equal(chips[0].getAttribute('href'), 'https://official.example/somepool');
});

test('the panel embeds the LaneGantt on the SAME timescale instance (no desync possible)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  assert.ok(p.gantt);
  assert.equal(p.gantt.timescale, ts); // literally the same object
  assert.ok(p.el.query(hasClass('gantt')));
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
  assert.equal(p.el.query(hasClass('detail__title')).textContent, 'Freibad Heuried');
  assert.ok(p.el.query(hasClass('detail__facts')));
  // No per-lane headline for a basin-less panel, and no Gantt was built.
  assert.equal(p.el.query(hasClass('detail__headline')), null);
  assert.equal(p.gantt, null);
  // Water temp degrades honestly to "Not listed" (no basin to read a temperature from).
  const water = p.el.queryAll(hasClass('detail__factval')).map((e) => e.textContent);
  assert.ok(water.some((t) => t.includes('Not listed')));
  // The uncurated honesty note is present (location known, timetable not).
  assert.ok(p.el.query((e) => e.classList.contains('detail__note--uncurated')));
  // headlineAt is safe to call on a basin-less panel (returns the zero reading, no throw).
  assert.deepEqual(p.headlineAt(600), { public: 0, total: 0 });
});
