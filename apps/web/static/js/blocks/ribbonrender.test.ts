// ribbonrender.test.ts — the lane stack's PAINT (lane-stack-board S4).
//
// `board_render.test.ts` mounts the whole board to prove the painters execute; this file
// drives `drawRibbons` directly with a recording context, because the S4 properties are
// about WHICH marks land where: one band per lane inside the same row height, a best-public
// band that is absent rather than zero-width, NO TEXT anywhere on the stack — and, above
// all, that the three degraded states stay three (invariant I5).
//
// The recorder snapshots `fillStyle`/`globalAlpha` AT CALL TIME, so an assertion can name
// the colour a rectangle was actually painted in rather than the last one assigned.

import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { FakeDocument } from '../components/_fakedom.js';
import { asDoc, type El } from '../domtypes.js';
import { must } from '../testutil.js';
import { makeTimescale } from '../timescale.js';
import { optionRibbon, type RibbonOption } from './ribbonmodel.js';
import {
  drawRibbons,
  laneBands,
  resolveFamilyPalette,
  LANE_BAND_MIN_H,
  type Ctx2D,
  type Palette,
  type RenderRibbon,
} from './ribbonrender.js';
import { tailTimescale, TAIL_H } from './daytail.js';

const HERE = dirname(fileURLToPath(import.meta.url));

// The board's row-height FLOOR, and the phone tail's TAIL_H. Since board-order-and-defects
// S3 a board row carrying a lane plan is `max(46, 10 × lanes)` tall (`board.ts::rowHeight`),
// so 46 is no longer the only height a stack is painted at — the tests that care say which.
const H = 46;
const MID = H / 2;
/** The height the BOARD gives a 6-lane basin (City) and an 8-lane one (Oerlikon). */
const H6 = 60;
const H8 = 80;
const TS = makeTimescale(6, 22, 900);

/** Distinct, nameable colours — a real palette is resolved from tokens at runtime. */
const PAL: Palette = {
  public: 'PUBLIC', lane: 'LANE', other: 'OTHER', sheath: 'SHEATH', muted: 'MUTED',
  unknown: 'UNKNOWN', closed: 'CLOSED', axis: 'AXIS', hair: 'HAIR',
  lanepublic: 'LANEPUBLIC', lanereserved: 'LANERESERVED',
  lanetrack: 'LANETRACK', bestband: 'BESTBAND', bestedge: 'BESTEDGE',
};

interface Call {
  op: string;
  args: number[];
  text?: string;
  fill: string;
  stroke: string;
  alpha: number;
  dash: number[];
}

function recorder() {
  const calls: Call[] = [];
  /** Every TYPE-related thing the painter touches: the text state it assigns and any text
   *  it measures. `fillText` alone would miss a painter that sets up a font and then decides
   *  not to draw — and, more to the point, a text-free stack should touch none of it. */
  const textState: string[] = [];
  const state = { fillStyle: '', strokeStyle: '', globalAlpha: 1, dash: [] as number[], font: '' };
  const rec = (op: string, args: number[], text?: string) => {
    calls.push({
      op, args, text,
      fill: String(state.fillStyle), stroke: String(state.strokeStyle),
      alpha: state.globalAlpha, dash: [...state.dash],
    });
  };
  const ctx = {
    save() {}, restore() {}, beginPath() {}, closePath() {}, clip() {},
    moveTo(...a: number[]) { rec('moveTo', a); },
    lineTo(...a: number[]) { rec('lineTo', a); },
    arc(...a: number[]) { rec('arc', a); },
    rect(...a: number[]) { rec('rect', a); },
    fill() { rec('fill', []); },
    stroke() { rec('stroke', []); },
    fillRect(...a: number[]) { rec('fillRect', a); },
    strokeRect(...a: number[]) { rec('strokeRect', a); },
    clearRect(...a: number[]) { rec('clearRect', a); },
    fillText(text: string, x: number, y: number) { rec('fillText', [x, y], text); },
    setLineDash(d: number[]) { state.dash = d; },
    measureText(s: string) { textState.push(`measureText(${s})`); return { width: s.length * 6 }; },
    set fillStyle(v: string) { state.fillStyle = v; },
    get fillStyle() { return state.fillStyle; },
    set strokeStyle(v: string) { state.strokeStyle = v; },
    get strokeStyle() { return state.strokeStyle; },
    set globalAlpha(v: number) { state.globalAlpha = v; },
    get globalAlpha() { return state.globalAlpha; },
    set font(v: string) { textState.push(`font=${v}`); state.font = v; },
    get font() { return state.font; },
    set textAlign(v: string) { textState.push(`textAlign=${v}`); },
    get textAlign() { return ''; },
    set textBaseline(v: string) { textState.push(`textBaseline=${v}`); },
    get textBaseline() { return ''; },
    lineWidth: 1,
  };
  return { calls, textState, ctx: ctx as unknown as Ctx2D };
}

