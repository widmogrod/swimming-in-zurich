import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { computeInsight, createInsightBar } from './insightbar.js';
import { mount } from '../components/_fakedom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

// Recompute the expected best public window from a set of options — the SAME rule
// the block uses (max public_lanes, ties → earliest start), so the test can't drift.
function expectedBest(options) {
  let best = null;
  for (const o of options) {
    for (const seg of (o.lane_timeline && o.lane_timeline.segments) || []) {
      if (
        best === null ||
        seg.public_lanes > best.public_lanes ||
        (seg.public_lanes === best.public_lanes && seg.start < best.start)
      ) {
        best = { facility: o.facility, ...seg };
      }
    }
  }
  return best;
}

test('Day insight: N distinct facilities with hours + the best public window', () => {
  const day = load('swim_day.json');
  const distinct = new Set(day.options.map((o) => o.facility)).size;
  const best = expectedBest(day.options);
  const insight = computeInsight({ day }, { mode: 'day' });
  assert.equal(insight.mode, 'day');
  assert.equal(insight.poolsCount, distinct);
  assert.ok(insight.text.includes(`${distinct} pools with curated hours nearby`));
  // The best window is the max-public segment (8/8 at Oerlikon 09:30–10:00 in the fixture).
  assert.equal(insight.best.public_lanes, best.public_lanes);
  assert.ok(insight.text.includes(`${best.public_lanes}/${best.lane_count}`));
  assert.ok(insight.text.includes(best.facility));
  assert.ok(insight.text.includes(`${best.start}–${best.end}`));
});

test('Day insight degrades honestly when no lane split is published', () => {
  const day = {
    options: [
      { facility: 'A', lane_timeline: null },
      { facility: 'B', lane_timeline: { segments: [] } },
    ],
    statuses: [],
  };
  const insight = computeInsight({ day }, { mode: 'day' });
  assert.equal(insight.poolsCount, 2);
  assert.equal(insight.best, null);
  assert.ok(insight.text.includes('2 pools with curated hours nearby'));
  assert.ok(insight.text.includes('lane split not published'));
});

test('Day insight with zero pools says so (never a fabricated count)', () => {
  const insight = computeInsight({ day: { options: [], statuses: [] } }, { mode: 'day' });
  assert.equal(insight.poolsCount, 0);
  assert.ok(insight.text.toLowerCase().includes('no pools'));
});

test('Pool insight: reliable public lanes + open-days count for the week', () => {
  const week = load('swim_week_oerlikon.json');
  const openDays = week.days.filter((d) => d.answer.options.length > 0).length;
  const best = expectedBest(week.days.flatMap((d) => d.answer.options));
  const insight = computeInsight({ week }, { mode: 'pool' });
  assert.equal(insight.mode, 'pool');
  assert.equal(insight.openDays, openDays);
  assert.ok(insight.text.includes(week.facility));
  assert.ok(insight.text.includes(`open ${openDays} of 7 days`));
  if (best) {
    assert.ok(insight.text.includes(`up to ${best.public_lanes} of ${best.lane_count}`));
  }
});

test('createInsightBar writes the summary text and is role=status/aria-live', () => {
  const el = mount();
  const day = load('swim_day.json');
  const bar = createInsightBar(el, { data: { day }, filter: { mode: 'day' } });
  assert.equal(el.getAttribute('role'), 'status');
  assert.equal(el.getAttribute('aria-live'), 'polite');
  const line = el.query((c) => c.classList.contains('insight__line'));
  assert.ok(line.textContent.includes('pools with curated hours nearby'));
  // update() re-renders for a new mode.
  const week = load('swim_week_oerlikon.json');
  bar.update({ week }, { mode: 'pool' });
  assert.ok(line.textContent.includes(week.facility));
});
