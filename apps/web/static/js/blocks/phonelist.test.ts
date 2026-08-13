import { expect, test } from 'vitest';

import { mount, type FakeElement } from '../components/_fakedom.js';
import { fake, must } from '../testutil.js';
import { formatHour } from '../datefmt.js';
import { locale } from '../i18n.js';
import { STRIP_HOURS, tickPercent } from './daytail.js';
import { createPoolList } from './poollist.js';
import { createPhoneBar, leadTag, stripDates } from './phonebar.js';
import { rowKey, type RankRow } from './poolrank.js';

const M = (h: number, m = 0) => h * 60 + m;

const ROWS: RankRow[] = [
  {
    label: 'Hallenbad City',
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
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
  {
    label: 'Seebad Utoquai',
    facility: 'Seebad Utoquai',
    options: [],
    statuses: [{ status: 'closed' }],
  },
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
  // NOTE: since S1 put the tail inside the card button, the canvas is `aria-hidden` and
  // these two attributes are INERT — retained deliberately (they are the correct labelling
  // if the canvas ever leaves the button again), not a live a11y guarantee. What a screen
  // reader actually announces is asserted by 'a row does not announce its pool name twice'.
  expect(canvases[0].getAttribute('aria-label')).toBe('Hallenbad City');
  expect(canvases[0].getAttribute('role')).toBe('img');
});

// --- S1: the ribbon IS the tap target ------------------------------------------------
// `_fakedom`'s dispatch does not bubble and neither `El` nor `FakeElement` has a
// node-level `contains` (that lives on ElClassList), so "a tap on the tail reaches the
// button" is asserted as parentage.

test('the day tail lives inside the card button, so tapping the bars opens the card', () => {
  const { el } = build();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  const tailBox = must(el.query((c: FakeElement) => c.classList.contains('plist__tail')));
  // S3 pushed the tail one level deeper — it shares the padded `.plist__plot` wrapper with
  // the hour strip, which is what keeps the strip's percentages over the canvas's bars. The
  // CLAIM this test makes is unchanged and is about the tap target, not the nesting depth,
  // so it is asserted as ancestry: `btn` is still what a tap on the bars reaches. (The exact
  // parentage — tail inside plot inside btn — is pinned by the S3 DOM-contract test below.)
  //
  // Asserted as a BOOLEAN, not `expect(node).toBe(otherNode)`: a red identity assertion
  // makes vitest deep-diff two FakeElement trees, and `parentNode` back-references make
  // that diff take minutes — long enough to look like a hung suite rather than a failure.
  expect(btn.query((c: FakeElement) => c === tailBox) !== null).toBe(true);
  const canvas = must(tailBox.query((c: FakeElement) => c.tagName === 'CANVAS'));
  expect(canvas.parentNode === tailBox).toBe(true);
});

test('the expanded body is NOT inside the button — a <button> may not nest the Gantt', () => {
  const { el } = build();
  const card = must(el.query((c: FakeElement) => c.classList.contains('plist__card')));
  const more = must(el.query((c: FakeElement) => c.classList.contains('plist__more')));
  expect(more.parentNode).toBe(card);
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  expect(btn.query((c: FakeElement) => c.classList.contains('plist__more'))).toBeNull();
});

test('a row does not announce its pool name twice', () => {
  // The button names itself from its contents. The h3 already carries `row.label`, so the
  // canvas inside it must be aria-hidden or every one of ~58 rows says the name twice.
  const { el } = build();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  const canvas = must(btn.query((c: FakeElement) => c.tagName === 'CANVAS'));
  expect(canvas.getAttribute('aria-hidden')).toBe('true');
  const named = btn
    .queryAll((c: FakeElement) => c.textContent === 'Hallenbad City')
    .filter((c: FakeElement) => c.tagName === 'H3');
  expect(named.length).toBe(1);
});

// --- S3: the hour strip -------------------------------------------------------------
// The tail encodes time along X but carries no axis of its own, and the phone has no
// shared header to read it against (`phonebar.ts` carries the DATE, never the hours).
// These pin the strip's contract; its pixel alignment is a layout fact no headless suite
// can see, and is checked by eye at the pause gate.