/** A `/swim` option with a per-lane day view: `lanes` public lanes, the rest held. */
function stackOption(opts: {
  lanes: number;
  publicLanes: number;
  owner?: string | null;
  /** An owner name on the PUBLIC segments too. Every fixture here (and every real
   *  Belegungsplan we have parsed) leaves a public hold's owner null, which is exactly why
   *  the renderer's `seg.public ? null : …` guard was untestable until this existed. */
  publicOwner?: string | null;
  start?: string;
  end?: string;
  best?: { start: string; end: string; public_lanes: number } | null;
}): RibbonOption {
  const start = opts.start ?? '08:00';
  const end = opts.end ?? '20:00';
  return {
    facility: 'P', basin: 'b', access: 'PublicSwim', start, end,
    lane_day_view: {
      weekday: 2,
      lane_count: opts.lanes,
      strips: Array.from({ length: opts.lanes }, (_, i) => ({
        lane: i + 1,
        segments: [
          i < opts.publicLanes
            ? { start, end, access: 'PublicSwim', owner: opts.publicOwner ?? null }
            : { start, end, access: 'ClubReserved', owner: opts.owner ?? 'SC Oerlikon' },
        ],
      })),
    },
    lane_best_public: opts.best === undefined ? { start, end, public_lanes: opts.publicLanes } : opts.best,
  };
}

const paintAll = (ribbons: RenderRibbon[], ts = TS, h = H) => {
  const { calls, textState, ctx } = recorder();
  drawRibbons(ctx, ribbons, ts, PAL, h / 2, h, 0);
  return { calls, textState };
};

const paint = (ribbons: RenderRibbon[], ts = TS, h = H) => paintAll(ribbons, ts, h).calls;

// --- The palette: every ink traces back to a token ------------------------------------

test('every ink the stack paints is probed from a class that blocks.css actually defines', () => {
  // The renderer holds no colour of its own: it probes `.fam-*` for a computed colour. A
  // probe with no CSS class behind it resolves to nothing and paints `undefined` on the
  // canvas — silently, in whatever the last fill was. So: collect the classes the renderer
  // really asks for, and assert the stylesheet answers each one.
  const asked: string[] = [];
  const doc = new FakeDocument();
  (doc as unknown as { defaultView: unknown }).defaultView = {
    getComputedStyle: (el: { className: string }) => {
      const cls = el.className.split(' ').filter((c) => c.startsWith('fam-'));
      asked.push(...cls);
      return { color: cls[0] ?? '' };
    },
  };
  const host = doc.createElement('div');
  const pal = must(resolveFamilyPalette(asDoc(doc), host as unknown as El));
  const css = readFileSync(join(HERE, '..', '..', 'blocks.css'), 'utf-8');
  for (const cls of new Set(asked)) expect(css, `blocks.css defines .${cls}`).toContain(`.${cls} {`);
  // And the stack's own inks are all there, distinctly named.
  // No `laneowner`: the stack paints no text, so it probes no ink for one — and the
  // `.fam-laneowner` class went with it. Adding it back needs a class behind it again.
  for (const key of ['lanepublic', 'lanereserved', 'lanetrack', 'bestband', 'bestedge']) {
    expect(pal[key]).toBe(`fam-${key}`);
  }
});

