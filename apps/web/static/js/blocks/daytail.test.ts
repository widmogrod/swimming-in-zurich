import { expect, test } from 'vitest';

import { mount } from '../components/_fakedom.js';
import { recordingCtx, type Call } from '../testutil.js';
import { asCanvas, type Palette, type RenderRibbon } from './ribbonrender.js';
import {
  drawDayTail,
  tailBacking,
  tailTimescale,
  tickPercent,
  MAX_DPR,
  STRIP_HOURS,
  TAIL_DAY0,
  TAIL_DAY1,
  TAIL_H,
  TICK_HOURS,
  type DayTailOpts,
} from './daytail.js';

test('the tail spans 06:00 to 22:30 across its laid-out width', () => {
  const ts = tailTimescale(340);
  expect(ts.X(TAIL_DAY0 * 60)).toBe(0);
  expect(ts.X(TAIL_DAY1 * 60)).toBe(340);
  // The board stops at 22:00; the tail runs later so a 22:00 session has somewhere to end
  // rather than being clipped flush against the right edge.
  expect(ts.X(22 * 60)).toBeLessThan(340);
});

test('tailBacking scales the backing store by dpr and caps it', () => {
  expect(tailBacking(340, 1)).toEqual({ w: 340, h: TAIL_H, scale: 1 });
  expect(tailBacking(340, 2)).toEqual({ w: 680, h: TAIL_H * 2, scale: 2 });
  // Beyond 2x the extra pixels cost memory and buy nothing.
  expect(tailBacking(340, 3).scale).toBe(MAX_DPR);
});

test('a nonsense devicePixelRatio falls back to 1 rather than a zero-sized canvas', () => {
  // Some embedded webviews report 0; scaling by it would render nothing at all, silently.
  for (const bad of [0, -1, NaN, Infinity]) {
    expect(tailBacking(340, bad)).toEqual({ w: 340, h: TAIL_H, scale: 1 });
  }
});

test('tailBacking never rounds down to a zero dimension', () => {
  expect(tailBacking(0.2, 1).w).toBe(1);
});

test('drawDayTail is a no-op headless, and on an unlaid-out row', () => {
  // The fake canvas has no getContext; the drawable LOGIC lives in ribbonmodel/poolrank
  // and is tested there, so a canvas-free environment loses nothing testable.
  const canvas = asCanvas(mount().ownerDocument.createElement('canvas'));
  expect(() => drawDayTail(canvas, [], null, { width: 340 })).not.toThrow();
  expect(() => drawDayTail(canvas, [], { public: 'red' }, { width: 0 })).not.toThrow();
});

// ---- The hour marks -------------------------------------------------------------

test('the strip labels every third hour, and the canvas marks all but the left edge', () => {
  expect(STRIP_HOURS).toEqual([6, 9, 12, 15, 18, 21]);
  // 06:00 IS the left edge of the plot: a rule there paints on the canvas border and reads
  // as a frame rather than as a time. It is still LABELLED — the strip says where 06:00 is.
  expect(TICK_HOURS).toEqual([9, 12, 15, 18, 21]);
  expect(STRIP_HOURS.filter((h) => !TICK_HOURS.includes(h))).toEqual([TAIL_DAY0]);
});

test('tickPercent agrees with the canvas timescale at every labelled hour, at any width', () => {
  // X1. The DOM strip positions its labels in PERCENT and the canvas paints in px; they
  // line up only if these are the same mapping. Widths pinned deliberately: 320 (iPhone SE)
  // and 390 (iPhone 12-14) are the ULP cases — `X` computes `((min-lo)/span)*PLOT` and this
  // test divides by PLOT again, so the two sides differ by one float ulp at hour 21 and a
  // strict `===` would go red on a CORRECT implementation at the two commonest phone widths.
  for (const w of [320, 375, 390]) {
    const ts = tailTimescale(w);
    for (const hour of STRIP_HOURS) {
      expect(Math.abs(tickPercent(hour) - (ts.X(hour * 60) / w) * 100)).toBeLessThan(1e-10);
    }
  }
  // The window's own edges anchor the scale.
  expect(tickPercent(TAIL_DAY0)).toBe(0);
  expect(tickPercent(TAIL_DAY1)).toBe(100);
});

// ---- Painting, against a recording context --------------------------------------

/** The palette the tail resolves from tokens.css at runtime; every key the painters read. */
const PAL: Palette = {
  public: 'rgb(1, 2, 3)',
  other: 'rgb(1, 2, 3)',
  sheath: 'rgb(9, 9, 9)',
  lanetrack: 'rgb(8, 8, 8)',
  lanepublic: 'rgb(7, 7, 7)',
  lanereserved: 'rgb(6, 6, 6)',
  bestband: 'rgb(5, 5, 5)',
  bestedge: 'rgb(4, 4, 4)',
  axis: 'rgb(3, 3, 3)',
  hair: 'rgb(2, 2, 2)',
};

/** A lane STACK with a sheath and real lane strips — pinned, because the four ribbon
 *  painters emit different ops: the `status` painter emits no `fillRect` at all (which
 *  would make the ordering assertion vacuous) and the hatched painter emits its own
 *  `moveTo` per hatch line, so neither can decide draw order. The stack paints solid
 *  `fillRect` bands and no path ops at all — and it is also the variant the marks must
 *  survive, since an opaque band is exactly what hides a hairline drawn underneath it. */
