// _selectgroup.js — shared roving single-select group used by BOTH
// SegmentedControl and ChipGroup (identical ARIA + key behaviour, different
// skin). role=group of `aria-pressed` buttons with roving tabindex and
// arrow-key navigation. Not a component itself (leading underscore); the two
// public factories are thin skins over it.
//
// The document is derived from the mount's ownerDocument, so a fake mount (from
// the test's FakeDocument) drives a fully headless build — no globalThis.document.

import { rovingIndex } from './keynav.js';

export function buildSelectGroup(el, { props = {}, onChange } = {}, classes = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const items = props.items || [];
  const disabled = !!props.disabled;
  let selected = props.selected != null ? props.selected : items[0] && items[0].value;

  el.classList.add(classes.root || 'ui-seg');
  el.setAttribute('role', 'group');
  if (props.label) el.setAttribute('aria-label', props.label);
  if (disabled) el.setAttribute('aria-disabled', 'true');

  const buttons = items.map((item, i) => {
    const b = doc.createElement('button');
    b.setAttribute('type', 'button');
    b.classList.add(classes.opt || 'ui-seg__opt');
    b.textContent = item.label;
    b.dataset.value = item.value;
    if (disabled) {
      b.disabled = true;
      b.setAttribute('aria-disabled', 'true');
    }
    b.addEventListener('click', () => choose(i, true));
    b.addEventListener('keydown', (e) => onKey(e, i));
    el.appendChild(b);
    return b;
  });

  function render() {
    buttons.forEach((b) => {
      const on = b.dataset.value === selected;
      b.setAttribute('aria-pressed', String(on));
      b.setAttribute('tabindex', on ? '0' : '-1');
      b.classList.toggle('is-selected', on);
    });
  }

  function choose(i, focus) {
    if (disabled) return;
    const item = items[i];
    if (!item) return;
    const changed = item.value !== selected;
    selected = item.value;
    render();
    if (focus) buttons[i].focus();
    if (changed && onChange) onChange(selected);
  }

  function onKey(e, i) {
    if (disabled) return;
    const next = rovingIndex(i, items.length, e.key);
    if (next === null) return;
    e.preventDefault();
    choose(next, true);
  }

  render();
  return {
    el,
    buttons,
    get value() {
      return selected;
    },
    setValue(v) {
      selected = v;
      render();
    },
  };
}
