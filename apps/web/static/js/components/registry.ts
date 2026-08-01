// registry.js — the single map from a component NAME (the data-component token
// the server writes into each gallery mount) to its factory + a props builder
// for each documented gallery state. The Python gallery route owns the list of
// names/states it renders; this owns how each state is realised in the DOM.
// gallery.js walks the mounts and calls these; the ARIA tests import REGISTRY to
// build every primitive headlessly.

import { createSegmentedControl } from './segmentedcontrol.js';
import { createChipGroup } from './chipgroup.js';
import { createCombobox } from './combobox.js';
import { createSelect } from './select.js';
import { createPlaceTypeahead } from './placetypeahead.js';
import { createToggle } from './toggle.js';
import { createDateStepper } from './datestepper.js';
import { createStatePill } from './statepill.js';
import { createEligibilityBadge } from './eligibilitybadge.js';
import { createLengthLanesBadge } from './lengthlanesbadge.js';
import { createProvenanceStamp } from './provenancestamp.js';
import { createIconSet } from './iconset.js';

const MODES = [
  { value: 'day', label: 'Day' },
  { value: 'pool', label: 'Pool' },
];
const AGES = [
  { value: '6', label: 'Under 12' },
  { value: '16', label: 'Teen' },
  { value: '34', label: 'Adult' },
  { value: '70', label: 'Senior' },
];
const POOLS = [
  { value: 'oerlikon', label: 'Hallenbad Oerlikon' },
  { value: 'city', label: 'Hallenbad City' },
  { value: 'bungert', label: 'Hallenbad Bungertwies', closed: true },
];
const LOCALES = [
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
  { value: 'fr', label: 'Français' },
];
const PLACES = [
  { value: 'hb', label: 'Zürich HB', lat: 47.3779, lon: 8.5403 },
  { value: 'bellevue', label: 'Bellevue', lat: 47.3671, lon: 8.5451 },
];

export const REGISTRY = {
  'segmented-control': {
    create: createSegmentedControl,
    interactive: true,
    props: (state: string) => ({
      label: 'View mode',
      variant: 'mode',
      items: MODES,
      selected: state === 'disabled' ? 'day' : 'pool',
      disabled: state === 'disabled',
    }),
  },
  'chip-group': {
    create: createChipGroup,
    interactive: true,
    props: (state: string) => ({
      label: 'Age',
      items: AGES,
      selected: state === 'selected' ? '34' : null,
      disabled: state === 'disabled',
    }),
  },
  combobox: {
    create: createCombobox,
    interactive: true,
    props: (state: string) => ({
      label: 'Pool',
      placeholder: 'Search pools…',
      options: state === 'empty' ? [] : POOLS,
      value: state === 'selected' ? 'oerlikon' : null,
      emptyText: 'No pools match',
      disabled: state === 'disabled',
    }),
  },
  select: {
    create: createSelect,
    interactive: true,
    props: (state: string) => ({
      label: 'Language',
      icon: 'globe',
      variant: state === 'pill' ? 'pill' : 'field',
      options: LOCALES,
      value: 'de',
      disabled: state === 'disabled',
    }),
  },
  'place-typeahead': {
    create: createPlaceTypeahead,
    interactive: true,
    props: (state: string) => ({
      label: 'Place',
      placeholder: 'Where from?',
      presets: state === 'empty' ? [] : PLACES,
      disabled: state === 'disabled',
    }),
  },
  toggle: {
    create: createToggle,
    interactive: true,
    props: (state: string) => ({
      label: state === 'disabled' ? 'Busyness' : 'Lap only',
      checked: state === 'selected',
      disabled: state === 'disabled',
      reason: state === 'disabled' ? 'Busyness data is not available yet' : undefined,
    }),
  },
  'date-stepper': {
    create: createDateStepper,
    interactive: true,
    props: (state: string) => ({
      label: 'Selected day',
      value: '2026-07-23',
      today: '2026-07-23',
      min: state === 'disabled' ? '2026-07-23' : '2026-07-01',
      max: '2026-08-31',
    }),
  },
  'state-pill': {
    create: createStatePill,
    interactive: false,
    props: (state: string) => ({ state }),
  },
  'eligibility-badge': {
    create: createEligibilityBadge,
    interactive: false,
    props: (state: string) => ({
      state,
      reason:
        state === 'no'
          ? 'Women-only session'
          : state === 'chk'
            ? 'Confirm admission on site'
            : 'Public lane swim',
    }),
  },
  'length-lanes-badge': {
    create: createLengthLanesBadge,
    interactive: false,
    props: (state: string) =>
      state === 'empty' ? { length_m: null } : { length_m: 25, lanes: 6 },
  },
  'provenance-stamp': {
    create: createProvenanceStamp,
    interactive: false,
    props: (state: string) => ({
      freshness: state,
      source: 'stadt-zuerich.ch',
      valid_as_of: '2026-07-18',
    }),
  },
  'icon-set': {
    create: createIconSet,
    interactive: false,
    props: () => ({}),
  },
};
