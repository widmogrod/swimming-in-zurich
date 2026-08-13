import { expect, test } from 'vitest';

import { mount } from '../components/_fakedom.js';
import { asCanvas } from './ribbonrender.js';
import {
  drawDayTail,
  tailBacking,
  tailTimescale,
  MAX_DPR,
  TAIL_DAY0,
  TAIL_DAY1,
  TAIL_H,
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
