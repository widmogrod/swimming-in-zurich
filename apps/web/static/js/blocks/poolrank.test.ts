import { expect, test } from 'vitest';

import {
  countOpenToYou,
  isPartlyReserved,
  laneSplitAt,
  optionAt,
  optionNext,
  rankRows,
  rowKey,
  terminalStatus,
  tierCounts,
  tierFor,
  verdictFor,
  type RankRow,
} from './poolrank.js';

const M = (h: number, m = 0) => h * 60 + m;

function opt(start: string, end: string, extra: Record<string, unknown> = {}) {
  return { start, end, facility: 'X', ...extra };
}

/** A pool open 09:00–21:00 with a published split that reserves lanes 12:00–13:30. */
function city(): RankRow {
  return {
    label: 'Hallenbad City',
    options: [
      opt('09:00', '21:00', {
        distance_km: 0.9,
        lane_timeline: {
          segments: [
            { start: '09:00', end: '12:00', lane_count: 6, public_lanes: 6 },
            { start: '12:00', end: '13:30', lane_count: 6, public_lanes: 2 },
            { start: '13:30', end: '21:00', lane_count: 6, public_lanes: 6 },
          ],
        },
      }),
    ],
    statuses: [],
  };
}

const closed: RankRow = { label: 'Seebad Utoquai', options: [], statuses: [{ status: 'closed' }] };
const uncurated: RankRow = { label: 'Flussbad', options: [], statuses: [{ status: 'awaiting_scrape' }] };
/** Hours published, but no lane split at all — a real, distinct state. */
const lake: RankRow = {
  label: 'Seebad Enge',
  options: [opt('09:00', '20:00', { distance_km: 1.6 })],
  statuses: [],
};

test('optionAt is half-open: the end minute belongs to the NEXT session', () => {
  const options = [opt('09:00', '12:00'), opt('12:00', '15:00')];
  expect(optionAt(options, M(11, 59))?.end).toBe('12:00');
  expect(optionAt(options, M(12))?.end).toBe('15:00');
  expect(optionAt(options, M(8))).toBeNull();
  expect(optionAt(options, M(15))).toBeNull();
});

test('optionNext returns the SOONEST later session, not the first listed', () => {
  const options = [opt('18:00', '20:00'), opt('14:00', '16:00')];
  expect(optionNext(options, M(10))?.start).toBe('14:00');
  expect(optionNext(options, M(16))?.start).toBe('18:00');
  expect(optionNext(options, M(21))).toBeNull();
});

test('laneSplitAt reads the segment covering the minute', () => {
  const o = city().options![0];
  expect(laneSplitAt(o, M(10))).toEqual({ public_lanes: 6, lane_count: 6 });
  expect(laneSplitAt(o, M(12, 30))).toEqual({ public_lanes: 2, lane_count: 6 });
});

test('no published timeline is null, NOT a zero split', () => {
  // The difference is the whole point: zero lanes public is a claim, "not published" is
  // an absence. Collapsing them would invent data.
  expect(laneSplitAt(lake.options![0], M(10))).toBeNull();
  expect(laneSplitAt(null, M(10))).toBeNull();
  const zeroLanes = opt('09:00', '10:00', {
    lane_timeline: { segments: [{ start: '09:00', end: '10:00', lane_count: 0, public_lanes: 0 }] },
  });
  expect(laneSplitAt(zeroLanes, M(9, 30))).toBeNull();
});

test('isPartlyReserved is exactly "some lanes held back"', () => {
  expect(isPartlyReserved({ public_lanes: 2, lane_count: 6 })).toBe(true);
  expect(isPartlyReserved({ public_lanes: 6, lane_count: 6 })).toBe(false);
  expect(isPartlyReserved(null)).toBe(false);
});

test('terminalStatus prefers closed over uncurated', () => {
  expect(terminalStatus(closed)).toBe('closed');
  expect(terminalStatus(uncurated)).toBe('unknown');
  expect(terminalStatus({ label: 'x', statuses: [{ status: 'closed' }, { status: 'awaiting_scrape' }] }))
    .toBe('closed');
  expect(terminalStatus(city())).toBeNull();
});

test('tierFor: open now vs later vs the two terminal states', () => {
  expect(tierFor(city(), M(10))).toBe('now');
  expect(tierFor(city(), M(7))).toBe('soon');
  expect(tierFor(closed, M(10))).toBe('closed');
  expect(tierFor(uncurated, M(10))).toBe('unknown');
});

test('a pool whose sessions have all ended is not filed under "later today"', () => {
  // The original bug: tierFor said `soon` for any row with options and none current, so a
  // finished pool rendered as "Later today / Done for today" — the heading contradicting
  // the verdict directly beneath it. The tier and the verdict must agree.
  expect(tierFor(city(), M(22))).toBe('closed');
  expect(verdictFor(city(), M(22)).key).toBe('mobile.verdict.doneForToday');
  // …and `soon` still means soon when something really is still to come.
  expect(tierFor(city(), M(7))).toBe('soon');
  expect(verdictFor(city(), M(7)).key).toBe('mobile.verdict.opensAt');
});

test('a pool with hours but NO lane split still ranks by its hours', () => {
  // It is open; we simply cannot say how many lanes are yours. Demoting it to `unknown`
  // would hide an open pool behind a data gap.
  expect(tierFor(lake, M(10))).toBe('now');
});

