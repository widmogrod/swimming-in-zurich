import { expect, test } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import type {
  Ribbon,
  RibbonOption,
  RibbonStackLane,
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
  expect(accessFamily('GirlsOnly')).toBe('girls');
  expect(accessFamily('GenderDiverse')).toBe('diverse');
  expect(accessFamily('AccompaniedChildren')).toBe('accompanied');
  expect(accessFamily('SomethingNew')).toBe('other');
});

test('the school-pool kinds get their OWN family, never the public-swim fallback', () => {
  // `accessFamily` falling to 'other' is not neutral: ribbonrender paints 'other' with
  // `fam-public`, so a restricted session would be drawn in the open-to-all colour.
  for (const a of ['GirlsOnly', 'GenderDiverse', 'AccompaniedChildren']) {
    expect(accessFamily(a)).not.toBe('other');
    expect(accessFamily(a)).not.toBe('public');
  }
});

test('the synthetic fixture exercises every colour family', () => {
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

test('the new "open_unscheduled" status degrades to the dotted ghost, never to closed', () => {
  // sharedsource-fanout S1 pins the wire value before S3 makes it live: a UI that does not
  // yet know the status must fall back to the ghost/unknown ribbon — rendering it closed
  // would break the "unknown != closed" invariant for a pool that is in fact open.
  const r = statusRibbon({ status: 'open_unscheduled', detail: '' });
  expect(r.variant).toBe('ghost');
  expect(r.style).toBe('dotted');
  expect(r.variant).not.toBe('closed');
  // The status value rides along so a future UI can render its SPECIFIC label.
  expect(r.status).toBe('open_unscheduled');
});

test('an option WITH lane_timeline → a filled ribbon; thickness = public/lane_count, pinched where reserved>0, sheath present', () => {
  // Read from `access_families.json`, not `swim_day.json`: S4 gave the Oerlikon basin the
  // per-lane day view it really has, so its options now paint the STACK. This fixture is
  // the remaining saved answer whose options carry counts and no plan — i.e. the pools
  // (most of them) whose lane split is published only as totals.
  const { options } = load<{ options: RibbonOption[] }>('access_families.json');
  // the PublicSwim arc carries BOTH a full (reserved=0) and a pinched segment
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
  // the fixture contains BOTH a full (reserved=0) and a pinched (reserved>0) segment
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

// --- S4: the lane stack (variant C) -------------------------------------------------

const DAY = load<{ options: RibbonOption[] }>('swim_day.json');
/** The Oerlikon basin, whose Belegungsplan reaches `/swim` as a per-lane day view. */
const stackOption = (start: string): RibbonOption =>
  must(DAY.options.find((o) => o.lane_day_view && o.start === start));

const stripsOf = (r: Ribbon): RibbonStackLane[] => r.strips as RibbonStackLane[];

test('AC1 · the three variants are decided by what the option carries, on saved fixtures', () => {
  // A day view → the STACK. Counts only → the filled ribbon. Neither → "not published".
  // These are three states, never merged (I5): most pools will never publish a plan.
  const withPlan = stackOption('08:00');
  const countsOnly = must(
    load<{ options: RibbonOption[] }>('access_families.json').options.find(
      (o) => o.lane_timeline && !o.lane_day_view,
    ),
  );
  const nothing = must(DAY.options.find((o) => !o.lane_timeline && !o.lane_day_view));
  expect(optionRibbon(withPlan).variant).toBe('lanestack');
  expect(optionRibbon(countsOnly).variant).toBe('lanes');
  expect(optionRibbon(nothing).variant).toBe('unpublished');
});

test('the stack has ONE sub-row per lane, and wins over the counts the same option carries', () => {
  const option = stackOption('08:00');
  // The real option carries BOTH shapes; the day view is strictly richer, so it decides.
  expect(option.lane_timeline).toBeTruthy();
  const r = optionRibbon(option);
  expect(r.lane_count).toBe(8);
  expect(stripsOf(r).length).toBe(8);
  expect(stripsOf(r).map((s) => s.lane)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  expect(r.sheath).toBe(true);
});

test('every block is CLIPPED to the option\'s own hours (the day view spans the weekday)', () => {
  // Oerlikon's two options share one basin and therefore one day view. Unclipped, the
  // 06:00–08:00 ribbon would paint holds running to 21:30 — hours its session never covers.
  const early = optionRibbon(stackOption('06:00'));
  for (const lane of stripsOf(early)) {
    for (const seg of lane.segments) {
      expect(seg.start >= '06:00').toBe(true);
      expect(seg.end <= '08:00').toBe(true);
    }
  }
  // Lane 8 is held 06:00–09:30 in the plan; the early ribbon must end it at 08:00.
  const lane8 = must(stripsOf(early).find((l) => l.lane === 8));
  expect(lane8.segments[0]).toEqual({
    start: '06:00',
    end: '08:00',
    public: false,
    owner: 'SC Oerlikon',
  });
  // …and the late ribbon must NOT start it before 08:00.
  const late8 = must(stripsOf(optionRibbon(stackOption('08:00'))).find((l) => l.lane === 8));
  expect(late8.segments[0].start).toBe('08:00');
});

test('a lane nobody holds keeps its (empty) sub-row — dropping it would renumber the rest', () => {
  const r = optionRibbon({
    facility: 'x', basin: 'y', access: 'PublicSwim', start: '09:00', end: '10:00',
    lane_day_view: {
      lane_count: 3,
      strips: [
        { lane: 1, segments: [{ start: '09:00', end: '10:00', access: 'PublicSwim' }] },
        // lane 2 is held only OUTSIDE this session, lane 3 is absent from the payload
        { lane: 2, segments: [{ start: '06:00', end: '08:00', access: 'ClubReserved', owner: 'X' }] },
      ],
    },
  });
  expect(stripsOf(r).map((l) => l.lane)).toEqual([1, 2, 3]);
  expect(stripsOf(r)[1].segments).toEqual([]);
  expect(stripsOf(r)[2].segments).toEqual([]);
});

test('public is read from the ACCESS class, never inferred from a missing owner', () => {
  // Availability is never derived by complement (the same rule `publicAt` enforces): a
  // reserved lane whose holder is unnamed is still reserved, not free water.
  const r = optionRibbon({
    facility: 'x', basin: 'y', access: 'PublicSwim', start: '09:00', end: '10:00',
    lane_day_view: {
      lane_count: 2,
      strips: [
        { lane: 1, segments: [{ start: '09:00', end: '10:00', access: 'ClubReserved', owner: null }] },
        { lane: 2, segments: [{ start: '09:00', end: '10:00', access: 'PublicSwim', owner: '' }] },
      ],
    },
  });
  expect(stripsOf(r)[0].segments[0]).toEqual({ start: '09:00', end: '10:00', public: false, owner: null });
  expect(stripsOf(r)[1].segments[0]).toEqual({ start: '09:00', end: '10:00', public: true, owner: null });
});

test('AC6 · the best-public window rides on the ribbon, and is ABSENT when the option has none', () => {
  // It comes from `option.lane_best_public` (S2 bounded it to the session) — NOT from the
  // day view, which does not carry one.
  const r = optionRibbon(stackOption('08:00'));
  expect(r.best_public).toEqual({ start: '11:00', end: '13:00', public_lanes: 8 });
  const none = optionRibbon({
    ...stackOption('08:00'),
    lane_best_public: null,
  });
  // ABSENT, not a zero-width window: `{start:'', end:''}` would be a claim about 00:00.
  expect('best_public' in none).toBe(false);
});

test('an option with no HOURS cannot be stacked — an unclippable stack reads as "nothing free"', () => {
  const r = optionRibbon({
    facility: 'x', basin: 'y', access: 'PublicSwim',
    lane_day_view: {
      lane_count: 2,
      strips: [{ lane: 1, segments: [{ start: '09:00', end: '10:00', access: 'PublicSwim' }] }],
    },
  });
  expect(r.variant).toBe('unpublished');
});

test('a day view that says nothing falls back — never an empty stack (I5)', () => {
  // `lane_count: 0` is not "a pool with no free lanes"; it is a pool we know nothing
  // about. It must degrade to the state that says so.
  const empty = { weekday: 2, lane_count: 0, strips: [] };
  const base = { facility: 'x', basin: 'y', access: 'PublicSwim', start: '09:00', end: '10:00' };
  expect(optionRibbon({ ...base, lane_day_view: empty }).variant).toBe('unpublished');
  expect(
    optionRibbon({
      ...base,
      lane_day_view: empty,
      lane_timeline: { segments: [{ start: '09:00', end: '10:00', lane_count: 4, public_lanes: 2, reserved_lanes: 2 }] },
    }).variant,
  ).toBe('lanes');
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

// --- The cross-client golden (plan S3b acceptance 1) -------------------------------------
//
// The iOS app paints the SAME ribbon encoding from the same facts, and nothing about the two
// implementations makes either notice when the other changes: the TypeScript module gains a
// variant, the Swift port silently keeps drawing four, and the two clients disagree about what
// a pool's day looks like. So this suite emits a golden artifact — inputs and the ribbon each
// produces — and `apps/ios/Tests/SwimZHKitTests/RibbonModelTests.swift` replays it.
//
// TWO CANONICALISATIONS, both deliberate:
//  * keys are sorted recursively, so the file diffs by CONTENT rather than by whatever order a
//    spread happened to produce;
//  * `label` is DROPPED and `label_key` kept. `label` is `t(...)` output — locale-dependent —
//    so a golden carrying it would pin this suite's active locale into a cross-client contract
//    and go red the day a translation is improved. The key is what both clients agree on.

const GOLDEN = join(HERE, 'fixtures', 'ribbon_golden.json');

/** The sources the golden is drawn from: between them they exercise every variant. */
const GOLDEN_SOURCES = ['swim_day.json', 'access_families.json'] as const;

/**
 * One option the committed fixtures cannot supply: thickness that is NOT exactly representable
 * in binary floating point, and `partial: true`.
 *
 * Every thickness in the fixture-drawn half of the golden is 0.5, 0.75 or 1 — all exact — so a
 * port that rounded to two decimals, or formatted through a float, would reproduce the golden
 * byte for byte and the cross-client contract would prove nothing about the arithmetic. 5/6 is
 * 0.8333333333333334 and 1/3 is 0.3333333333333333: both are long enough that any rounding
 * shows up immediately. `partial` was also `false` on every committed segment, so the flag that
 * decides whether a swimmer is told the count is a floor was pinned at one value only.
 *
 * Held inline rather than as a new file under `apps/web/tests/fixtures/`: it is a property of
 * this contract, not a shape any other suite reads.
 */
const GOLDEN_INLINE: { source: string; options: RibbonOption[] } = {
  source: 'inline:awkward_thickness',
  options: [
    {
      facility_id: 'inline',
      facility: 'Awkward Fractions',
      basin: 'Main',
      access: 'PublicSwim',
      start: '06:00',
      end: '09:00',
      lanes: 6,
      lane_timeline: {
        segments: [
          // 5/6 — the case the exact-thirds and halves above cannot make.
          {
            start: '06:00',
            end: '07:00',
            lane_count: 6,
            public_lanes: 5,
            reserved_lanes: 1,
            partial: true,
          },
          // 1/3, and `partial` back to false so both values ride in one entry.
          {
            start: '07:00',
            end: '09:00',
            lane_count: 6,
            public_lanes: 2,
            reserved_lanes: 4,
            partial: false,
          },
        ],
      },
    } as RibbonOption,
  ],
};

function sortedDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedDeep);
  if (value && typeof value === 'object') {
    const source = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) {
      if (source[key] === undefined) continue;
      out[key] = sortedDeep(source[key]);
    }
    return out;
  }
  return value;
}

function canonicalRibbon(ribbon: Ribbon): unknown {
  const copy: Record<string, unknown> = { ...ribbon };
  delete copy.label;
  return sortedDeep(copy);
}

interface GoldenEntry {
  source: string;
  kind: 'option' | 'status';
  index: number;
  input: unknown;
  ribbon: unknown;
}

function goldenEntries(): GoldenEntry[] {
  const entries: GoldenEntry[] = [];
  for (const source of GOLDEN_SOURCES) {
    const day = load<{ options?: RibbonOption[]; statuses?: RibbonStatus[] }>(source);
    (day.options ?? []).forEach((option, index) => {
      entries.push({
        source,
        kind: 'option',
        index,
        input: sortedDeep(option),
        ribbon: canonicalRibbon(optionRibbon(option)),
      });
    });
    (day.statuses ?? []).forEach((status, index) => {
      entries.push({
        source,
        kind: 'status',
        index,
        input: sortedDeep(status),
        ribbon: canonicalRibbon(statusRibbon(status)),
      });
    });
  }
  GOLDEN_INLINE.options.forEach((option, index) => {
    entries.push({
      source: GOLDEN_INLINE.source,
      kind: 'option',
      index,
      input: sortedDeep(option),
      ribbon: canonicalRibbon(optionRibbon(option)),
    });
  });
  return entries;
}

test('the committed ribbon golden still equals what this module produces', () => {
  const entries = goldenEntries();
  const text =
    JSON.stringify(
      {
        _note:
          'GENERATED by blocks/ribbonmodel.test.ts — do NOT hand-edit. Replayed by ' +
          'apps/ios/Tests/SwimZHKitTests/RibbonModelTests.swift so the two clients cannot ' +
          'disagree about the ribbon encoding. `label` is dropped (locale-dependent output); ' +
          '`label_key` is kept. Regenerate with REGENERATE_RIBBON_GOLDEN=1 npm test.',
        entries,
      },
      null,
      2,
    ) + '\n';
  if (process.env.REGENERATE_RIBBON_GOLDEN) {
    mkdirSync(join(HERE, 'fixtures'), { recursive: true });
    writeFileSync(GOLDEN, text, 'utf-8');
  }
  expect(readFileSync(GOLDEN, 'utf-8')).toBe(text);
});

test('the golden exercises EVERY variant — otherwise the Swift port is unpinned', () => {
  // A golden of nothing but `unpublished` ribbons would pass forever while the stack, the
  // lane ribbon and the two terminal states drifted apart on the phone.
  const variants = new Set(
    goldenEntries().map((entry) => (entry.ribbon as { variant?: string }).variant),
  );
  expect(variants).toEqual(new Set(['lanestack', 'lanes', 'unpublished', 'closed', 'ghost']));
});

test('the golden pins thickness that is NOT exactly representable, and both partial values', () => {
  // Without this the golden's only thicknesses were 0.5, 0.75 and 1 — all exact — so a port
  // that rounded to two decimals would reproduce it byte for byte and the cross-client contract
  // would say nothing about the arithmetic it exists to pin.
  const segments = goldenEntries().flatMap(
    (entry) => (entry.ribbon as { segments?: RibbonTimelineSegment[] }).segments ?? [],
  );
  const thicknesses = segments.map((s) => (s as unknown as { thickness: number }).thickness);
  expect(thicknesses).toContain(5 / 6);
  expect(thicknesses).toContain(1 / 3);
  // Long enough that any rounding to two, or even ten, decimals shows.
  for (const value of [5 / 6, 1 / 3]) {
    expect(String(value).length).toBeGreaterThan(12);
  }
  const partials = new Set(segments.map((s) => (s as unknown as { partial: boolean }).partial));
  expect(partials).toEqual(new Set([true, false]));
});
