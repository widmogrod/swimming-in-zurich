import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { mount } from '../components/_fakedom.js';
import type { FakeElement } from '../components/_fakedom.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, cursorX, publicAt, type LanePanel } from './cursor.js';
import { BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createGantt, readoutLeft, READOUT_NOMINAL_W, GANTT_LABEL_W } from './gantt.js';
import { must } from '../testutil.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

const POOL = load<{ lane_panels: unknown[] }>('pool_oerlikon.json');
const BASIN = basinFromPanel(POOL.lane_panels[0] as LanePanel); // 50m-Becken, 8 lanes
const hasClass = (c: string) => (e: FakeElement) => e.classList.contains(c);
const textIs = (t: string) => (e: FakeElement) => e.textContent === t;

// The sampled cursor minutes for the alignment assertions (06:00 … 22:00).
const SAMPLES = [360, 450, 540, 600, 690, 780, 870, 960, 1080, 1200, 1320];

test('createGantt REQUIRES a shared timescale (refuses to re-derive its own scale)', () => {
  expect(() => createGantt(mount(), { basin: BASIN } as never)).toThrow();
});

test('(a) cursor-x equality: the Gantt cursor-x is exactly the board timescale mapping', () => {
  // The board draws its ribbons/cursor through THIS timescale (board.js → ts.X); the
  // Gantt is handed the SAME instance, so cursorPlotX(T) == board cursor-x(T) == ts.X(T).
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const g = createGantt(mount(), { basin: BASIN, timescale: ts });
  for (const T of SAMPLES) {
    expect(g.cursorPlotX(T)).toBe(ts.X(T)); // board & Gantt share the mapping
    expect(g.cursorPlotX(T)).toBe(cursorX(ts, T)); // both go through the one helper
  }
});

test('(a) non-tautology: cursorPlotX tracks the INJECTED scale, so a private scale would diverge', () => {
  // Two different scales → two different cursor-x for the same minute. This is what
  // FAILS if someone gives the Gantt its own timescale instead of the board's.
  const ts900 = makeTimescale(6, 22, 900);
  const ts500 = makeTimescale(6, 22, 500);
  const g900 = createGantt(mount(), { basin: BASIN, timescale: ts900 });
  const g500 = createGantt(mount(), { basin: BASIN, timescale: ts500 });
  const T = 600; // 10:00
  expect(g900.cursorPlotX(T)).toBe(ts900.X(T));
  expect(g500.cursorPlotX(T)).toBe(ts500.X(T));
  expect(g900.cursorPlotX(T)).not.toBe(g500.cursorPlotX(T));
});

test('(a) a click at 10:00 puts the Gantt cursor on the Gantt 10:00 gridline', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  g.setCursor(600); // 10:00
  const cursor = must(el.query(hasClass('gantt__cursor')));
  const tick = must(
    el.queryAll(hasClass('gantt__tick')).find((t) => t.textContent === '10:00'),
    '10:00 tick',
  );
  // Both the cursor and the 10:00 axis tick are placed at the SAME track x.
  expect(cursor.style.left).toBe(`${g.trackX(600)}px`);
  expect(tick.style.left).toBe(`${g.trackX(600)}px`);
});

test('(c) one lane row per lane, with owner-named reserved segments from /pools/{id}', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  createGantt(el, { basin: BASIN, timescale: ts });
  // one row per lane
  expect(el.queryAll(hasClass('gantt__lane')).length).toBe(BASIN.strips.length);
  expect(el.queryAll(hasClass('gantt__lanelabel')).length).toBe(BASIN.strips.length);
  // reserved segments carry the owner text seen in the real capture
  const reserved = el.queryAll(hasClass('is-reserved'));
  expect(reserved.length > 0).toBeTruthy();
  for (const owner of ['Limmat-Sharks', 'Schools', 'PH Zürich']) {
    expect(must(el.query(textIs(owner)))).toBeTruthy();
  }
  // public segments are labelled, never hue-only
  expect(el.queryAll(hasClass('is-public')).length > 0).toBeTruthy();
});

test('the live readout reads publicAt at the cursor, formatted "T · N of M lanes public"', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  g.setCursor(780); // 13:00
  const { public: n, total: m } = publicAt(BASIN, 780);
  expect(g.readoutAt(780)).toEqual({ public: n, total: m });
  const readout = must(el.query(hasClass('gantt__readout')));
  expect(readout.textContent).toBe(`13:00 · ${n} of ${m} lanes public`);
});

