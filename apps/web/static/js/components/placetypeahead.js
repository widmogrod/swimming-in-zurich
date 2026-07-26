// PlaceTypeahead — place → {lat, lon, label}. A combobox over curated presets
// PLUS a "use my location" button. Two documented behaviours S1 must prove:
//   - select-on-focus: focusing the input selects its whole text so typing
//     replaces the query rather than appending to it.
//   - geolocation fallback: "use my location" calls navigator.geolocation; if it
//     is unavailable OR the permission is denied, it falls back to the first
//     preset (emitted with source:'fallback' + a reason) instead of dead-ending.
//
// `geolocation` is injectable (props.geolocation) so the fallback path is
// unit-testable without a browser; it defaults to navigator.geolocation.

import { filterOptions } from './keynav.js';

/**
 * @param {import('../domtypes.js').El} el
 * @param {{props?: Record<string, unknown>, onChange?: (...args: any[]) => void}} [opts]
 * @returns {{el: import('../domtypes.js').El, input: import('../domtypes.js').El, geoBtn: import('../domtypes.js').El, useLocation: unknown, isOpen(): boolean}}
 */
export function createPlaceTypeahead(el, { props = {}, onChange } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const presets = props.presets || [];
  const disabled = !!props.disabled;
  const geolocation =
    props.geolocation !== undefined
      ? props.geolocation
      : (globalThis.navigator && globalThis.navigator.geolocation) || null;
  const fallback = props.fallback || presets[0] || null;
  let open = false;
  let filtered = presets.slice();

  el.classList.add('ui-place');

  const input = doc.createElement('input');
  input.setAttribute('type', 'text');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('autocomplete', 'off');
  if (props.label) input.setAttribute('aria-label', props.label);
  if (props.placeholder) input.setAttribute('placeholder', props.placeholder);
  if (disabled) {
    input.disabled = true;
    input.setAttribute('aria-disabled', 'true');
    el.classList.add('is-disabled');
  }

  const geoBtn = doc.createElement('button');
  geoBtn.setAttribute('type', 'button');
  geoBtn.classList.add('ui-place__geo');
  geoBtn.textContent = props.geoLabel || 'Use my location';
  if (disabled) {
    geoBtn.disabled = true;
    geoBtn.setAttribute('aria-disabled', 'true');
  }

  const list = doc.createElement('ul');
  list.setAttribute('role', 'listbox');

  function setOpen(v) {
    open = !!v && !disabled;
    input.setAttribute('aria-expanded', String(open));
    list.style.display = open ? '' : 'none';
    el.classList.toggle('is-open', open);
  }

  function renderList() {
    list.textContent = '';
    filtered.forEach((p) => {
      const li = doc.createElement('li');
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      li.classList.add('ui-place__opt');
      li.textContent = p.label;
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        choosePreset(p);
      });
      list.appendChild(li);
    });
  }

  function choosePreset(p) {
    input.value = p.label;
    setOpen(false);
    if (onChange) {
      onChange({ lat: p.lat, lon: p.lon, label: p.label, source: p.source || 'preset' });
    }
  }

  function fallbackTo(reason) {
    setOpen(false);
    if (fallback && onChange) {
      onChange({
        lat: fallback.lat,
        lon: fallback.lon,
        label: fallback.label,
        source: 'fallback',
        reason,
      });
    }
  }

  function useLocation() {
    if (disabled) return;
    if (!geolocation || typeof geolocation.getCurrentPosition !== 'function') {
      fallbackTo('geolocation-unavailable');
      return;
    }
    geolocation.getCurrentPosition(
      (pos) => {
        setOpen(false);
        if (onChange) {
          onChange({
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            label: props.hereLabel || 'My location',
            source: 'geolocation',
          });
        }
      },
      () => fallbackTo('geolocation-denied'),
    );
  }

  // select-on-focus.
  input.addEventListener('focus', () => {
    if (disabled) return;
    input.select();
    filtered = presets.slice();
    renderList();
    setOpen(true);
  });
  input.addEventListener('input', () => {
    filtered = filterOptions(presets, input.value, props.filterFn);
    renderList();
    setOpen(true);
  });
  geoBtn.addEventListener('click', useLocation);

  el.appendChild(input);
  el.appendChild(geoBtn);
  el.appendChild(list);
  renderList();
  setOpen(false);

  return { el, input, geoBtn, useLocation, isOpen: () => open };
}
