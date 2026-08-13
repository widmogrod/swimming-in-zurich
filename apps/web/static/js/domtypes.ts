// domtypes.ts — the DOM surface the UI factories actually touch.
//
// Deliberately STRUCTURAL rather than `HTMLElement`. Every component factory in this
// codebase is duck-typed so the headless suites can hand it `_fakedom.js`'s FakeElement
// instead of a browser node — that is the whole reason the tests need no jsdom. Typing
// the factories as `HTMLElement` would be a lie the test suite disproves on line one.
//
// A real browser `HTMLElement` is NOT structurally assignable to `El` (its `style` is a
// CSSStyleDeclaration, its `children` an HTMLCollection). That is deliberate and costs
// exactly one documented cast at each boundary where real DOM enters the app — see
// `asEl()` below — after which everything downstream is properly typed.

export interface ElClassList {
  add(...classes: string[]): void;
  remove(...classes: string[]): void;
  toggle(cls: string, force?: boolean): boolean;
  contains(cls: string): boolean;
}

/** The minimal event shape the factories read (real Event and FakeElement's synthetic
 *  event both satisfy it). */
export interface ElEvent {
  type: string;
  target: unknown;
  key?: string;
  preventDefault(): void;
  stopPropagation(): void;
}

export interface El {
  tagName: string;
  ownerDocument: Doc | null;
  classList: ElClassList;
  className: string;
  id: string;
  textContent: string;
  innerHTML: string;
  value: string;
  checked: boolean;
  disabled: boolean;
  /** Optional: present on real nodes and on <button>/<input>, absent from FakeElement. */
  type?: string;
  dataset: Record<string, string | undefined>;
  style: Record<string, string>;
  children: El[];
  parentNode: El | null;
  setAttribute(name: string, value: string): void;
  getAttribute(name: string): string | null;
  hasAttribute(name: string): boolean;
  removeAttribute(name: string): void;
  appendChild(child: El): El;
  /** Optional: FakeElement models append-only trees and never removes. */
  removeChild?(child: El): El;
  addEventListener(type: string, handler: (ev: ElEvent) => void): void;
  focus(): unknown;
  click(): unknown;
  select(): unknown;
  /** Real-DOM selector search; absent on FakeElement (which uses query/queryAll). */
  querySelectorAll?(selector: string): Iterable<El>;
  /** Test-only recursive search (FakeElement); absent on real nodes. */
  query?(pred: (el: El) => boolean): El | null;
  queryAll?(pred: (el: El) => boolean, acc?: El[]): El[];
}

export interface Doc {
  createElement(tag: string): El;
  /** Present on a real document, absent from FakeDocument — the header stamps
   *  `[data-theme]` on it when no explicit root is supplied. */
  documentElement?: El | null;
  activeElement?: El | null;
  defaultView?: WindowLike | null;
}

export interface WindowLike {
  getComputedStyle(el: El): {
    color: string;
    getPropertyValue(p: string): string;
  };
  matchMedia?(q: string): { matches: boolean };
  requestAnimationFrame?(cb: (t: number) => void): number;
  cancelAnimationFrame?(h: number): void;
}

/**
 * The ONE documented crossing from real browser DOM into the structural `El` world.
 *
 * Used at the composition root (app.ts) and the dev preview pages, where genuine
 * `document.getElementById` results enter. Everything below that boundary is typed.
 */
export function asEl(node: unknown): El {
  return node as El;
}

/** The same crossing for a real `document`. */
export function asDoc(node: unknown): Doc {
  return node as Doc;
}
