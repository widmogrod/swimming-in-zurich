// board_render.test.ts — exercises the CANVAS renderers.
//
// The other board suites run headless, where `canvas.getContext('2d')` is absent and
// `drawRow` returns early — so every ribbon painter stayed unexecuted (and, once the
// module became TypeScript, unmeasured by the CRAP gate). This file hands the board a
// document whose canvases return a RECORDING 2D context, so the painters actually run.
//
// The assertions are deliberately structural (did we paint, in the right colours, within
// the plot) rather than pixel-exact: the point is that the drawing code is executed and
// self-consistent, not to pin an image.

import { expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { FakeDocument, type FakeElement } from "../components/_fakedom.js";
import {
  createBoard,
  dayRows,
  rowHeight,
  rowStatusLine,
  type BoardAnswer,
  type BoardWeek,
} from "./board.js";
import type { El } from "../domtypes.js";

const HERE = dirname(fileURLToPath(import.meta.url));
/** The committed `/swim` answer: its Hallenbad Oerlikon row carries a real 8-lane
 *  Belegungsplan with four named holders — the basin AC1 is actually about. */
const DAY = JSON.parse(
  readFileSync(join(HERE, "..", "..", "..", "tests", "fixtures", "swim_day.json"), "utf-8"),
) as BoardAnswer;

interface Call {
  op: string;
  args: unknown[];
}

/** A 2D context that records every call instead of rasterising. */
function recordingCtx(calls: Call[]): Record<string, unknown> {
  const op =
    (name: string) =>
    (...args: unknown[]) => {
      calls.push({ op: name, args });
    };
  return {
    save: op("save"),
    restore: op("restore"),
    beginPath: op("beginPath"),
    closePath: op("closePath"),
    moveTo: op("moveTo"),
    lineTo: op("lineTo"),
    arc: op("arc"),
    rect: op("rect"),
    clip: op("clip"),
    fill: op("fill"),
    stroke: op("stroke"),
    fillRect: op("fillRect"),
    strokeRect: op("strokeRect"),
    clearRect: op("clearRect"),
    fillText: op("fillText"),
    setLineDash: op("setLineDash"),
    // The lane stack MEASURES an owner's name before deciding to draw it (S4), so the
    // recorder must answer measureText or the painter cannot run at all.
    measureText: (s: string) => ({ width: String(s).length * 6 }),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    globalAlpha: 1,
    font: "",
    textAlign: "",
    textBaseline: "",
  };
}

/** A document whose <canvas> elements hand back the recording context, plus a window
 *  stub so the board's palette probe resolves colours instead of bailing out. */
function paintingDoc(calls: Call[]) {
  const doc = new FakeDocument();
  const create = doc.createElement.bind(doc);
  doc.createElement = (tag: string): FakeElement => {
    const el = create(tag);
    if (String(tag).toLowerCase() === "canvas") {
      (el as unknown as { getContext: () => unknown }).getContext = () =>
        recordingCtx(calls);
    }
    return el;
  };
  (doc as unknown as { defaultView: unknown }).defaultView = {
    getComputedStyle: () => ({ color: "rgb(1, 2, 3)", getPropertyValue: () => "" }),
  };
  return doc;
}

const answer = (options: unknown[], statuses: unknown[] = []): BoardAnswer =>
  ({ options, statuses }) as BoardAnswer;

const laneOption = {
  facility: "Hallenbad Oerlikon",
  basin: "50m",
  access: "LaneSwim",
  start: "09:00",
  end: "12:00",
  lane_timeline: {
    lane_count: 4,
    segments: [
      { start: "09:00", end: "10:30", public_lanes: 4, lane_count: 4 },
      { start: "10:30", end: "12:00", public_lanes: 2, lane_count: 4 },
    ],
  },
};

function mountBoard(calls: Call[], data: { day?: BoardAnswer; week?: BoardWeek }) {
  const doc = paintingDoc(calls);
  const host = doc.createElement("div");
  return createBoard(host as unknown as El, {
    data,
    filter: { mode: "day", gender: "", age: null },
    matchMedia: () => ({ matches: true }), // reduced motion → deterministic single paint
  });
}

test("a lane-split option paints ribbon geometry onto the row canvas", () => {
  const calls: Call[] = [];
  mountBoard(calls, { day: answer([laneOption]) });
  expect(calls.length).toBeGreaterThan(0);
  // The axis is cleared and the ribbon body is filled.
  expect(calls.some((c) => c.op === "clearRect")).toBe(true);
  expect(calls.some((c) => c.op === "fillRect" || c.op === "fill")).toBe(true);
});

/** Hallenbad City's Schwimmerbecken as `/swim` serves it: 6 lanes, the last two held by a
 *  named club. Shared by the geometry smoke test and AC1 — the same option has to produce
 *  both the 60px row and the two owner labels inside it. */
const stackOption = {
  facility: "Hallenbad City",
  basin: "Schwimmerbecken",
  basin_id: "city-50m",
  access: "PublicSwim",
  start: "09:00",
  end: "12:00",
  lane_day_view: {
    weekday: 2,
    lane_count: 6,
    strips: Array.from({ length: 6 }, (_, i) => ({
      lane: i + 1,
      segments: [
        i < 4
          ? { start: "09:00", end: "12:00", access: "PublicSwim", owner: null }
          : { start: "09:00", end: "12:00", access: "ClubReserved", owner: "SC Uster" },
      ],
    })),
  },
  lane_best_public: { start: "09:00", end: "11:00", public_lanes: 4 },
};

test("AC2 · a row with a lane plan paints its stack THROUGH the board, inside its OWN row box", () => {
  // [[lane-stack-board]]'s AC2, SUPERSEDED IN PART by board-order-and-defects S3 — which is
  // why the title says "its own row box" where it used to say ROW_H.
  // As shipped this asserted the stack stayed inside 46px — and it did, at the cost of 5.13px
  // lane bands that could not carry an owner name on any real basin. A row with a plan is now
  // `rowHeight(row)` tall (6 lanes → 60), so the box this stays inside is the row's own, and
  // the constant it is measured against is the one the board actually sized the canvas with.
  //
  // The smoke half of AC2: the pure geometry is asserted in ribbonrender.test.ts; what this
  // adds is that a real `/swim` option reaches `drawLaneStack` through `createBoard` — row
  // derivation, palette probe, dispatch and all.
  const calls: Call[] = [];
  mountBoard(calls, { day: answer([stackOption]) });
  const rects = calls.filter((c) => c.op === "fillRect");
  // 6 lane tracks + 6 lane blocks + the best-public band, at least.
  expect(rects.length).toBeGreaterThanOrEqual(13);
  // The box is the ROW's, not a constant copied into the test: six lanes → 60px.
  const h6 = rowHeight(dayRows(answer([stackOption]))[0]);
  expect(h6).toBe(60);
  for (const c of rects) {
    const y = c.args[1] as number;
    const h = c.args[3] as number;
    expect(y).toBeGreaterThanOrEqual(-1);
    expect(y + h).toBeLessThanOrEqual(h6 + 1);
  }
});

test("AC1 · City's 6 lanes and Oerlikon's 8 both paint their owners' NAMES", () => {
  // The defect this slice exists for. [[lane-stack-board]] shipped the owner label and the
  // 46px row together; at 6 lanes a band is 5.13px, `ownerLabelFits` refuses anything under
  // 7px, and so the name rendered on NO real Zürich basin — City has 6 lanes, Oerlikon 8.
  // Asserted end to end (fixture → dayRows → rowHeight → canvas → drawLaneStack), because
  // every part of that chain has to agree for a single word to land on the board.
  // Every string the board writes onto a canvas EXCEPT the axis' own "HH:00" hour ticks.
  const written = (calls: Call[]) =>
    calls
      .filter((c) => c.op === "fillText")
      .map((c) => String(c.args[0]))
      .filter((s) => !/^\d\d:00$/.test(s));

  const city: Call[] = [];
  mountBoard(city, { day: answer([stackOption]) }); // 6 lanes, lanes 5-6 held by SC Uster
  expect(written(city)).toEqual(["SC Uster", "SC Uster"]);

  // Oerlikon, from the COMMITTED `/swim` fixture: 8 lanes, four different real holders.
  const oerlikon: Call[] = [];
  mountBoard(oerlikon, { day: DAY });
  const names = new Set(written(oerlikon));
  for (const owner of ["SV Limmat", "Schule Liguster", "Wasserball ZH", "SC Oerlikon"]) {
    expect(names.has(owner), `${owner} is named on the board`).toBe(true);
  }
  // EXHAUSTIVE, so a public lane cannot quietly acquire a label as the row grows: the four
  // holders, and the Aemtler row's "no lane split published" caption — nothing else.
  expect([...names].sort()).toEqual([
    'Hours not published yet',
    'SC Oerlikon',
    'SV Limmat',
    'Schule Liguster',
    'Wasserball ZH',
  ]);
});

test("a closed row paints a DASHED status ribbon (never a solid public block)", () => {
  const calls: Call[] = [];
  mountBoard(calls, {
    day: answer([], [{ facility: "Shut", status: "closed", detail: "Sommerpause" }]),
  });
  const dashes = calls.filter((c) => c.op === "setLineDash");
  expect(dashes.length).toBeGreaterThan(0);
  // At least one non-empty dash pattern — the closed/unknown states are never solid.
  expect(dashes.some((c) => Array.isArray(c.args[0]) && (c.args[0] as number[]).length > 0)).toBe(
    true,
  );
});

test("an uncurated row paints too — 'hours not listed' is drawn, not skipped", () => {
  const calls: Call[] = [];
  mountBoard(calls, {
    day: answer([], [{ facility: "Unknown", status: "awaiting_scrape" }]),
  });
  expect(calls.some((c) => c.op === "clearRect")).toBe(true);
});

test("an option with NO published lane split still paints (the unpublished variant)", () => {
  const calls: Call[] = [];
  mountBoard(calls, {
    day: answer([
      { facility: "P", basin: "b", access: "PublicSwim", start: "08:00", end: "10:00" },
    ]),
  });
  expect(calls.some((c) => c.op === "fillRect" || c.op === "fill")).toBe(true);
});

test("every painted x stays inside the plot width", () => {
  // The board's containment contract: ribbons are drawn in plot coordinates, so nothing
  // is emitted beyond BOARD_PLOT (the card scrolls the track; it never overflows the page).
  const calls: Call[] = [];
  const board = mountBoard(calls, { day: answer([laneOption]) });
  const plot = board.timescale.PLOT;
  const xs = calls
    .filter((c) => c.op === "fillRect" || c.op === "strokeRect")
    .flatMap((c) => [c.args[0] as number, (c.args[0] as number) + (c.args[2] as number)]);
  expect(xs.length).toBeGreaterThan(0);
  for (const x of xs) {
    expect(x).toBeGreaterThanOrEqual(-1);
    expect(x).toBeLessThanOrEqual(plot + 1);
  }
});

test("the axis paints its hour ticks as text", () => {
  const calls: Call[] = [];
  mountBoard(calls, { day: answer([laneOption]) });
  expect(calls.some((c) => c.op === "fillText")).toBe(true);
});

test('a closure is stated ONCE — in the label column, never on the canvas', () => {
  // The plot used to repeat the label column's "Closed · <reason>" at the start of the
  // dashed rule — centred on the same y as the rule, in the same colour, so the row's own
  // dash struck the words through. The reason now lives only in the label column; the
  // plot keeps the dot + dashed rule, which already read as "shut all day".
  const status = {
    facility: 'Shut',
    status: 'closed',
    detail: 'Sommerpause',
    closure_code: 'seasonal_break',
    detail_params: {},
  };
  const label = rowStatusLine({ options: [], statuses: [status] });

  const calls: Call[] = [];
  mountBoard(calls, { day: answer([], [status]) });
  const painted = calls.filter((c) => c.op === 'fillText').map((c) => String(c.args[0]));

  expect(label?.text).toBe('Closed · Summer break');
  expect(painted.some((s) => s.startsWith('Closed') || s.includes('Summer break'))).toBe(false);
});
