import { expect, test } from 'vitest';

import { mount, type FakeElement } from './_fakedom.js';
import { must } from '../testutil.js';
import { createSourceStrip } from './sourcestrip.js';

const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);
const chipsOf = (el: FakeElement) => el.queryAll(hasClass('ui-sourcestrip__chip'));

test('three distinct URLs → 3 new-tab links with exact href + honest aria-label', () => {
  const el = mount();
  createSourceStrip(el, {
    props: {
      officialUrl: 'https://official.example/pool',
      lanePlanUrls: ['https://plans.example/lane.pdf'],
      pricesUrl: 'https://prices.example/tariff',
    },
  });
  const chips = chipsOf(el);
  expect(chips.length).toBe(3);
  for (const c of chips) {
    expect(c.tagName).toBe('A');
    expect(c.getAttribute('target')).toBe('_blank');
    const rel = c.getAttribute('rel');
    expect(rel).toMatch(/noopener/);
    expect(rel).toMatch(/noreferrer/);
    expect(c.getAttribute('aria-label')).toMatch(/new tab/);
  }
  // href equals the input URL EXACTLY, and the order is Official → Lane plan → Prices.
  expect(chips.map((c: FakeElement) => c.getAttribute('href'))).toEqual(['https://official.example/pool', 'https://plans.example/lane.pdf', 'https://prices.example/tariff']);
  // the aria-label names the destination host
  expect(chips[0].getAttribute('aria-label')).toMatch(/official\.example/);
});

test('a null / empty source drops ONLY its own chip', () => {
  const noOfficial = mount();
  createSourceStrip(noOfficial, {
    props: { officialUrl: null, lanePlanUrls: ['https://plans.example/lane.pdf'], pricesUrl: 'https://prices.example/t' },
  });
  expect(chipsOf(noOfficial).length).toBe(2);

  const noPrices = mount();
  createSourceStrip(noPrices, {
    props: { officialUrl: 'https://official.example/p', lanePlanUrls: ['https://plans.example/lane.pdf'], pricesUrl: null },
  });
  expect(chipsOf(noPrices).length).toBe(2);

  const noLanes = mount();
  createSourceStrip(noLanes, {
    props: { officialUrl: 'https://official.example/p', lanePlanUrls: [], pricesUrl: 'https://prices.example/t' },
  });
  expect(chipsOf(noLanes).length).toBe(2);
});

test('all-empty props → an element with NO chips (no dead links)', () => {
  const el = mount();
  createSourceStrip(el, { props: { officialUrl: null, lanePlanUrls: [], pricesUrl: null } });
  expect(el.classList.contains('ui-sourcestrip')).toBeTruthy();
  expect(chipsOf(el).length).toBe(0);
  // No chips → no "Sources" group role, so a screen reader announces nothing empty.
  expect(el.getAttribute('role')).toBe(null);
  expect(el.getAttribute('aria-label')).toBe(null);
});

test('missing props object is tolerated (no crash, no chips)', () => {
  const el = mount();
  createSourceStrip(el, {});
  expect(chipsOf(el).length).toBe(0);
});

test('two identical lanePlanUrls collapse to ONE Lane-plan chip', () => {
  const el = mount();
  createSourceStrip(el, {
    props: { lanePlanUrls: ['https://plans.example/x.pdf', 'https://plans.example/x.pdf'] },
  });
  expect(chipsOf(el).length).toBe(1);
});

test('a pricesUrl equal to officialUrl collapses into the Official chip (dedup across kinds)', () => {
  const el = mount();
  createSourceStrip(el, {
    props: { officialUrl: 'https://same.example/page', lanePlanUrls: [], pricesUrl: 'https://same.example/page' },
  });
  const chips = chipsOf(el);
  expect(chips.length).toBe(1);
  expect(chips[0].classList.contains('ui-sourcestrip__chip--official')).toBeTruthy();
  expect(chips[0].textContent.includes('Official')).toBeTruthy();
});

test('Lane-plan chips carry a visible "PDF" marker', () => {
  const el = mount();
  createSourceStrip(el, { props: { lanePlanUrls: ['https://plans.example/lane.pdf'] } });
  const chip = must(el.query(hasClass('ui-sourcestrip__chip')));
  expect(chip.classList.contains('ui-sourcestrip__chip--lane')).toBeTruthy();
  expect(chip.textContent.includes('PDF')).toBeTruthy();
  expect(chip.getAttribute('aria-label')).toMatch(/Lane plan PDF/);
});