// --- the readout follows the cursor --------------------------------------------------
//
// As shipped, the readout was a plain block div appended to `el`: its TEXT changed as the
// cursor moved and its POSITION never did, so it sat in the top-left corner while the line
// it describes travelled underneath it. Reported by the owner against the running app:
// "it does not move '19:16 · 4 z 6 torów publicznych' to align with current time, or with
// selection or hover". It now rides above its own cursor, off the same `trackX`.

const TRACK_W = GANTT_LABEL_W + BOARD_PLOT;

test('readoutLeft centres on the cursor x, and clamps at BOTH edges of the VISIBLE window', () => {
  // Centred wherever there is room on both sides.
  expect(readoutLeft(500, 180, 0, 1020)).toBe(410);
  expect(readoutLeft(90, 180, 0, 1020)).toBe(0); // would be -0…, clamped to the left edge
  expect(readoutLeft(0, 180, 0, 1020)).toBe(0);
  expect(readoutLeft(1020, 180, 0, 1020)).toBe(840); // flush right, never past the track
  expect(readoutLeft(940, 180, 0, 1020)).toBe(840); // 940-90=850 > 840 → clamped
  // The exact boundaries: one px inside each clamp is still centred, so the clamp cannot be
  // widened into the middle without failing here.
  expect(readoutLeft(91, 180, 0, 1020)).toBe(1);
  expect(readoutLeft(929, 180, 0, 1020)).toBe(839);
  // A readout wider than the whole track has no non-overflowing placement: flush left.
  expect(readoutLeft(500, 1200, 0, 1020)).toBe(0);
});

test('the readout is CENTRED on the very x the cursor line is drawn at', () => {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  const readout = must(el.query(hasClass('gantt__readout')));
  const cursor = must(el.query(hasClass('gantt__cursor')));
  const px = (e: FakeElement) => Number.parseFloat(e.style.left);
  let centred = 0;
  for (const T of SAMPLES) {
    g.setCursor(T);
    // The readout goes through `trackX`, exactly as the cursor does — never a second
    // derivation of the same moment.
    expect(px(readout)).toBe(readoutLeft(g.trackX(T), READOUT_NOMINAL_W, 0, TRACK_W));
    // …and it stays inside the track at every sampled minute.
    expect(px(readout)).toBeGreaterThanOrEqual(0);
    expect(px(readout) + READOUT_NOMINAL_W).toBeLessThanOrEqual(TRACK_W);
    // Where it is not clamped, its centre IS the cursor. This is the user-visible property.
    if (px(readout) > 0 && px(readout) + READOUT_NOMINAL_W < TRACK_W) {
      expect(px(readout) + READOUT_NOMINAL_W / 2).toBe(px(cursor));
      centred += 1;
    }
  }
  // Not vacuously true because every sample happened to clamp.
  expect(centred).toBeGreaterThan(5);
});

test('the readout moves — a second position is a DIFFERENT number, not the same corner', () => {
  // The precise regression: the old readout's `left` never changed at all.
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  const readout = must(el.query(hasClass('gantt__readout')));
  g.setCursor(480); // 08:00
  const at8 = readout.style.left;
  g.setCursor(1200); // 20:00
  expect(readout.style.left).not.toBe(at8);
  // …and it moves the same way the cursor does: later is further right.
  expect(Number.parseFloat(readout.style.left)).toBeGreaterThan(Number.parseFloat(at8));
});

test('the readout sits INSIDE the track, in the cursor\'s own coordinate space', () => {
  // `.gantt__scroll` is the overflow container and `.gantt__track` is what slides under the
  // finger. Being a child of the track puts the readout in the cursor's own coordinate
  // space, so ALIGNMENT is one number in track px and `scrollLeft` never enters it. Parked
  // back in `el` (as it shipped) it would need `scrollLeft` subtracted from every placement
  // just to sit over its own line.
  //
  // Alignment is not visibility, and this test claims only the first: the readout must ALSO
  // be clamped to the part of the track the reader can SEE, which does move with
  // `scrollLeft`. That is the visible-window section at the foot of this file, and it is why
  // `gantt.ts` registers a scroll listener as well as parenting the readout here — the two
  // mechanisms answer different questions and neither replaces the other.
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  createGantt(el, { basin: BASIN, timescale: ts });
  const track = must(el.query(hasClass('gantt__track')));
  const readout = must(el.query(hasClass('gantt__readout')));
  // Asserted as booleans, not `toBe(track)`: a failing identity assertion on two FakeElements
  // makes vitest serialise two cyclic DOM trees, which hangs the reporter instead of
  // reporting. Same property, printable failure.
  expect(Boolean(track.query(hasClass('gantt__readout'))), 'readout is in the track').toBe(true);
  // The cursor is in the same box — hence the same origin, hence one `left` means one x.
  expect(Boolean(track.query(hasClass('gantt__cursor'))), 'cursor is in the track').toBe(true);
  // Still a live region: moving it must not cost a screen-reader user the value.
  expect(readout.getAttribute('role')).toBe('status');
  expect(readout.getAttribute('aria-live')).toBe('polite');
});

