import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import type { InsightAnswer, InsightOption, InsightSegment } from './insightbar.js';
import { computeInsight, createInsightBar } from './insightbar.js';
import { mount } from '../components/_fakedom.js';
import { must } from '../testutil.js';
import type { FakeElement } from '../components/_fakedom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

// Recompute the expected best public window from a set of options — the SAME rule
// the block uses (max public_lanes, ties → earliest start), so the test can't drift.
function expectedBest(options: InsightOption[]): (InsightSegment & { facility?: string }) | null {
  let best: (InsightSegment & { facility?: string }) | null = null;
  for (const o of options) {
    for (const seg of (o.lane_timeline && o.lane_timeline.segments) || []) {
      if (
        best === null ||
        seg.public_lanes > must(best).public_lanes ||
        (seg.public_lanes === must(best).public_lanes && seg.start < must(best).start)
      ) {
        best = { facility: o.facility, ...seg };
      }
    }
  }
  return best;
}

test('Day insight: N distinct facilities with hours + the best public window', () => {
  const day = load<Required<InsightAnswer>>('swim_day.json');
  const distinct = new Set(day.options.map((o) => o.facility)).size;
  const best = expectedBest(day.options);
  const insight = computeInsight({ day }, { mode: 'day' });
  expect(insight.mode).toBe('day');
  expect(insight.poolsCount).toBe(distinct);
  expect(insight.text.includes(`${distinct} pools with curated hours nearby`)).toBeTruthy();
  // The best window is the max-public segment (8/8 at Oerlikon 09:30–10:00 in the fixture).
  expect(must(insight.best).public_lanes).toBe(must(best).public_lanes);
  expect(insight.text.includes(`${must(best).public_lanes}/${must(best).lane_count}`)).toBeTruthy();
  expect(insight.text.includes(String(must(best).facility))).toBeTruthy();
  expect(insight.text.includes(`${must(best).start}–${must(best).end}`)).toBeTruthy();
});

test('Day insight appends the honest closed / hours-not-listed coverage split (FIX 5)', () => {
  const day = load<Required<InsightAnswer>>('swim_day.json');
  const closed = day.statuses.filter((s) => s.status === 'closed').length;
  const unlisted = day.statuses.filter((s) => s.status === 'uncurated').length;
  expect(closed + unlisted > 0).toBeTruthy();
  const insight = computeInsight({ day }, { mode: 'day' });
  expect(insight.closed).toBe(closed);
  expect(insight.unlisted).toBe(unlisted);
  expect(insight.text.includes(`${closed} closed, ${unlisted} hours-not-listed nearby`)).toBeTruthy();
});

test('Day insight omits the coverage split when there are no statuses (one calm line)', () => {
  const day = { options: [{ facility: 'A', lane_timeline: null }], statuses: [] };
  const insight = computeInsight({ day }, { mode: 'day' });
  expect(!insight.text.includes('hours-not-listed nearby')).toBeTruthy();
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
  expect(insight.poolsCount).toBe(2);
  expect(insight.best).toBe(null);
  expect(insight.text.includes('2 pools with curated hours nearby')).toBeTruthy();
  expect(insight.text.includes('lane split not published')).toBeTruthy();
});

test('Day insight with zero pools says so (never a fabricated count)', () => {
  const insight = computeInsight({ day: { options: [], statuses: [] } }, { mode: 'day' });
  expect(insight.poolsCount).toBe(0);
  expect(insight.text.toLowerCase().includes('no pools')).toBeTruthy();
});

test('Pool insight: reliable public lanes + open-days count for the week', () => {
  const week = load<{ facility: string; days: { answer: Required<InsightAnswer> }[] }>(
    'swim_week_oerlikon.json',
  );
  const openDays = week.days.filter((d) => d.answer.options.length > 0).length;
  const best = expectedBest(week.days.flatMap((d) => d.answer.options));
  const insight = computeInsight({ week }, { mode: 'pool' });
  expect(insight.mode).toBe('pool');
  expect(insight.openDays).toBe(openDays);
  expect(insight.text.includes(String(week.facility))).toBeTruthy();
  expect(insight.text.includes(`open ${openDays} of 7 days`)).toBeTruthy();
  if (best) {
    expect(insight.text.includes(`up to ${must(best).public_lanes} of ${must(best).lane_count}`)).toBeTruthy();
  }
});

test('createInsightBar writes the summary text and is role=status/aria-live', () => {
  const el = mount();
  const day = load<Required<InsightAnswer>>('swim_day.json');
  const bar = createInsightBar(el, { data: { day }, filter: { mode: 'day' } });
  expect(el.getAttribute('role')).toBe('status');
  expect(el.getAttribute('aria-live')).toBe('polite');
  const line = must(el.query((c: FakeElement) => c.classList.contains('insight__line')));
  expect(line.textContent.includes('pools with curated hours nearby')).toBeTruthy();
  // update() re-renders for a new mode.
  const week = load<{ facility: string; days: { answer: Required<InsightAnswer> }[] }>(
    'swim_week_oerlikon.json',
  );
  bar.update({ week }, { mode: 'pool' });
  expect(line.textContent.includes(week.facility)).toBeTruthy();
});
