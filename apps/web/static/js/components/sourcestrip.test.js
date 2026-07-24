import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createSourceStrip } from './sourcestrip.js';

const hasClass = (c) => (e) => e.classList.contains(c);
const chipsOf = (el) => el.queryAll(hasClass('ui-sourcestrip__chip'));

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
  assert.equal(chips.length, 3);
  for (const c of chips) {
    assert.equal(c.tagName, 'A');
    assert.equal(c.getAttribute('target'), '_blank');
    const rel = c.getAttribute('rel');
    assert.match(rel, /noopener/);
    assert.match(rel, /noreferrer/);
    assert.match(c.getAttribute('aria-label'), /new tab/);
  }
  // href equals the input URL EXACTLY, and the order is Official → Lane plan → Prices.
  assert.deepEqual(
    chips.map((c) => c.getAttribute('href')),
    ['https://official.example/pool', 'https://plans.example/lane.pdf', 'https://prices.example/tariff'],
  );
  // the aria-label names the destination host
  assert.match(chips[0].getAttribute('aria-label'), /official\.example/);
});

test('a null / empty source drops ONLY its own chip', () => {
  const noOfficial = mount();
  createSourceStrip(noOfficial, {
    props: { officialUrl: null, lanePlanUrls: ['https://plans.example/lane.pdf'], pricesUrl: 'https://prices.example/t' },
  });
  assert.equal(chipsOf(noOfficial).length, 2);

  const noPrices = mount();
  createSourceStrip(noPrices, {
    props: { officialUrl: 'https://official.example/p', lanePlanUrls: ['https://plans.example/lane.pdf'], pricesUrl: null },
  });
  assert.equal(chipsOf(noPrices).length, 2);

  const noLanes = mount();
  createSourceStrip(noLanes, {
    props: { officialUrl: 'https://official.example/p', lanePlanUrls: [], pricesUrl: 'https://prices.example/t' },
  });
  assert.equal(chipsOf(noLanes).length, 2);
});

test('all-empty props → an element with NO chips (no dead links)', () => {
  const el = mount();
  createSourceStrip(el, { props: { officialUrl: null, lanePlanUrls: [], pricesUrl: null } });
  assert.ok(el.classList.contains('ui-sourcestrip'));
  assert.equal(chipsOf(el).length, 0);
  // No chips → no "Sources" group role, so a screen reader announces nothing empty.
  assert.equal(el.getAttribute('role'), null);
  assert.equal(el.getAttribute('aria-label'), null);
});

test('missing props object is tolerated (no crash, no chips)', () => {
  const el = mount();
  createSourceStrip(el, {});
  assert.equal(chipsOf(el).length, 0);
});

test('two identical lanePlanUrls collapse to ONE Lane-plan chip', () => {
  const el = mount();
  createSourceStrip(el, {
    props: { lanePlanUrls: ['https://plans.example/x.pdf', 'https://plans.example/x.pdf'] },
  });
  assert.equal(chipsOf(el).length, 1);
});

test('a pricesUrl equal to officialUrl collapses into the Official chip (dedup across kinds)', () => {
  const el = mount();
  createSourceStrip(el, {
    props: { officialUrl: 'https://same.example/page', lanePlanUrls: [], pricesUrl: 'https://same.example/page' },
  });
  const chips = chipsOf(el);
  assert.equal(chips.length, 1);
  assert.ok(chips[0].classList.contains('ui-sourcestrip__chip--official'));
  assert.ok(chips[0].textContent.includes('Official'));
});

test('Lane-plan chips carry a visible "PDF" marker', () => {
  const el = mount();
  createSourceStrip(el, { props: { lanePlanUrls: ['https://plans.example/lane.pdf'] } });
  const chip = el.query(hasClass('ui-sourcestrip__chip'));
  assert.ok(chip.classList.contains('ui-sourcestrip__chip--lane'));
  assert.ok(chip.textContent.includes('PDF'));
  assert.match(chip.getAttribute('aria-label'), /Lane plan PDF/);
});