test('every card labels its tail with the strip hours, positioned by tickPercent', () => {
  const { el } = build();
  const strips = el.queryAll((c: FakeElement) => c.classList.contains('plist__ticks'));
  expect(strips.length).toBe(2); // one per card, not one for the list
  for (const strip of strips) {
    const labels = strip.queryAll((c: FakeElement) => c.tagName === 'SPAN');
    expect(labels.length).toBe(STRIP_HOURS.length);
    // Text AND position derived from the shared sources, so a hand-rolled `HH:00` or a
    // hand-copied window would fail here rather than drift silently on screen.
    expect(labels.map((l: FakeElement) => l.textContent)).toEqual(
      STRIP_HOURS.map((h) => formatHour(h, locale())),
    );
    expect(labels.map((l: FakeElement) => l.style.left)).toEqual(
      STRIP_HOURS.map((h) => `${tickPercent(h)}%`),
    );
  }
});

test('the strip sits in the padded plot wrapper the canvas shares, inside the button', () => {
  // The CSS contract: ONE inline padding, on `.plist__plot`, shared by both children —
  // percentages only line up with the canvas if the two resolve against the same content
  // box. `.plist__tail` survives so `.plist__tail canvas { width: 100% }` keeps matching.
  const { el } = build();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  const plot = must(el.query((c: FakeElement) => c.classList.contains('plist__plot')));
  const strip = must(el.query((c: FakeElement) => c.classList.contains('plist__ticks')));
  const tailBox = must(el.query((c: FakeElement) => c.classList.contains('plist__tail')));
  const canvas = must(tailBox.query((c: FakeElement) => c.tagName === 'CANVAS'));

  // Parentage as booleans PLUS the parent's class: the boolean is the real identity
  // claim, the class name is what a red run prints. `expect(node).toBe(node)` would deep
  // diff two whole FakeElement trees through their `parentNode` back-references, which
  // takes minutes and reads as a hung suite.
  expect([strip, tailBox].map((n) => n.parentNode?.className)).toEqual([
    'plist__plot',
    'plist__plot',
  ]);
  expect(strip.parentNode === plot).toBe(true);
  expect(tailBox.parentNode === plot).toBe(true);
  expect(canvas.parentNode === tailBox).toBe(true);
  // …and the whole plot is inside the button: a strip outside it would punch a dead gap
  // through the middle of the tap target S1 created.
  expect(plot.parentNode === btn).toBe(true);
});

test('the hour strip is hidden from assistive tech', () => {
  // Six loose numbers per card, across ~58 cards, between one verdict and the next.
  const { el } = build();
  const strip = must(el.query((c: FakeElement) => c.classList.contains('plist__ticks')));
  expect(strip.getAttribute('aria-hidden')).toBe('true');
});

test('a partly-reserved pool is not counted as open to you', () => {
  // City publishes 2 of 6 lanes public — open, but not a promise.
  expect(build().api.countOpenToYou()).toBe(0);
});

test('tapping a card expands it, and tapping again collapses', () => {
  const { el, api } = build();
  const btn = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  btn.click();
  expect(api.openKey).toBe(rowKey(ROWS[0]));
  const reopened = must(el.query((c: FakeElement) => c.classList.contains('plist__btn')));
  reopened.click();
  expect(api.openKey).toBeNull();
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
  expect(api.openKey).toBeNull();
  expect(el.queryAll((c: FakeElement) => c.tagName === 'CANVAS').length).toBe(1);
});

// --- S3: a card is a BASIN of a pool, and its open state is keyed on that -------------

/** One pool publishing two basins — the case rule L1 relabels, and the case every
 *  label-keyed comparison in this block used to break on. Both basins are open now and
 *  wholly public, so both cards land in the same tier and the list must still tell them
 *  apart. */
const TWO_BASINS: RankRow[] = [
  {
    label: 'Hallenbad City \u00b7 Hauptbecken',
    facility: 'Hallenbad City',
    basin_id: 'city-main',
    // Rule L1 put the basin in the label, and says so — exactly what `dayRows` emits for
    // this answer. That the two agree is asserted in board.test.ts ("`basinInLabel` is set
    // on exactly the rows whose LABEL carries the basin"), so this flag is not a free
    // choice here: a fixture that set it without the suffix would contradict that test.
    basinInLabel: true,
    options: [{ start: '09:00', end: '21:00', distance_km: 0.9, basin: 'Hauptbecken' }],
    statuses: [],
  },
  {
    label: 'Hallenbad City \u00b7 Schwimmerbecken',
    facility: 'Hallenbad City',
    basin_id: 'city-50m',
    basinInLabel: true,
    options: [{ start: '09:00', end: '21:00', distance_km: 0.9, basin: 'Schwimmerbecken' }],
    statuses: [],
  },
];

