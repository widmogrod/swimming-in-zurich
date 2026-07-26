import { expect, test } from 'vitest';

import { mount, type FakeElement } from './_fakedom.js';
import { fake, must } from '../testutil.js';
import { createPlaceTypeahead, type GeoPosition, type Place } from './placetypeahead.js';

const PLACES = [
  { value: 'hb', label: 'Zürich HB', lat: 47.3779, lon: 8.5403 },
  { value: 'bellevue', label: 'Bellevue', lat: 47.3671, lon: 8.5451 },
];

test('PlaceTypeahead selects the whole query text on focus', () => {
  const el = mount();
  const api = createPlaceTypeahead(el, { props: { presets: PLACES } });
  expect(fake(api.input).selectionCalls).toBe(0);
  fake(api.input).focus();
  expect(fake(api.input).selectionCalls).toBe(1); // select-on-focus
  expect(api.input.getAttribute('aria-expanded')).toBe('true');
});

test('PlaceTypeahead emits a preset selection with its coordinates', () => {
  const el = mount();
  const seen: Place[] = [];
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES },
    onChange: (p: Place) => seen.push(p),
  });
  fake(api.input).focus();
  must(el.query((c: FakeElement) => c.classList.contains('ui-place__opt'))).dispatch('mousedown');
  expect(seen.length).toBe(1);
  expect({ lat: seen[0].lat, lon: seen[0].lon, source: seen[0].source }).toEqual({ lat: 47.3779, lon: 8.5403, source: 'preset' });
});

test('Use-my-location emits geolocation coordinates on success', () => {
  const el = mount();
  const seen: Place[] = [];
  const geolocation = {
    getCurrentPosition: (ok: (p: GeoPosition) => void) => ok({ coords: { latitude: 47.4, longitude: 8.5 } }),
  };
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation },
    onChange: (p: Place) => seen.push(p),
  });
  fake(api.geoBtn).click();
  expect(seen.length).toBe(1);
  expect(seen[0].source).toBe('geolocation');
  expect(seen[0].lat).toBe(47.4);
});

test('Use-my-location falls back to a preset when geolocation is unavailable', () => {
  const el = mount();
  const seen: Place[] = [];
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation: null },
    onChange: (p: Place) => seen.push(p),
  });
  fake(api.geoBtn).click();
  expect(seen.length).toBe(1);
  expect(seen[0].source).toBe('fallback');
  expect(seen[0].reason).toBe('geolocation-unavailable');
  expect(seen[0].label).toBe('Zürich HB');
});

test('Use-my-location falls back when permission is denied', () => {
  const el = mount();
  const seen: Place[] = [];
  const geolocation = {
    getCurrentPosition: (_ok: (p: GeoPosition) => void, err: (e?: unknown) => void) => err({ code: 1, message: 'denied' }),
  };
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation },
    onChange: (p: Place) => seen.push(p),
  });
  fake(api.geoBtn).click();
  expect(seen[0].source).toBe('fallback');
  expect(seen[0].reason).toBe('geolocation-denied');
});

test('PlaceTypeahead input carries combobox ARIA', () => {
  const el = mount();
  const api = createPlaceTypeahead(el, { props: { presets: PLACES, label: 'Place' } });
  expect(api.input.getAttribute('role')).toBe('combobox');
  expect(api.input.getAttribute('aria-expanded')).toBe('false');
  expect(api.input.getAttribute('aria-label')).toBe('Place');
});