// --- AC2: the geometry, pure ---------------------------------------------------------

test('AC2 · six lanes become six DISTINCT sub-bands inside the row, not six rows', () => {
  // SUPERSEDED IN PART by board-order-and-defects S3. As shipped, this said the bands stay
  // "inside the row's own box — the row does not grow to fit the stack", which was a claim
  // about the BOARD and is now false there: a plan-bearing row IS grown, to `10 × lanes`,
  // because 46px could not carry an owner name on any real basin. What survives — and is
  // what this file is actually about — is that `laneBands` subdivides whatever height it is
  // handed and never paints outside it. So the property is asserted at BOTH heights: the
  // phone tail's 46 (unchanged, `TAIL_H`) and the board's 60 for a 6-lane basin.
  for (const h of [H, H6]) {
    const mid = h / 2;
    const bands = laneBands(6, mid, h);
    expect(bands.length).toBe(6);
    for (const [i, b] of bands.entries()) {
      expect(b.top).toBeGreaterThanOrEqual(mid - h * 0.4 - 0.001);
      expect(b.top + b.height).toBeLessThanOrEqual(mid + h * 0.4 + 0.001);
      expect(b.height).toBeGreaterThan(1);
      // SEPARATED, not merely adjacent: at six lanes there is room for the hairline gap, and
      // six touching fills read as one block with colour changes, not as six lanes.
      if (i + 1 < bands.length) expect(bands[i + 1].top).toBeGreaterThan(b.top + b.height);
    }
    // Evenly pitched — no lane is drawn fatter than its neighbours.
    const pitches = bands.slice(1).map((b, i) => b.top - bands[i].top);
    for (const p of pitches) expect(p).toBeCloseTo(pitches[0], 6);
  }
  // A taller row spends the extra pixels on the BANDS, not on padding around them.
  expect(laneBands(6, H6 / 2, H6)[0].height).toBeGreaterThan(laneBands(6, MID, H)[0].height);
});

test('an absurd lane count still yields that many bands, each at least a hairline', () => {
  const bands = laneBands(20, MID, H);
  expect(bands.length).toBe(20);
  expect(Math.min(...bands.map((b) => b.height))).toBeGreaterThanOrEqual(1);
  expect(laneBands(0, MID, H).length).toBe(1); // never zero bands, never a divide by zero
});

// --- AC2/AC1: the paint --------------------------------------------------------------

test('a 6-lane stack paints one track + one block per lane, public and reserved in DIFFERENT inks', () => {
  const calls = paint([optionRibbon(stackOption({ lanes: 6, publicLanes: 4 }))]);
  const bands = laneBands(6, MID, H);
  const tracks = calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANETRACK');
  const pub = calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANEPUBLIC');
  const res = calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANERESERVED');
  expect(tracks.length).toBe(6);
  expect(pub.length).toBe(4);
  expect(res.length).toBe(2);
  expect(PAL.lanepublic).not.toBe(PAL.lanereserved);
  // Each block sits on its own band, top to bottom, in lane order.
  const painted = [...pub, ...res].map((c) => c.args[1]).sort((a, b) => a - b);
  expect(painted).toEqual(bands.map((b) => b.top));
});

test('a stack where NO lane is public still paints every lane — it is not an empty row', () => {
  const calls = paint([optionRibbon(stackOption({ lanes: 6, publicLanes: 0 }))]);
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANERESERVED').length).toBe(6);
  expect(calls.some((c) => c.fill === 'LANEPUBLIC')).toBe(false);
});

