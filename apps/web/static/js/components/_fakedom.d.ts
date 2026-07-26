// _fakedom.d.ts — types for the headless fake DOM (_fakedom.js).
//
// The implementation stays plain JS (it is test scaffolding, not shipped code), but the
// suites are now TypeScript and type-checked at full strictness, so they need a precise
// shape. Declaring it here — rather than converting _fakedom.js — keeps the runtime file
// untouched while giving every test a mount whose `query`/`queryAll`/`dispatch` helpers
// are REQUIRED, not optional as they are on the structural `El` (where real nodes, which
// lack them, also have to fit).

import type { El, ElEvent } from '../domtypes.js';

export interface FakeEvent extends ElEvent {
  defaultPrevented: boolean;
  [k: string]: unknown;
}

/** A fake element: the `El` surface, plus the test-only helpers, all required. */
export interface FakeElement extends El {
  ownerDocument: FakeDocument;
  attributes: Record<string, string>;
  children: FakeElement[];
  parentNode: FakeElement | null;
  selectionCalls: number;

  appendChild(child: El): FakeElement;
  dispatch(type: string, event?: Record<string, unknown>): FakeEvent;
  click(): FakeEvent;
  keydown(key: string, extra?: Record<string, unknown>): FakeEvent;
  focus(): FakeEvent;
  select(): void;
  query(pred: (el: FakeElement) => boolean): FakeElement | null;
  queryAll(pred: (el: FakeElement) => boolean, acc?: FakeElement[]): FakeElement[];
}

export declare class FakeDocument {
  activeElement: FakeElement | null;
  created: FakeElement[];
  createElement(tag: string): FakeElement;
}

/** A fresh mount element owned by a fresh FakeDocument. */
export declare function mount(): FakeElement;
