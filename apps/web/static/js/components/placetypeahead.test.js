import test from 'node:test';
import assert from 'node:assert/strict';

import { mount } from './_fakedom.js';
import { createPlaceTypeahead } from './placetypeahead.js';

const PLACES = [
  { value: 'hb', label: 'Zürich HB', lat: 47.3779, lon: 8.5403 },
  { value: 'bellevue', label: 'Bellevue', lat: 47.3671, lon: 8.5451 },
];

test('PlaceTypeahead selects the whole query text on focus', () => {
  const el = mount();
  const api = createPlaceTypeahead(el, { props: { presets: PLACES } });
  assert.equal(api.input.selectionCalls, 0);
  api.input.focus();
  assert.equal(api.input.selectionCalls, 1); // select-on-focus
  assert.equal(api.input.getAttribute('aria-expanded'), 'true');
});

test('PlaceTypeahead emits a preset selection with its coordinates', () => {
  const el = mount();
  const seen = [];
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES },
    onChange: (p) => seen.push(p),
  });
  api.input.focus();
  el.query((c) => c.classList.contains('ui-place__opt')).dispatch('mousedown');
  assert.equal(seen.length, 1);
  assert.deepEqual(
    { lat: seen[0].lat, lon: seen[0].lon, source: seen[0].source },
    { lat: 47.3779, lon: 8.5403, source: 'preset' },
  );
});

test('Use-my-location emits geolocation coordinates on success', () => {
  const el = mount();
  const seen = [];
  const geolocation = {
    getCurrentPosition: (ok) => ok({ coords: { latitude: 47.4, longitude: 8.5 } }),
  };
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation },
    onChange: (p) => seen.push(p),
  });
  api.geoBtn.click();
  assert.equal(seen.length, 1);
  assert.equal(seen[0].source, 'geolocation');
  assert.equal(seen[0].lat, 47.4);
});

test('Use-my-location falls back to a preset when geolocation is unavailable', () => {
  const el = mount();
  const seen = [];
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation: null },
    onChange: (p) => seen.push(p),
  });
  api.geoBtn.click();
  assert.equal(seen.length, 1);
  assert.equal(seen[0].source, 'fallback');
  assert.equal(seen[0].reason, 'geolocation-unavailable');
  assert.equal(seen[0].label, 'Zürich HB');
});

test('Use-my-location falls back when permission is denied', () => {
  const el = mount();
  const seen = [];
  const geolocation = {
    getCurrentPosition: (_ok, err) => err({ code: 1, message: 'denied' }),
  };
  const api = createPlaceTypeahead(el, {
    props: { presets: PLACES, geolocation },
    onChange: (p) => seen.push(p),
  });
  api.geoBtn.click();
  assert.equal(seen[0].source, 'fallback');
  assert.equal(seen[0].reason, 'geolocation-denied');
});

test('PlaceTypeahead input carries combobox ARIA', () => {
  const el = mount();
  const api = createPlaceTypeahead(el, { props: { presets: PLACES, label: 'Place' } });
  assert.equal(api.input.getAttribute('role'), 'combobox');
  assert.equal(api.input.getAttribute('aria-expanded'), 'false');
  assert.equal(api.input.getAttribute('aria-label'), 'Place');
});
