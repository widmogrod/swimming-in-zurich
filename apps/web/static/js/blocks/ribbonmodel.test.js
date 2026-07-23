import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  accessFamily,
  optionRibbon,
  statusRibbon,
  ribbonsFor,
  ACCESS_FAMILY,
} from './ribbonmodel.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8'));

test('accessFamily maps every domain access class to its colour family', () => {
  assert.equal(accessFamily('PublicSwim'), 'public');
  assert.equal(accessFamily('LaneSwim'), 'lane');
  assert.equal(accessFamily('FamilyTime'), 'family');
  assert.equal(accessFamily('WomenOnly'), 'women');
  assert.equal(accessFamily('SeniorsOnly'), 'seniors');
  assert.equal(accessFamily('AdultsOnly'), 'adults');
  assert.equal(accessFamily('SchoolReserved'), 'school');
  assert.equal(accessFamily('ClubReserved'), 'club');
  assert.equal(accessFamily('SomethingNew'), 'other');
});

test('the synthetic fixture exercises all eight colour families', () => {
  const { options } = load('access_families.json');
  const families = new Set(options.map((o) => accessFamily(o.access)));
  for (const fam of Object.values(ACCESS_FAMILY)) {
    assert.ok(families.has(fam), `fixture missing family ${fam}`);
  }
});

test('closed status → a DASHED closed ribbon carrying its detail', () => {
  const { statuses } = load('swim_day.json');
  const closed = statuses.find((s) => s.status === 'closed');
  const r = statusRibbon(closed);
  assert.equal(r.variant, 'closed');
  assert.equal(r.style, 'dashed');
  assert.equal(r.detail, closed.detail);
  assert.ok(r.detail.length > 0);
});

test('uncurated status → a DOTTED ghost ribbon (unknown ≠ closed)', () => {
  const { statuses } = load('swim_day.json');
  const un = statuses.find((s) => s.status === 'uncurated');
  const r = statusRibbon(un);
  assert.equal(r.variant, 'ghost');
  assert.equal(r.style, 'dotted');
  assert.notEqual(r.variant, statusRibbon({ status: 'closed', detail: '' }).variant);
});

test('an option WITH lane_timeline → a filled ribbon; thickness = public/lane_count, pinched where reserved>0, sheath present', () => {
  const { options } = load('swim_day.json');
  // the PublicSwim arc at Oerlikon carries BOTH a full (reserved=0) and pinched segment
  const withTimeline = options.find(
    (o) =>
      o.lane_timeline &&
      o.lane_timeline.segments.some((s) => s.reserved_lanes === 0) &&
      o.lane_timeline.segments.some((s) => s.reserved_lanes > 0),
  );
  const r = optionRibbon(withTimeline);
  assert.equal(r.variant, 'lanes');
  assert.equal(r.sheath, true);
  assert.ok(r.segments.length > 0);
  for (const [i, seg] of r.segments.entries()) {
    const src = withTimeline.lane_timeline.segments[i];
    assert.equal(seg.thickness, src.public_lanes / src.lane_count);
    assert.equal(seg.pinched, src.reserved_lanes > 0);
  }
  // the Oerlikon fixture contains BOTH a full (reserved=0) and a pinched (reserved>0) segment
  assert.ok(r.segments.some((s) => s.pinched === true), 'expected a pinched segment');
  assert.ok(r.segments.some((s) => s.pinched === false), 'expected a full segment');
  const full = r.segments.find((s) => s.pinched === false);
  assert.equal(full.thickness, 1); // public==lane_count when nothing reserved
});

test('an option WITHOUT lane_timeline → a "lane split not published" ribbon', () => {
  const { options } = load('swim_day.json');
  const noTimeline = options.find((o) => !o.lane_timeline);
  const r = optionRibbon(noTimeline);
  assert.equal(r.variant, 'unpublished');
  assert.equal(r.sheath, false);
  assert.equal(r.label, 'Lane split not published');
  assert.ok(r.segments === undefined);
});

test('publicFraction is 0 (not NaN) when a segment records no lanes', () => {
  const r = optionRibbon({
    facility: 'x', basin: 'y', access: 'PublicSwim', start: '08:00', end: '09:00',
    lane_timeline: { segments: [{ start: '08:00', end: '09:00', lane_count: 0, public_lanes: 0, reserved_lanes: 0, partial: true }] },
  });
  assert.equal(r.segments[0].thickness, 0);
});

test('ribbonsFor draws statuses first (background), then options (foreground)', () => {
  const day = load('swim_day.json');
  const oerlikon = {
    options: day.options.filter((o) => o.facility === 'Hallenbad Oerlikon'),
    statuses: day.statuses.filter((s) => s.facility === 'Hallenbad Oerlikon'),
  };
  const ribbons = ribbonsFor(oerlikon);
  assert.equal(ribbons.length, oerlikon.options.length + oerlikon.statuses.length);
  const firstOption = ribbons.findIndex((r) => r.kind === 'option');
  const lastStatus = ribbons.map((r) => r.kind).lastIndexOf('status');
  if (firstOption !== -1 && lastStatus !== -1) assert.ok(lastStatus < firstOption);
});
