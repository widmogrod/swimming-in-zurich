import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import type {
  RibbonOption,
  RibbonStatus,
  RibbonTimelineSegment,
} from './ribbonmodel.js';
import { must } from '../testutil.js';

import {
  accessFamily,
  optionRibbon,
  statusRibbon,
  ribbonsFor,
  ACCESS_FAMILY,
} from './ribbonmodel.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, '..', '..', '..', 'tests', 'fixtures');
const load = <T,>(name: string): T =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as T;

test('accessFamily maps every domain access class to its colour family', () => {
  expect(accessFamily('PublicSwim')).toBe('public');
  expect(accessFamily('LaneSwim')).toBe('lane');
  expect(accessFamily('FamilyTime')).toBe('family');
  expect(accessFamily('WomenOnly')).toBe('women');
  expect(accessFamily('SeniorsOnly')).toBe('seniors');
  expect(accessFamily('AdultsOnly')).toBe('adults');
  expect(accessFamily('SchoolReserved')).toBe('school');
  expect(accessFamily('ClubReserved')).toBe('club');
  expect(accessFamily('SomethingNew')).toBe('other');
});

test('the synthetic fixture exercises all eight colour families', () => {
  const { options } = load<{ options: RibbonOption[] }>('access_families.json');
  const families = new Set(options.map((o: RibbonOption) => accessFamily(o.access ?? '')));
  for (const fam of Object.values(ACCESS_FAMILY)) {
    expect(families.has(fam)).toBeTruthy();
  }
});

test('closed status → a DASHED closed ribbon carrying its detail', () => {
  const { statuses } = load<{ statuses: RibbonStatus[] }>('swim_day.json');
  const closed = must(statuses.find((s: RibbonStatus) => s.status === 'closed'));
  const r = statusRibbon(closed);
  expect(r.variant).toBe('closed');
  expect(r.style).toBe('dashed');
  expect(r.detail).toBe(closed.detail);
  expect(must(r.detail as string | null).length > 0).toBeTruthy();
});

test('uncurated status → a DOTTED ghost ribbon (unknown ≠ closed)', () => {
  const { statuses } = load<{ statuses: RibbonStatus[] }>('swim_day.json');
  const un = must(statuses.find((s: RibbonStatus) => s.status === 'awaiting_scrape'));
  const r = statusRibbon(un);
  expect(r.variant).toBe('ghost');
  expect(r.style).toBe('dotted');
  expect(r.variant).not.toBe(statusRibbon({ status: 'closed', detail: '' }).variant);
});

test('an option WITH lane_timeline → a filled ribbon; thickness = public/lane_count, pinched where reserved>0, sheath present', () => {
  const { options } = load<{ options: RibbonOption[] }>('swim_day.json');
  // the PublicSwim arc at Oerlikon carries BOTH a full (reserved=0) and pinched segment
  const withTimeline = must(
    options.find(
      (o: RibbonOption) =>
        o.lane_timeline?.segments?.some((s) => s.reserved_lanes === 0) &&
        o.lane_timeline?.segments?.some((s) => Number(s.reserved_lanes) > 0),
    ),
  );
  const r = optionRibbon(withTimeline);
  expect(r.variant).toBe('lanes');
  expect(r.sheath).toBe(true);
  expect((r.segments as RibbonTimelineSegment[]).length > 0).toBeTruthy();
  for (const [i, seg] of (r.segments as RibbonTimelineSegment[]).entries()) {
    const src = (must(withTimeline.lane_timeline).segments ?? [])[i];
    expect(seg.thickness).toBe(src.public_lanes / src.lane_count);
    expect(seg.pinched).toBe(Number(src.reserved_lanes) > 0);
  }
  // the Oerlikon fixture contains BOTH a full (reserved=0) and a pinched (reserved>0) segment
  expect((r.segments as RibbonTimelineSegment[]).some((s: RibbonTimelineSegment) => s.pinched === true)).toBeTruthy();
  expect((r.segments as RibbonTimelineSegment[]).some((s: RibbonTimelineSegment) => s.pinched === false)).toBeTruthy();
  const full = must(
    (r.segments as RibbonTimelineSegment[]).find((s) => s.pinched === false),
  );
  expect(full.thickness).toBe(1); // public==lane_count when nothing reserved
});

test('an option WITHOUT lane_timeline → a "lane split not published" ribbon', () => {
  const { options } = load<{ options: RibbonOption[] }>('swim_day.json');
  const noTimeline = must(options.find((o: RibbonOption) => !o.lane_timeline));
  const r = optionRibbon(noTimeline);
  expect(r.variant).toBe('unpublished');
  expect(r.sheath).toBe(false);
  expect((r.label as string)).toBe('Lane split not published');
  expect((r.segments as RibbonTimelineSegment[]) === undefined).toBeTruthy();
});

test('publicFraction is 0 (not NaN) when a segment records no lanes', () => {
  const r = optionRibbon({
    facility: 'x', basin: 'y', access: 'PublicSwim', start: '08:00', end: '09:00',
    lane_timeline: { segments: [{ start: '08:00', end: '09:00', lane_count: 0, public_lanes: 0, reserved_lanes: 0, partial: true }] },
  });
  expect((r.segments as RibbonTimelineSegment[])[0].thickness).toBe(0);
});

test('ribbonsFor draws statuses first (background), then options (foreground)', () => {
  const day = load<{ options: RibbonOption[]; statuses: RibbonStatus[] }>('swim_day.json');
  const oerlikon = {
    options: day.options.filter((o: RibbonOption) => o.facility === 'Hallenbad Oerlikon'),
    statuses: day.statuses.filter((s: RibbonStatus) => s.facility === 'Hallenbad Oerlikon'),
  };
  const ribbons = ribbonsFor(oerlikon);
  expect(ribbons.length).toBe(oerlikon.options.length + oerlikon.statuses.length);
  const firstOption = ribbons.findIndex((r) => r.kind === 'option');
  const lastStatus = ribbons.map((r) => r.kind).lastIndexOf('status');
  if (firstOption !== -1 && lastStatus !== -1) expect(lastStatus < firstOption).toBeTruthy();
});