// --- The stack is text-free ----------------------------------------------------------
//
// SUPERSEDES the whole "AC3 · the owner label" section of [[lane-stack-board]] S4 and its
// [[board-order-and-defects]] S3 follow-ups. Five tests lived here and asserted the
// OPPOSITE of what ships now:
//
//   • "AC3 · an owner is written where the whole word fits, and OMITTED where it does not"
//   • "a band too SHORT for type carries no owner either — and still paints its block"
//   • "S3 · at the height the BOARD now gives it, the same stack writes its owners"
//   • "ownerLabelFits measures the text — it never guesses from the block width alone"
//   • "ownerLabelFits reserves its padding — the boundary is text + BOTH margins"
//   • "a public lane is never labelled with the holder of the lane beside it"
//
// They are gone, not adjusted, because their subject is: the board's stack no longer writes
// the owner at all, and `ownerLabelFits` / `OWNER_LABEL_MIN_H` / `OWNER_LABEL_PAD` / the
// owner font no longer exist to be tested. Owner-review reason: the name is already read in
// the DetailPanel's Gantt, which sets it in real DOM type at full size, so at row scale on
// the board it was duplicated information paid for in 8.5px glyphs squeezed into an 8px
// band. What the row height buys now is the BANDS (`LANE_BAND_MIN_H`), asserted below and
// in board.test.ts.
//
// What survives from those tests is the non-text half — a hold too narrow for a word is
// still PAINTED, a public hold that carries a name is still public water — kept below so
// the deletion cannot take real coverage with it.

test('the board lane stack paints NO TEXT — at any height, any width, any holder', () => {
  // The regression guard for this change. It is deliberately stated over the exact cases
  // that used to produce labels: the three heights (phone/board 46, City 60, Oerlikon 80),
  // a hold wide enough for the word, and a public hold carrying an owner name.
  const cases: [string, ReturnType<typeof paintAll>][] = [
    ['3 lanes, wide hold, 46px', paintAll([optionRibbon(stackOption({ lanes: 3, publicLanes: 1, owner: 'SC Oerlikon' }))])],
    ['6 lanes at the board height', paintAll([optionRibbon(stackOption({ lanes: 6, publicLanes: 4, owner: 'SC Uster' }))], TS, H6)],
    ['8 lanes at the board height', paintAll([optionRibbon(stackOption({ lanes: 8, publicLanes: 6, owner: 'SV Limmat' }))], TS, H8)],
    ['a 15-minute hold', paintAll([optionRibbon(stackOption({ lanes: 3, publicLanes: 1, owner: 'SC Oerlikon', start: '08:00', end: '08:15' }))])],
    ['a NAMED public hold', paintAll([optionRibbon(stackOption({ lanes: 2, publicLanes: 1, publicOwner: 'SV Limmat', owner: 'SC Oerlikon' }))])],
  ];
  for (const [label, { calls, textState }] of cases) {
    expect(calls.filter((c) => c.op === 'fillText'), `${label}: fillText`).toEqual([]);
    // …and it never even sets up to write: no font, no alignment, no measurement. Restoring
    // the label needs all of this back, so a half-restoration cannot slip through either.
    expect(textState, `${label}: text state touched`).toEqual([]);
    // Not a vacuous pass on an empty canvas: the stack really did paint.
    expect(calls.filter((c) => c.op === 'fillRect').length, `${label}: blocks`).toBeGreaterThan(0);
  }
});

test('a hold too narrow for any word is still painted as a block', () => {
  // The surviving half of the old AC3 test. A 15-minute hold used to be the "unlabelled,
  // never clipped mid-word" case; what still matters is that it is a visible reservation.
  const narrow = paint([
    optionRibbon(stackOption({ lanes: 3, publicLanes: 1, owner: 'SC Oerlikon', start: '08:00', end: '08:15' })),
  ]);
  expect(narrow.filter((c) => c.op === 'fillRect' && c.fill === 'LANERESERVED').length).toBe(2);
});