test('reserved lanes read "Partly reserved", never "Open now"', () => {
  const v = verdictFor(city(), M(12, 30));
  expect(v.key).toBe('mobile.verdict.partlyReserved');
  expect(v.tailKey).toBe('mobile.lanesUntil');
  expect(v.tailParams).toMatchObject({ public: 2, total: 6 });
});

test('a fully public session reads "Open now"', () => {
  const v = verdictFor(city(), M(10));
  expect(v.key).toBe('mobile.verdict.openNow');
  expect(v.tailParams).toMatchObject({ hhmm: '21:00' });
});

test('before opening it reads when it opens; after closing, done for today', () => {
  expect(verdictFor(city(), M(7)).key).toBe('mobile.verdict.opensAt');
  expect(verdictFor(city(), M(7)).params).toMatchObject({ hhmm: '09:00' });
  expect(verdictFor(city(), M(22)).key).toBe('mobile.verdict.doneForToday');
});

test('closed is not the same as not-for-you', () => {
  // A pool shut for maintenance must not blame the swimmer.
  expect(verdictFor(closed, M(10)).key).toBe('mobile.verdict.closedAllDay');
  expect(verdictFor(uncurated, M(10)).key).toBe('mobile.verdict.hoursUnknown');
});

test('an ineligible session says when it becomes yours', () => {
  const women: RankRow = {
    label: 'Bungertwies',
    options: [opt('09:00', '11:00', { eligible: false }), opt('11:00', '20:00')],
  };
  const v = verdictFor(women, M(10));
  expect(v.key).toBe('mobile.verdict.notYoursUntil');
  expect(v.params).toMatchObject({ hhmm: '11:00' });
});

test('rankRows groups by tier first, then nearest', () => {
  const far = { ...city(), label: 'Far' };
  far.options = [{ ...city().options![0], distance_km: 5.2 }];
  const ranked = rankRows([closed, far, city(), uncurated], M(10));
  expect(ranked.map((r) => r.row.label)).toEqual([
    'Hallenbad City', // now, 0.9 km
    'Far', // now, 5.2 km
    'Flussbad', // unknown
    'Seebad Utoquai', // closed
  ]);
});

test('a missing distance sorts LAST within its tier, never first', () => {
  const noKm: RankRow = { label: 'Nowhere', options: [opt('09:00', '21:00')] };
  const ranked = rankRows([noKm, city()], M(10));
  expect(ranked.map((r) => r.row.label)).toEqual(['Hallenbad City', 'Nowhere']);
});

test('"open to you" excludes partly-reserved sessions', () => {
  // The count is a promise; a session holding lanes back is not one.
  expect(countOpenToYou(rankRows([city()], M(10)))).toBe(1);
  expect(countOpenToYou(rankRows([city()], M(12, 30)))).toBe(0);
});

test('"open to you" counts DISTINCT POOLS, so a two-basin pool contributes 1', () => {
  // The phone bar leads with this number ("{count} open to you now"). Since S3 a row is
  // one BASIN, so a pool publishing two lane basins yields two rows — counting rows would
  // promise two swims in one building.
  const basin = (basin_id: string): RankRow => ({
    label: `Hallenbad City \u00b7 ${basin_id}`,
    facility: 'Hallenbad City',
    basin_id,
    options: [opt('09:00', '21:00', { distance_km: 0.9 })],
    statuses: [],
  });
  expect(countOpenToYou(rankRows([basin('city-main'), basin('city-50m')], M(10)))).toBe(1);
  // Two DIFFERENT pools still count two.
  const other: RankRow = {
    label: 'Hallenbad Bl\u00e4si',
    facility: 'Hallenbad Bl\u00e4si',
    basin_id: 'blaesi-25m',
    options: [opt('09:00', '21:00', { distance_km: 2.1 })],
    statuses: [],
  };
  expect(countOpenToYou(rankRows([basin('city-main'), basin('city-50m'), other], M(10)))).toBe(2);
});

test('rowKey is facility + basin, and never collapses two basins of one pool', () => {
  const a: RankRow = { label: 'X', facility: 'Hallenbad City', basin_id: 'city-main' };
  const b: RankRow = { label: 'X', facility: 'Hallenbad City', basin_id: 'city-50m' };
  expect(rowKey(a)).not.toBe(rowKey(b));
  // The LABEL is not part of it: relabelling a row (which rule L1 does, per answer) must
  // not change its identity.
  expect(rowKey({ ...a, label: 'Hallenbad City \u00b7 Hauptbecken' })).toBe(rowKey(a));
  // A status-only row (no basin) is keyed by its facility alone.
  expect(rowKey({ label: 'Seebad Utoquai', facility: 'Seebad Utoquai' })).toBe(
    rowKey({ label: 'anything', facility: 'Seebad Utoquai' }),
  );
});

test('"open to you" excludes ineligible, closed and unlisted rows', () => {
  const women: RankRow = { label: 'W', options: [opt('09:00', '11:00', { eligible: false })] };
  expect(countOpenToYou(rankRows([women, closed, uncurated], M(10)))).toBe(0);
});

test('tierCounts reports every tier, including the empty ones', () => {
  expect(tierCounts(rankRows([city(), closed], M(10)))).toEqual({
    now: 1,
    soon: 0,
    unknown: 0,
    closed: 1,
  });
});