const LANE_STACK: RenderRibbon = {
  kind: 'lane_day_view',
  variant: 'lanestack',
  family: 'public',
  sheath: true,
  start: '09:00',
  end: '12:00',
  lane_count: 4,
  strips: [
    { lane: 1, segments: [{ start: '09:00', end: '10:30', public: true }] },
    { lane: 2, segments: [{ start: '10:30', end: '12:00', public: false }] },
    { lane: 3, segments: [] },
    { lane: 4, segments: [{ start: '09:00', end: '12:00', public: true }] },
  ],
};

const WIDTH = 340;

/** Paint one tail onto a recording context and hand back the call trace. */
function paint(opts: Partial<DayTailOpts> = {}, ribbons: RenderRibbon[] = [LANE_STACK]): Call[] {
  const calls: Call[] = [];
  const canvas = asCanvas(mount().ownerDocument.createElement('canvas'));
  (canvas as unknown as { getContext: () => unknown }).getContext = () => recordingCtx(calls);
  drawDayTail(canvas, ribbons, PAL, { width: WIDTH, ...opts });
  return calls;
}

/** The x each mark is stroked at — the same rounding `drawTicks` applies. */
const tickXs = (): number[] =>
  TICK_HOURS.map((h) => Math.round(tailTimescale(WIDTH).X(h * 60)) + 0.5);

/** A mark's path start, identified by COORDINATE. Not "the first moveTo": a ribbon painter
 *  emits its own path ops, so position in the trace cannot identify a mark. */
const isTickStart = (c: Call): boolean =>
  c.op === 'moveTo' && c.args[1] === 0 && tickXs().includes(c.args[0] as number);

test('the hour marks are painted AFTER the ribbons, so a lane band cannot bury them', () => {
  const calls = paint();
  const lastFill = calls.map((c) => c.op).lastIndexOf('fillRect');
  const firstTick = calls.findIndex(isTickStart);
  expect(lastFill).toBeGreaterThan(-1); // the stack really did paint its bands
  expect(firstTick).toBeGreaterThan(-1); // the marks really were drawn
  // Under an OPAQUE lane band, a hairline drawn first simply is not there.
  expect(lastFill).toBeLessThan(firstTick);
});

/** The gutter a lane stack leaves free: the stack's box is `0.8 * h`, centred. A notch must
 *  stop INSIDE this, or it crosses the bands it is supposed to survive alongside. */
const GUTTER = (TAIL_H - TAIL_H * 0.8) / 2;

test('every marked hour gets a full-height rule AND a notch in each gutter', () => {
  const calls = paint();
  const marks = calls.filter(isTickStart).map((c) => c.args[0]);
  // Two paths per marked hour: the full-height rule, then the pair of gutter notches.
  expect(marks).toEqual(tickXs().flatMap((x) => [x, x]));

  for (const x of tickXs()) {
    // Every path op at this hour's x, in order — the mark's whole geometry.
    const ys = calls
      .filter((c) => (c.op === 'moveTo' || c.op === 'lineTo') && c.args[0] === x)
      .map((c) => c.args[1] as number);
    expect(ys.length).toBe(6);
    // The rule: edge to edge, at low alpha, so it reads through a translucent sheath.
    expect(ys.slice(0, 2)).toEqual([0, TAIL_H]);
    // The notches: from each edge inward by the SAME depth, and that depth must land in
    // the gutter. Asserted as a depth rather than as a call count, because two full-height
    // rules would satisfy a count — and would not be a notch.
    const [top0, top1, bot0, bot1] = ys.slice(2);
    expect(top0).toBe(0);
    expect(bot1).toBe(TAIL_H);
    expect(top1).toBeGreaterThan(0);
    expect(top1).toBeLessThanOrEqual(GUTTER);
    expect(TAIL_H - bot0).toBe(top1);
  }

  const leftEdge = Math.round(tailTimescale(WIDTH).X(TAIL_DAY0 * 60)) + 0.5;
  expect(calls.some((c) => c.op === 'moveTo' && c.args[0] === leftEdge)).toBe(false);
});

test('the now cursor draws only inside the window, and is a silent no-op outside it', () => {
  // X2, asserted as a DIFFERENTIAL: the marks stroke too, so a raw stroke count proves
  // nothing about the cursor. Only the delta against `null` isolates it.
  const strokes = (cursorMin: number | null): number =>
    paint({ cursorMin }).filter((c) => c.op === 'stroke').length;

  const baseline = strokes(null);
  expect(strokes(860)).toBe(baseline + 1); // 14:20 — inside [06:00, 22:30]
  // Before 06:00 `ts.X` is NEGATIVE and after 22:30 it runs past the right edge: the old
  // code stroked off-canvas and the rule silently vanished, which is the reported defect.
  expect(strokes(300)).toBe(baseline); // 05:00
  expect(strokes(1400)).toBe(baseline); // 23:20
  // The window's own edges are inside it.
  expect(strokes(TAIL_DAY0 * 60)).toBe(baseline + 1);
  expect(strokes(TAIL_DAY1 * 60)).toBe(baseline + 1);
});