test('a NAMED public hold is still painted as public water, never reclassified as reserved', () => {
  // The surviving half of "a NAMED public hold is still drawn unlabelled". A Belegungsplan
  // MAY name the party a public hold was booked under (a Verein hosting an open session).
  // The renderer must key the ink off `seg.public`, so that lane stays teal.
  const calls = paint([
    optionRibbon(
      stackOption({ lanes: 2, publicLanes: 1, publicOwner: 'SV Limmat', owner: 'SC Oerlikon' }),
    ),
  ]);
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANEPUBLIC').length).toBe(1);
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANERESERVED').length).toBe(1);
});

test('LANE_BAND_MIN_H is what the board row height buys — bands, not labels', () => {
  // The re-founded constant. The arithmetic is the one the owner-label gate used to justify
  // (`h·0.8/n − 1 ≥ 7 ⟺ h ≥ 10n`), on a reason that still exists: below 7px a band stops
  // reading as its own lane and the stack stripes into a hatch. Same counterfactual as
  // before — at the old fixed 46 a 6-lane basin gave 5.13px bands — now stated about the
  // bands themselves. The rowHeight ↔ laneBands link across the two files is in board.test.ts.
  expect(TAIL_H).toBe(46);
  expect(laneBands(6, MID, H)[0].height).toBeLessThan(LANE_BAND_MIN_H);
  for (const [lanes, h] of [[6, H6], [8, H8]] as const) {
    expect(laneBands(lanes, h / 2, h)[0].height, `${lanes} lanes at ${h}px`).toBeGreaterThanOrEqual(
      LANE_BAND_MIN_H,
    );
    // One pixel short and the band drops below the floor again — `10 × lanes` is the
    // load-bearing number, not a round one that happens to be big enough.
    expect(laneBands(lanes, (h - 1) / 2, h - 1)[0].height).toBeLessThan(LANE_BAND_MIN_H);
  }
});

// --- AC6: the best-public band -------------------------------------------------------

test('AC6 · the best-public band is painted BEHIND the stack, spanning its own window', () => {
  const option = stackOption({ lanes: 6, publicLanes: 4, best: { start: '11:00', end: '13:00', public_lanes: 6 } });
  const calls = paint([optionRibbon(option)]);
  const band = calls.filter((c) => c.op === 'fillRect' && c.fill === 'BESTBAND');
  expect(band.length).toBe(1);
  expect(band[0].args[0]).toBe(TS.X(11 * 60));
  expect(band[0].args[2]).toBe(TS.X(13 * 60) - TS.X(11 * 60));
  // Behind: every lane fill is painted AFTER the band.
  const bandAt = calls.indexOf(band[0]);
  const firstLane = calls.findIndex((c) => c.fill === 'LANETRACK' || c.fill === 'LANEPUBLIC');
  expect(bandAt).toBeLessThan(firstLane);
});

test('AC6 · no window → NO band at all, not a zero-width one', () => {
  const calls = paint([optionRibbon(stackOption({ lanes: 6, publicLanes: 4, best: null }))]);
  expect(calls.some((c) => c.fill === 'BESTBAND' || c.fill === 'BESTEDGE')).toBe(false);
  expect(calls.some((c) => c.stroke === 'BESTEDGE')).toBe(false);
  // The stack itself is unaffected.
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANETRACK').length).toBe(6);
});

// --- AC4 / I5: the honesty floor -----------------------------------------------------

