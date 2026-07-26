// Combobox (searchable) — the pool selector. ARIA combobox+listbox: the input
// carries role=combobox / aria-expanded / aria-controls / aria-activedescendant;
// each option is role=option with aria-selected. Type to filter, ↑/↓ to move the
// active option, Enter to commit, Esc to close. Options may carry `closed: true`
// (renders a closed badge). Empty filter shows an explicit "no matches" row.

import { asDoc, type El } from '../domtypes.js';
import { listboxIndex, filterOptions } from './keynav.js';

let _seq = 0;

export interface ComboOption {
  value: string;
  label: string;
  closed?: boolean;
  note?: string;
  [k: string]: unknown;
}

export interface ComboboxProps {
  options?: ComboOption[];
  value?: string | null;
  disabled?: boolean;
  label?: string;
  placeholder?: string;
  emptyText?: string;
  filterFn?: (option: ComboOption, query: string) => boolean;
}

export function createCombobox<T extends El>(
  el: T,
  { props = {}, onChange }: { props?: ComboboxProps; onChange?: (value: string) => void } = {},
) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const allOptions = props.options || [];
  const disabled = !!props.disabled;
  let value = props.value != null ? props.value : null;
  let open = false;
  let active = -1;
  let filtered = allOptions.slice();
  let optionEls: El[] = [];

  const listId = `ui-combo-${(_seq += 1)}`;

  el.classList.add('ui-combo');

  const input = doc.createElement('input');
  input.setAttribute('type', 'text');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', listId);
  input.setAttribute('autocomplete', 'off');
  if (props.label) input.setAttribute('aria-label', props.label);
  if (props.placeholder) input.setAttribute('placeholder', props.placeholder);
  if (disabled) {
    input.disabled = true;
    input.setAttribute('aria-disabled', 'true');
    el.classList.add('is-disabled');
  }

  const list = doc.createElement('ul');
  list.setAttribute('role', 'listbox');
  list.setAttribute('id', listId);
  list.id = listId;

  const selectedOpt = allOptions.find((o) => o.value === value);
  if (selectedOpt) input.value = selectedOpt.label;

  function updateActiveDescendant() {
    if (open && active >= 0 && optionEls[active]) {
      input.setAttribute('aria-activedescendant', optionEls[active].id);
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  function renderList() {
    list.textContent = ''; // clear (real + fake DOM)
    optionEls = filtered.map((o, i) => {
      const li = doc.createElement('li');
      const optId = `${listId}-opt-${i}`;
      li.setAttribute('id', optId);
      li.id = optId;
      li.setAttribute('role', 'option');
      li.classList.add('ui-combo__opt');
      li.dataset.value = o.value;
      li.setAttribute('aria-selected', String(o.value === value));
      li.classList.toggle('is-active', i === active);

      const text = doc.createElement('span');
      text.textContent = o.label;
      li.appendChild(text);
      // A muted trailing badge: `o.note` gives custom text (e.g. "no timetable yet"),
      // else `o.closed` renders the plain "closed" badge. Both share the same styling
      // so a caller can label unavailability HONESTLY (unknown ≠ closed).
      if (o.note || o.closed) {
        const badge = doc.createElement('span');
        badge.classList.add('ui-combo__closed');
        badge.textContent = o.note || 'closed';
        li.appendChild(badge);
      }
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        commit(o);
      });
      list.appendChild(li);
      return li;
    });
    if (!filtered.length) {
      const empty = doc.createElement('li');
      empty.classList.add('ui-combo__empty');
      empty.setAttribute('role', 'option');
      empty.setAttribute('aria-disabled', 'true');
      empty.textContent = props.emptyText || 'No matches';
      list.appendChild(empty);
    }
    updateActiveDescendant();
  }

  function setOpen(v: boolean) {
    open = !!v && !disabled;
    el.classList.toggle('is-open', open);
    input.setAttribute('aria-expanded', String(open));
    list.style.display = open ? '' : 'none';
    if (!open) {
      active = -1;
      updateActiveDescendant();
    }
  }

  function commit(o: ComboOption) {
    value = o.value;
    input.value = o.label;
    filtered = allOptions.slice();
    active = -1;
    renderList();
    setOpen(false);
    if (onChange) onChange(value);
  }

  input.addEventListener('focus', () => {
    if (disabled) return;
    filtered = allOptions.slice();
    active = -1;
    renderList();
    setOpen(true);
  });

  input.addEventListener('input', () => {
    filtered = filterOptions(allOptions, input.value ?? '', props.filterFn);
    active = -1;
    renderList();
    setOpen(true);
  });

  input.addEventListener('keydown', (e) => {
    if (disabled) return;
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (e.key === 'Enter') {
      if (open && active >= 0 && filtered[active]) {
        e.preventDefault();
        commit(filtered[active]);
      }
      return;
    }
    const ni = listboxIndex(active, filtered.length, e.key ?? '');
    if (ni === null) return;
    e.preventDefault();
    if (!open) setOpen(true);
    active = ni;
    renderList();
  });

  el.appendChild(input);
  el.appendChild(list);
  renderList();
  setOpen(false);

  return {
    el,
    input,
    list,
    get value() {
      return value;
    },
    open: () => setOpen(true),
    close: () => setOpen(false),
    state: () => ({ open, active, filtered: filtered.slice() }),
  };
}
