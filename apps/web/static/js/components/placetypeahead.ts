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

import { asDoc, type El } from '../domtypes.js';
import { filterOptions } from './keynav.js';

export interface GeoPosition {
  coords: { latitude: number; longitude: number };
}

export interface Place {
  label: string;
  lat: number;
  lon: number;
  /** How the place was chosen: a preset, the browser geolocation, or a fallback after
   *  geolocation was denied/unavailable. Surfaced so the UI never implies a precision it
   *  does not have. */
  source?: string;
  /** Why a fallback was used (geolocation denied/unavailable) — never invented. */
  reason?: string;
}

export interface PlaceTypeaheadProps {
  presets?: Place[];
  disabled?: boolean;
  geolocation?: {
    getCurrentPosition(ok: (p: GeoPosition) => void, err: (e?: unknown) => void): void;
  } | null;
  fallback?: Place | null;
  label?: string;
  placeholder?: string;
  geoLabel?: string;
  hereLabel?: string;
  filterFn?: (option: Place, query: string) => boolean;
}

export function createPlaceTypeahead<T extends El>(
  el: T,
  {
    props = {},
    onChange,
  }: { props?: PlaceTypeaheadProps; onChange?: (place: Place) => void } = {},
) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
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

  function setOpen(v: boolean) {
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

  function choosePreset(p: Place) {
    input.value = p.label;
    setOpen(false);
    if (onChange) {
      onChange({ lat: p.lat, lon: p.lon, label: p.label, source: p.source || 'preset' });
    }
  }

  function fallbackTo(reason: string) {
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
