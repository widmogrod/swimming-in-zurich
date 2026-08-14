import type { FakeElement } from "./components/_fakedom.js";
import type { El } from "./domtypes.js";

// testutil.ts — shared helpers for the headless component suites.

/**
 * Assert a queried node exists, and return it non-null.
 *
 * The suites are full of `el.query(hasClass('…'))` lookups whose result is immediately
 * dereferenced. `query` honestly returns `T | null`, so this narrows it at the one place
 * the test means "this node must be here" — and fails with a clear message when it is
 * not, rather than a `Cannot read properties of null` several lines later.
 *
 * Deliberately NOT a `!` non-null assertion: that would silence the checker without
 * producing a usable failure, and the lint gate rejects it.
 */
export function must<T>(value: T | null | undefined, what = "node"): T {
  if (value == null) throw new Error(`expected ${what} to exist`);
  return value;
}

/**
 * Narrow a structurally-typed `El` to the fake element the suites actually run against.
 *
 * Factories create their internal nodes via `doc.createElement`, which is typed to return
 * the structural `El` (real DOM has no `query`/`queryAll`). Under test that document is
 * always a FakeDocument, so this states that fact at the point of use instead of widening
 * the production types to suit the tests.
 */
export function fake(el: El): FakeElement {
  return el as FakeElement;
}

/** One recorded 2D-context call: the method name and the arguments it was given. */
export interface Call {
  op: string;
  args: unknown[];
}

/**
 * A 2D context that RECORDS every call instead of rasterising.
 *
 * The component suites run headless, where `canvas.getContext('2d')` is absent and every
 * canvas renderer returns early — so the painters stay unexecuted (and, once a module is
 * TypeScript, unmeasured by the CRAP gate). Handing a canvas this context runs the real
 * drawing code and leaves an inspectable trace of it.
 *
 * Assertions against the trace should stay STRUCTURAL — did we paint, in what order, at
 * which coordinates — rather than pixel-exact: the point is that the drawing code executes
 * and is self-consistent, not to pin an image.
 *
 * Shared by `blocks/board_render.test.ts` and `blocks/daytail.test.ts`, which paint the
 * SAME `ribbonrender` painters onto two surfaces; a second copy of this recorder would
 * drift from the first the next time a painter reaches for a new context method.
 */
export function recordingCtx(calls: Call[]): Record<string, unknown> {
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
    // A day tail rescales itself for the device pixel ratio before painting anything
    // (`daytail.ts` calls this FIRST), so without it the tail cannot be recorded at all.
    setTransform: op("setTransform"),
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
