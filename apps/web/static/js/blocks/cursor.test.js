import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { makeTimescale } from '../timescale.js';
import {
  hhmmToMin,
  minToHhmm,
  cursorX,
  publicAt,
  peakPublic,
  basinFromPanel,
  panelForBasin,
} from './cursor.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

const POOL = load('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0]); // 50m-Becken, 8 lanes

test('hhmmToMin / minToHhmm round-trip', () => {
  assert.equal(hhmmToMin('06:00'), 360);
  assert.equal(hhmmToMin('09:30'), 570);
  assert.equal(minToHhmm(360), '06:00');
  assert.equal(minToHhmm(570), '09:30');
});

test('cursorX is exactly the timescale mapping (the ONE mapping both renderers use)', () => {
  const ts = makeTimescale(6, 22, 900);
  for (const min of [360, 480, 570, 600, 780, 1200]) {
    assert.equal(cursorX(ts, min), ts.X(min));
  }
});

test('basinFromPanel projects a /pools/{id} lane_panel into the canonical basin', () => {
  assert.equal(BASIN.lane_count, POOL.lane_panels[0].panel.day_view.lane_count);
  assert.equal(BASIN.strips.length, POOL.lane_panels[0].panel.day_view.strips.length);
  assert.ok(BASIN.best_public);
});

test('publicAt counts only PublicSwim lanes covering the minute (reserved/gaps do not count)', () => {
  // A synthetic basin: lane 1 public 06:00–08:00; lane 2 reserved 06:00–08:00.
  const basin = {
    lane_count: 2,
    strips: [
      { lane: 1, segments: [{ start: '06:00', end: '08:00', access: 'PublicSwim', owner: null }] },
      { lane: 2, segments: [{ start: '06:00', end: '08:00', access: 'ClubReserved', owner: 'X' }] },
    ],
  };
  assert.deepEqual(publicAt(basin, hhmmToMin('07:00')), { public: 1, total: 2 });
  // A gap (no segment) is not public.
  assert.deepEqual(publicAt(basin, hhmmToMin('09:00')), { public: 0, total: 2 });
  // End is exclusive: exactly 08:00 is no longer inside 06:00–08:00.
  assert.deepEqual(publicAt(basin, hhmmToMin('08:00')), { public: 0, total: 2 });
});

test('panelForBasin picks the clicked basin (not always lane_panels[0]) on a multi-basin facility', () => {
  const panels = [
    { basin_name: '50m-Becken', panel: {} },
    { basin_name: 'Lehrschwimmbecken', panel: {} },
  ];
  // The clicked option's basin resolves to ITS panel, not the first.
  assert.equal(panelForBasin(panels, 'Lehrschwimmbecken').basin_name, 'Lehrschwimmbecken');
  assert.equal(panelForBasin(panels, '50m-Becken').basin_name, '50m-Becken');
  // Unknown / missing basin name falls back to the first panel (never throws).
  assert.equal(panelForBasin(panels, 'Nonexistent').basin_name, '50m-Becken');
  assert.equal(panelForBasin(panels, null).basin_name, '50m-Becken');
  // No panels → null (openPanel already guards the empty case before calling).
  assert.equal(panelForBasin([], 'x'), null);
  assert.equal(panelForBasin(undefined, 'x'), null);
});

test('the real fixture has a cursor minute where public != peak (proves cursor ≠ peak matters)', () => {
  const peak = peakPublic(BASIN);
  assert.ok(peak > 0);
  // Scan every segment boundary; at least one carries fewer public lanes than the peak.
  const boundaries = new Set();
  for (const strip of BASIN.strips) for (const s of strip.segments) boundaries.add(hhmmToMin(s.start));
  const below = [...boundaries].filter((min) => publicAt(BASIN, min).public !== peak);
  assert.ok(below.length > 0, 'expected some minute whose public count differs from the peak');
});