test('the readout is placed off its MEASURED width where the DOM can measure one', () => {
  // Headless there is no layout, so placement falls back to `READOUT_NOMINAL_W`. In a
  // browser the element reports its real width — which, on a locale whose sentence is much
  // longer or shorter than the nominal, is the difference between centred and visibly off.
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  const readout = must(el.query(hasClass('gantt__readout')));
  (readout as unknown as { offsetWidth: number }).offsetWidth = 300;
  g.setCursor(780);
  expect(readout.style.left).toBe(`${readoutLeft(g.trackX(780), 300, 0, TRACK_W)}px`);
  expect(readoutLeft(g.trackX(780), 300, 0, TRACK_W)).not.toBe(
    readoutLeft(g.trackX(780), READOUT_NOMINAL_W, 0, TRACK_W),
  );
});

// --- the clamp is against what is VISIBLE, not against the track ----------------------
//
// Found by looking at the running app rather than at a test: clamping to `[0, trackW]` is
// correct and useless in the desktop detail panel, where a 1020px track sits in a ~290px
// column. The readout was over its cursor and cut in half by `.gantt__scroll`.

test('readoutLeft clamps to a scrolled window, not to the track it lives in', () => {
  // A 290px column showing track px 0…290: a cursor at 289 cannot have a 180px readout
  // centred on it without half of it disappearing behind the container's edge.
  expect(readoutLeft(289, 180, 0, 290)).toBe(110); // flush with the visible right edge
  expect(readoutLeft(289, 180, 0, 1020)).toBe(199); // …which clamping to the TRACK misses
  // Scrolled: the window moves, and so do both clamps. The readout never precedes `lo`.
  expect(readoutLeft(600, 180, 500, 790)).toBe(510);
  expect(readoutLeft(505, 180, 500, 790)).toBe(500);
  expect(readoutLeft(780, 180, 500, 790)).toBe(610);
  // A window narrower than the readout itself: flush at `lo`, so the time is readable.
  expect(readoutLeft(600, 180, 500, 620)).toBe(500);
});

/** A mount whose `.gantt__scroll` reports layout, as a browser's would. */
function mountWithViewport(clientWidth: number) {
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const el = mount();
  const g = createGantt(el, { basin: BASIN, timescale: ts });
  const scroll = must(el.query(hasClass('gantt__scroll')));
  Object.assign(scroll, { clientWidth, scrollLeft: 0 });
  return { el, g, scroll, readout: must(el.query(hasClass('gantt__readout'))) };
}

test('a readout in a narrow column stays wholly inside the column', () => {
  const { g, readout } = mountWithViewport(290);
  for (const T of SAMPLES) {
    g.setCursor(T);
    const left = Number.parseFloat(readout.style.left);
    expect(left, `${T}: left edge`).toBeGreaterThanOrEqual(0);
    // The whole sentence fits in the visible 290px — never clipped by `.gantt__scroll`.
    expect(left + READOUT_NOMINAL_W, `${T}: right edge`).toBeLessThanOrEqual(290);
  }
});

test('scrolling the track re-places the readout — it does not slide out of view with it', () => {
  const { g, scroll, readout } = mountWithViewport(290);
  g.setCursor(1200); // 20:00 — far to the right of a 290px window, so the clamp binds
  const parked = Number.parseFloat(readout.style.left);
  expect(parked + READOUT_NOMINAL_W).toBeLessThanOrEqual(290);
  // The reader scrolls the track towards the cursor. The window moves; the readout follows.
  Object.assign(scroll, { scrollLeft: 800 });
  scroll.dispatch('scroll');
  const scrolled = Number.parseFloat(readout.style.left);
  expect(scrolled).not.toBe(parked);
  expect(scrolled).toBeGreaterThanOrEqual(800); // never behind the window's left edge
  expect(scrolled + READOUT_NOMINAL_W).toBeLessThanOrEqual(TRACK_W);
  // …and now that the cursor is genuinely inside the window, it is centred on it again.
  expect(scrolled + READOUT_NOMINAL_W / 2).toBe(g.trackX(1200));
});
