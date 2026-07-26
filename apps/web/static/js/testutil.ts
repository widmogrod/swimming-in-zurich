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
