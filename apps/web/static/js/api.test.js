import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isoDate,
  shiftIso,
  mondayOf,
  weekDates,
  swimParams,
  swimUrl,
  poolUrl,
  fetchDay,
  fetchWeek,
  fetchPoolDetail,
  WEEKDAY_LABELS,
} from './api.js';

test('isoDate/shiftIso are UTC and never drift a day', () => {
  assert.equal(isoDate(new Date(Date.UTC(2026, 6, 23))), '2026-07-23');
  assert.equal(shiftIso('2026-07-23', 2), '2026-07-25');
  assert.equal(shiftIso('2026-07-01', -1), '2026-06-30'); // month underflow
});

test('mondayOf snaps to the ISO Monday (Mon=0)', () => {
  assert.equal(mondayOf('2026-07-23'), '2026-07-20'); // Thu → Mon
  assert.equal(mondayOf('2026-07-20'), '2026-07-20'); // Mon → itself
  assert.equal(mondayOf('2026-07-26'), '2026-07-20'); // Sun → the same Mon
});

test('weekDates yields the 7 Mon…Sun dates in order', () => {
  const dates = weekDates('2026-07-23');
  assert.deepEqual(dates, [
    '2026-07-20', '2026-07-21', '2026-07-22', '2026-07-23',
    '2026-07-24', '2026-07-25', '2026-07-26',
  ]);
  assert.equal(dates.length, WEEKDAY_LABELS.length);
});

test('swimParams: eligible_only is always false and place/gender/age are conditional', () => {
  const base = swimParams({ place: { lat: null, lon: null }, gender: '', age: null }, '2026-07-23');
  assert.equal(base.at, '2026-07-23T12:00');
  assert.equal(base.eligible_only, 'false');
  assert.ok(!('lat' in base) && !('lon' in base));
  assert.ok(!('gender' in base) && !('age' in base));

  const full = swimParams(
    { place: { lat: 47.37, lon: 8.54 }, gender: 'female', age: 34 },
    '2026-07-23',
  );
  assert.equal(full.lat, '47.37');
  assert.equal(full.lon, '8.54');
  assert.equal(full.gender, 'female');
  assert.equal(full.age, '34');
});

test('swimUrl encodes the params; a lone lat (no lon) is dropped', () => {
  const url = swimUrl({ place: { lat: 47.37, lon: null }, gender: 'male' }, '2026-07-23');
  assert.ok(url.startsWith('/swim?'));
  assert.ok(url.includes('at=2026-07-23T12%3A00'));
  assert.ok(url.includes('gender=male'));
  assert.ok(!url.includes('lat='), 'lat without lon must not be sent');
});

test('poolUrl carries the at moment only when a date is given', () => {
  assert.equal(poolUrl('hallenbad-oerlikon'), '/pools/hallenbad-oerlikon');
  assert.equal(
    poolUrl('a/b', '2026-07-23'),
    '/pools/a%2Fb?at=2026-07-23T12%3A00',
  );
});

// A tiny fake fetch so the thin wrappers exercise headless (no browser).
function fakeFetch(routes) {
  return async (url) => {
    if (url in routes) return { ok: true, json: async () => routes[url] };
    return { ok: false, json: async () => ({}) };
  };
}

test('fetchDay returns the answer; a non-ok response degrades to an empty answer', async () => {
  const filter = { place: { lat: null, lon: null } };
  const url = swimUrl(filter, '2026-07-23');
  const answer = { options: [{ facility: 'X' }], statuses: [], warnings: [], notices: [] };
  const ok = await fetchDay(filter, '2026-07-23', fakeFetch({ [url]: answer }));
  assert.deepEqual(ok.options, answer.options);
  const bad = await fetchDay(filter, '2026-07-23', fakeFetch({}));
  assert.deepEqual(bad, { options: [], statuses: [], warnings: [], notices: [] });
});

test('fetchWeek assembles the 7 weekday answers in Mon…Sun order', async () => {
  const filter = { place: { lat: null, lon: null }, pool: { value: 'oer', label: 'Oerlikon' } };
  const routes = {};
  for (const iso of weekDates('2026-07-23')) {
    routes[swimUrl(filter, iso)] = {
      options: [{ facility: 'Oerlikon', day: iso }],
      statuses: [],
      warnings: [],
      notices: [],
    };
  }
  const week = await fetchWeek(filter, '2026-07-23', fakeFetch(routes));
  assert.equal(week.facility, 'Oerlikon');
  assert.equal(week.days.length, 7);
  assert.deepEqual(
    week.days.map((d) => d.label),
    WEEKDAY_LABELS,
  );
  assert.equal(week.days[0].iso, '2026-07-20');
  assert.equal(week.days[0].answer.options[0].day, '2026-07-20');
});

test('fetchPoolDetail returns the detail or null on failure', async () => {
  const detail = { facility_id: 'x', lane_panels: [] };
  const ok = await fetchPoolDetail('x', '2026-07-23', fakeFetch({ [poolUrl('x', '2026-07-23')]: detail }));
  assert.deepEqual(ok, detail);
  const bad = await fetchPoolDetail('x', '2026-07-23', fakeFetch({}));
  assert.equal(bad, null);
});
