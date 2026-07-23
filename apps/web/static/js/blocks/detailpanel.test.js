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

test('the panel embeds the LaneGantt on the SAME timescale instance (no desync possible)', () => {
  const ts = newTs();
  const p = createDetailPanel(mount(), { detail: POOL, basin: BASIN, timescale: ts });
  assert.ok(p.gantt);
  assert.equal(p.gantt.timescale, ts); // literally the same object
  assert.ok(p.el.query(hasClass('gantt')));
});
