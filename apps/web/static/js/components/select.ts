// Select — the design system's ONE dropdown skin over a native `<select>`.
//
// Why a native control rather than a listbox of our own (as `.ui-combo` does):
// a Select is for a short, fixed, non-searchable set where the platform's own
// keyboard handling, screen-reader semantics and — decisively — the mobile
// picker are worth more than the styling control we give up. `.ui-combo` exists
// for the other case (long, searchable, decorated options).
//
// The pill/field chrome lives on the WRAPPER, never on the `<select>`:
//   <span class="ui-select">
//     <span class="ui-select__icon">  ← optional leading glyph (iconSvg)
//     <select class="ui-select__control">
//   </span>
// A bare styled `<select>` ignores `background` on macOS unless `appearance` is
// reset, and it can hold neither a leading glyph nor our own caret — so the
// control is stripped flat and the wrapper carries border, background, caret
// (`::after`) and the focus ring. The caret is ours, so it inherits
// `currentColor` and follows the theme instead of the platform.
//
// The OPTION LIST is drawn by the OS and is not ours to style — that is the
// price of the native control, and the reason this primitive keeps the closed
// state visually identical to its `.ui-*` neighbours.

import { asDoc, type El } from '../domtypes.js';
import { iconSvg } from './iconset.js';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

/** `field` matches the toolbar inputs (`--r-sm`); `pill` matches the header controls. */
export type SelectVariant = 'field' | 'pill';

export interface SelectProps {
  options?: SelectOption[];
  value?: string | null;
  /** Accessible name. A Select has no visible label of its own. */
  label?: string;
  /** An `iconset` glyph name rendered ahead of the control (decorative). */
  icon?: string;
  variant?: SelectVariant;
  disabled?: boolean;
}

export interface SelectOpts {
  props?: SelectProps;
  onChange?: (value: string) => void;
}

export function createSelect<T extends El>(el: T, { props = {}, onChange }: SelectOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const options = props.options || [];
  const disabled = !!props.disabled;
  let value = props.value != null ? props.value : (options[0]?.value ?? '');

  el.classList.add('ui-select');
  if (props.variant === 'pill') el.classList.add('ui-select--pill');
  if (disabled) el.classList.add('is-disabled');

  if (props.icon) {
    const icon = doc.createElement('span');
    icon.classList.add('ui-select__icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = iconSvg(props.icon);
    el.appendChild(icon);
  }

  const control = doc.createElement('select');
  control.classList.add('ui-select__control');
  // No explicit `role`: a native <select> already exposes one, and overriding it
  // is how you lose the platform picker's semantics.
  if (props.label) control.setAttribute('aria-label', props.label);
  if (disabled) {
    control.disabled = true;
    control.setAttribute('aria-disabled', 'true');
  }

  for (const option of options) {
    const node = doc.createElement('option');
    node.value = option.value;
    node.textContent = option.label;
    if (option.disabled) node.disabled = true;
    if (option.value === value) node.setAttribute('selected', 'selected');
    control.appendChild(node);
  }
  control.value = value;

  control.addEventListener('change', () => {
    if (disabled) {
      control.value = value; // refuse; restore
      return;
    }
    const next = control.value;
    if (next === value) return;
    value = next;
    if (onChange) onChange(value);
  });

  el.appendChild(control);

  return {
    el,
    control,
    get value() {
      return value;
    },
    setValue(next: string) {
      value = next;
      control.value = next;
    },
  };
}
