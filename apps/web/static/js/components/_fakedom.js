// _fakedom.js — a MINIMAL fake DOM for headless component tests under
// `node --test`, with ZERO browser/jsdom dependency (the S1 ambiguity
// resolution). It records createElement/setAttribute/addEventListener and models
// only the small DOM surface the factories actually touch, plus test-only
// gesture helpers (click / keydown / focus) and recursive query helpers.
//
// Leading underscore + no `.test.js` suffix ⇒ the test runner never runs it as a
// test; it is imported by the *.test.js files.

class ClassList {
  constructor() {
    this._set = new Set();
  }

  add(...cs) {
    cs.forEach((c) => this._set.add(c));
  }

  remove(...cs) {
    cs.forEach((c) => this._set.delete(c));
  }

  toggle(c, force) {
    const on = force === undefined ? !this._set.has(c) : force;
    if (on) this._set.add(c);
    else this._set.delete(c);
    return on;
  }

  contains(c) {
    return this._set.has(c);
  }

  get value() {
    return [...this._set].join(' ');
  }
}

class FakeElement {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.attributes = {};
    this.classList = new ClassList();
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.parentNode = null;
    this.id = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.innerHTML = '';
    // Scroll position. A real element always HAS one (0 until something scrolls it), and
    // blocks that scroll a container into view both write and read it back, so the fake
    // owns it rather than materialising it on first assignment. It is a plain number: the
    // fake has no layout, so it does NOT clamp to a scrollable range and does NOT fire a
    // `scroll` event — a test that cares about either dispatches `scroll` itself.
    this.scrollLeft = 0;
    this.selectionCalls = 0;
    this._listeners = {};
    this._text = '';
  }

  // `className` mirrors the DOM: assigning a space-separated string REPLACES the
  // class set (so `.className = 'a b'` and `classList.add('a','b')` agree). Added in
  // S2 so blocks that build DOM via `.className =` are still classList-queryable.
  set className(v) {
    this.classList = new ClassList();
    String(v)
      .split(/\s+/)
      .filter(Boolean)
      .forEach((c) => this.classList.add(c));
  }

  get className() {
    return this.classList.value;
  }

  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'id') this.id = String(v);
  }

  getAttribute(k) {
    return k in this.attributes ? this.attributes[k] : null;
  }

  hasAttribute(k) {
    return k in this.attributes;
  }

  removeAttribute(k) {
    delete this.attributes[k];
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  addEventListener(type, handler) {
    (this._listeners[type] ||= []).push(handler);
  }

  dispatch(type, event = {}) {
    const ev = {
      type,
      target: this,
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
      stopPropagation() {},
      ...event,
    };
    (this._listeners[type] || []).forEach((h) => h.call(this, ev));
    return ev;
  }

  // --- test-only gesture helpers ---
  click() {
    return this.dispatch('click');
  }

  keydown(key, extra = {}) {
    return this.dispatch('keydown', { key, ...extra });
  }

  focus() {
    this.ownerDocument.activeElement = this;
    return this.dispatch('focus');
  }

  select() {
    this.selectionCalls += 1;
  }

  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }

  get textContent() {
    if (this.children.length) return this.children.map((c) => c.textContent).join('');
    return this._text;
  }

  // --- recursive search (tests only; factories never call these) ---
  query(pred) {
    for (const c of this.children) {
      if (pred(c)) return c;
      const found = c.query(pred);
      if (found) return found;
    }
    return null;
  }

  queryAll(pred, acc = []) {
    for (const c of this.children) {
      if (pred(c)) acc.push(c);
      c.queryAll(pred, acc);
    }
    return acc;
  }
}

export class FakeDocument {
  constructor() {
    this.activeElement = null;
    this.created = [];
  }

  createElement(tag) {
    const el = new FakeElement(tag, this);
    this.created.push(el);
    return el;
  }
}

/** A fresh mount element owned by a fresh FakeDocument. */
export function mount() {
  const doc = new FakeDocument();
  return doc.createElement('div');
}