test('AC4 · a pool with NO published plan keeps its hatched sheath — it never becomes a stack', () => {
  // The published universe is closed at 8 sheets: ~50 of 57 pools will never have a stack.
  // "Not published" must not degrade into "a stack with nothing free".
  const unpublished = optionRibbon({ facility: 'P', basin: 'b', access: 'PublicSwim', start: '08:00', end: '20:00' });
  expect(unpublished.variant).toBe('unpublished');
  const calls = paint([unpublished]);
  // Its capacity sheath is still there…
  expect(calls.some((c) => c.op === 'fillRect' && c.fill === 'SHEATH')).toBe(true);
  // …with the diagonal hatch and the dotted outline that make it its own state.
  expect(calls.some((c) => c.op === 'strokeRect' && c.dash.length > 0)).toBe(true);
  expect(calls.filter((c) => c.op === 'lineTo').length).toBeGreaterThan(10); // the hatch
  // And NONE of the stack's marks: no lane bands, no owner text, no best-window band.
  for (const ink of ['LANETRACK', 'LANEPUBLIC', 'LANERESERVED', 'BESTBAND']) {
    expect(calls.some((c) => c.fill === ink)).toBe(false);
  }
  expect(calls.some((c) => c.op === 'fillText')).toBe(false);
});

test('I5 · an empty stack, a thin stack and "not published" paint three DIFFERENT pictures', () => {
  const sig = (ribbon: RenderRibbon) =>
    JSON.stringify(paint([ribbon]).map((c) => [c.op, c.fill, c.stroke, c.dash.length]));
  const noPlan = sig(optionRibbon({ facility: 'P', basin: 'b', access: 'PublicSwim', start: '08:00', end: '20:00' }));
  const nothingFree = sig(optionRibbon(stackOption({ lanes: 6, publicLanes: 0 })));
  const oneFree = sig(optionRibbon(stackOption({ lanes: 6, publicLanes: 1 })));
  expect(new Set([noPlan, nothingFree, oneFree]).size).toBe(3);
  // The two stacks differ in HOW MANY lanes read as free, not merely in some detail.
  expect(nothingFree.includes('LANEPUBLIC')).toBe(false);
  expect(oneFree.includes('LANEPUBLIC')).toBe(true);
});

test('the dispatch is not a fallthrough: each variant reaches its OWN painter', () => {
  const stack = paint([optionRibbon(stackOption({ lanes: 6, publicLanes: 3 }))]);
  const lanes = paint([
    optionRibbon({
      facility: 'P', basin: 'b', access: 'PublicSwim', start: '08:00', end: '20:00',
      lane_timeline: { segments: [{ start: '08:00', end: '20:00', lane_count: 6, public_lanes: 3, reserved_lanes: 3 }] },
    }),
  ]);
  // The counts-only ribbon paints ONE body about the mid-line; the stack paints per-lane
  // bands. If `lanestack` fell through to either neighbour this equality would hold.
  expect(stack.some((c) => c.fill === 'LANETRACK')).toBe(true);
  expect(lanes.some((c) => c.fill === 'LANETRACK')).toBe(false);
  expect(lanes.some((c) => c.op === 'fill' && c.fill === 'PUBLIC')).toBe(true);
  expect(stack.some((c) => c.op === 'fill')).toBe(false);
});

// --- The phone tail ------------------------------------------------------------------

test('at phone width the stack degrades by dropping LABELS, never by dropping lanes', () => {
  // `daytail.ts` calls the same `drawRibbons` with a ~340px timescale. The plan puts the
  // phone-specific treatment out of scope, so what matters is that it stays legible: six
  // bands still painted, and not one clipped owner name among them.
  const ribbon = optionRibbon(stackOption({ lanes: 6, publicLanes: 4, owner: 'SC Oerlikon' }));
  const calls = paint([ribbon], tailTimescale(340));
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANETRACK').length).toBe(6);
  expect(calls.filter((c) => c.op === 'fillRect' && c.fill === 'LANEPUBLIC').length).toBe(4);
  expect(calls.some((c) => c.op === 'fillText')).toBe(false);
  // Nothing is painted outside the tail's own width.
  for (const c of calls.filter((x) => x.op === 'fillRect')) {
    expect(c.args[0]).toBeGreaterThanOrEqual(-1);
    expect(c.args[0] + c.args[2]).toBeLessThanOrEqual(341);
  }
});