function buildTwoBasins() {
  const el = mount();
  const opened: string[] = [];
  const api = createPoolList(el, {
    rows: TWO_BASINS,
    nowMin: M(10),
    reducedMotion: true,
    onOpen: (key) => opened.push(key),
  });
  return { el: fake(el), api, opened };
}

const btns = (el: ReturnType<typeof fake>) =>
  el.queryAll((c: FakeElement) => c.classList.contains('plist__btn'));

test('two basins of ONE pool are two cards, and opening one opens only that one', () => {
  const { el, api, opened } = buildTwoBasins();
  expect(btns(el).length).toBe(2);
  btns(el)[1].click();
  expect(api.openKey).toBe(rowKey(TWO_BASINS[1]));
  expect(opened).toEqual([rowKey(TWO_BASINS[1])]);
  // Exactly ONE card reports itself expanded — the second, not the first.
  const expanded = btns(el).map((b) => b.getAttribute('aria-expanded'));
  expect(expanded).toEqual(['false', 'true']);
  const openCards = el.queryAll((c: FakeElement) => c.classList.contains('is-open'));
  expect(openCards.length).toBe(1);
});

test('a two-basin card collapses and re-opens the SAME card across re-renders', () => {
  const { el, api } = buildTwoBasins();
  btns(el)[1].click(); // open the second basin
  expect(api.openKey).toBe(rowKey(TWO_BASINS[1]));
  btns(el)[1].click(); // tapping it again collapses it
  expect(api.openKey).toBeNull();
  expect(el.queryAll((c: FakeElement) => c.classList.contains('is-open')).length).toBe(0);
  btns(el)[1].click(); // and re-opens it, still the second
  expect(api.openKey).toBe(rowKey(TWO_BASINS[1]));
  expect(btns(el).map((b) => b.getAttribute('aria-expanded'))).toEqual(['false', 'true']);
});

test('opening a card hands the caller a key that finds the right row again', () => {
  // app.ts turns this key back into a row index (`phoneRows.findIndex`) to open the panel.
  // With a label it would have found the wrong basin — or none.
  const { el, opened } = buildTwoBasins();
  btns(el)[0].click();
  const index = TWO_BASINS.findIndex((r) => rowKey(r) === opened[0]);
  expect(index).toBe(0);
  expect(TWO_BASINS[index].basin_id).toBe('city-main');
});

test('a two-basin card does not repeat the basin its heading already names', () => {
  // S3 gave the heading its `· <basin>` suffix and the fact line kept adding the basin a
  // second time: "Hallenbad City · Schwimmerbecken" over "0.9 km · Schwimmerbecken".
  const { el } = buildTwoBasins();
  const metas = el
    .queryAll((c: FakeElement) => c.classList.contains('plist__meta'))
    .map((m) => m.textContent);
  expect(metas.length).toBe(2);
  for (const m of metas) expect(m).not.toContain('becken');
});

test('a SINGLE-basin card still shows its basin — the heading does not name it', () => {
  const el = mount();
  createPoolList(el, {
    rows: [
      {
        label: 'Hallenbad City',
        facility: 'Hallenbad City',
        basin_id: 'city-main',
        options: [{ start: '09:00', end: '21:00', distance_km: 0.9, basin: 'Hauptbecken' }],
        statuses: [],
      },
    ],
    nowMin: M(10),
    reducedMotion: true,
  });
  const meta = must(fake(el).query((c: FakeElement) => c.classList.contains('plist__meta')));
  expect(meta.textContent).toContain('Hauptbecken');
});

test('a two-basin pool counts ONCE toward "open to you now"', () => {
  expect(buildTwoBasins().api.countOpenToYou()).toBe(1);
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

test('a closed card now states how far away the pool is (board-order-and-defects S2)', () => {
  // A status carries a distance since S2, and `rowDistance` reads it — so the fact line of a
  // shut pool stops being blank. Without this the card said nothing at all about WHERE it is,
  // which is the one thing that still matters when you are choosing tomorrow instead.
  const el = mount();
  createPoolList(el, {
    rows: [
      {
        label: 'Seebad Utoquai',
        facility: 'Seebad Utoquai',
        options: [],
        statuses: [{ status: 'closed', distance_km: 1.87 }],
      },
    ],
    nowMin: M(10),
    reducedMotion: true,
  });
  const meta = must(fake(el).query((c: FakeElement) => c.classList.contains('plist__meta')));
  expect(meta.textContent).toContain('1.9 km'); // `formatKm` renders one decimal
});
