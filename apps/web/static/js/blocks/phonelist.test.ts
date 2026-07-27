import { expect, test } from 'vitest';

import { mount, type FakeElement } from '../components/_fakedom.js';
import { fake, must } from '../testutil.js';
import { createPoolList } from './poollist.js';
import { createPhoneBar, leadTag, stripDates } from './phonebar.js';
import type { RankRow } from './poolrank.js';

const M = (h: number, m = 0) => h * 60 + m;

const ROWS: RankRow[] = [
  {
    label: 'Hallenbad City',
    options: [
      {
        start: '09:00',
        end: '21:00',
        distance_km: 0.9,
        basin: '50m-Becken',
        lane_timeline: {
          segments: [{ start: '09:00', end: '21:00', lane_count: 6, public_lanes: 2 }],
        },
      },
    ],
    statuses: [],
  },
  { label: 'Seebad Utoquai', options: [], statuses: [{ status: 'closed' }] },
];

function build(nowMin: number | null = M(10)) {
  const el = mount();
  const api = createPoolList(el, { rows: ROWS, nowMin, reducedMotion: true });
  return { el: fake(el), api };
}

test('the list groups rows under named tiers, with a count', () => {
  const { el } = build();
  const groups = el.queryAll((c: FakeElement) => c.classList.contains('plist__group'));
  expect(groups.length).toBe(2); // now + closed
  expect(groups[0].textContent).toContain('1');
});

test('each card carries a day tail canvas labelled with its pool', () => {
  const { el } = build();
  const canvases = el.queryAll((c: FakeElement) => c.tagName === 'CANVAS');
  expect(canvases.length).toBe(2);
  expect(canvases[0].getAttribute('aria-label')).toBe('Hallenbad City');
  expect(canvases[0].getAttribute('role')).toBe('img');
});

test('a partly-reserved pool is not counted as open to you', () => {
  // City publishes 2 of 6 lanes public — open, but not a promise.
  expect(build().api.countOpenToYou()).toBe(0);
});

test('tapping a card expands it, and tapping again collapses', () => {
  const { el, api } = build();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  btn.click();
  expect(api.openLabel).toBe('Hallenbad City');
  const reopened = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  reopened.click();
  expect(api.openLabel).toBeNull();
});

test('the expanded card reports its state to assistive tech', () => {
  const { el } = build();
  must(el.query((c: FakeElement) => c.classList.contains('plist__btn'))).click();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  expect(btn.getAttribute('aria-expanded')).toBe('true');
});

test('setRows re-ranks and drops any open card', () => {
  const { el, api } = build();
  must(el.query((c: FakeElement) => c.classList.contains('plist__btn'))).click();
  api.setRows([ROWS[1]], M(10));
  expect(api.openLabel).toBeNull();
  expect(el.queryAll((c: FakeElement) => c.tagName === 'CANVAS').length).toBe(1);
});

// --- phone bar --------------------------------------------------------------------

test('the day strip offers yesterday through the week ahead', () => {
  const days = stripDates('2026-07-27');
  expect(days[0]).toBe('2026-07-26');
  expect(days.length).toBe(8);
  expect(days).toContain('2026-07-27');
});

test('"now" is claimed only on today', () => {
  // Otherwise the bar reads "0 open to you now" for a Saturday you are planning ahead for.
  const todayTag = leadTag(5, '2026-07-27', '2026-07-27');
  const otherTag = leadTag(5, '2026-08-01', '2026-07-27');
  expect(todayTag).not.toBe(otherTag);
  expect(todayTag).toContain('5');
  expect(otherTag).toContain('5');
});

test('the bar pins the summary and marks the selected day', () => {
  const el = mount();
  const bar = createPhoneBar(el, { props: { date: '2026-07-27', today: '2026-07-27' } });
  expect(fake(bar.summary).getAttribute('aria-expanded')).toBe('false');
  const sel = bar.dayButtons.filter((b) => b.getAttribute('aria-selected') === 'true');
  expect(sel.length).toBe(1);
});

test('the summary row IS the filter trigger', () => {
  const el = mount();
  const seen: boolean[] = [];
  const bar = createPhoneBar(el, {
    props: { date: '2026-07-27', today: '2026-07-27' },
    onToggleFilters: (open) => seen.push(open),
  });
  fake(bar.summary).click();
  expect(seen).toEqual([true]);
  expect(bar.filtersOpen).toBe(true);
  expect(fake(el).classList.contains('is-filtersopen')).toBe(true);
});

test('picking a day reports it and moves the selection', () => {
  const el = mount();
  const picked: string[] = [];
  const bar = createPhoneBar(el, {
    props: { date: '2026-07-27', today: '2026-07-27' },
    onDate: (iso) => picked.push(iso),
  });
  fake(bar.dayButtons[0]).click();
  expect(picked).toEqual(['2026-07-26']);
  const sel = bar.dayButtons.filter((b) => b.getAttribute('aria-selected') === 'true');
  expect(sel[0].dataset.date).toBe('2026-07-26');
});
