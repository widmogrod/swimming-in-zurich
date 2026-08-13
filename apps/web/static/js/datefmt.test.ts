import { expect, test } from "vitest";
import {
  dayParts,
  formatCelsius,
  formatDate,
  formatDay,
  formatHour,
  formatKm,
  HOUR_OPTS,
  isoDate,
  mondayOf,
  parseUtc,
  shiftIso,
  weekDates,
} from "./datefmt.js";
import { LOCALES } from "./plurals.js";

// ---- date arithmetic (behaviour preserved from the three deduplicated copies) --------

test("mondayOf snaps to the ISO Monday of the week", () => {
  expect(mondayOf("2026-07-23")).toBe("2026-07-20"); // a Thursday
  expect(mondayOf("2026-07-20")).toBe("2026-07-20"); // already Monday
  expect(mondayOf("2026-07-26")).toBe("2026-07-20"); // Sunday belongs to the week before
});

test("shiftIso crosses month and year boundaries", () => {
  expect(shiftIso("2026-07-31", 1)).toBe("2026-08-01");
  expect(shiftIso("2026-01-01", -1)).toBe("2025-12-31");
});

test("weekDates returns Mon…Sun", () => {
  expect(weekDates("2026-07-23")).toEqual([
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
    "2026-07-25",
    "2026-07-26",
  ]);
});

test("ISO dates round-trip through UTC midnight without drifting a day", () => {
  // The regression this guards: parsing as local time puts a viewer in a negative-offset
  // zone on the previous day. Date-only values are not moments.
  expect(isoDate(parseUtc("2026-07-23"))).toBe("2026-07-23");
});

// ---- Intl formatting -----------------------------------------------------------------

test("dayParts returns named parts so nothing re-parses a formatted string", () => {
  const parts = dayParts("2026-07-23", "en");
  expect(parts.weekday).toBe("Thu");
  expect(parts.day).toBe("23");
  expect(parts.month).toBe("Jul");
});

test("dayParts is correct for a locale that does not tokenise like English", () => {
  // Polish lowercases the weekday and abbreviates differently; the old
  // `formatLabel(...).split(' ')` in board.js could not survive this.
  const parts = dayParts("2026-07-23", "pl");
  expect(parts.weekday).not.toBe("");
  expect(parts.day).toBe("23");
  expect(parts.month).not.toBe("");
  expect(parts.weekday).toBe(parts.weekday.toLowerCase());
});

test("formatDay is locale-specific", () => {
  expect(formatDay("2026-07-23", "en")).toContain("23");
  expect(formatDay("2026-07-23", "de")).not.toBe(formatDay("2026-07-23", "en"));
});

test("a formatted day is stable across the host timezone", () => {
  // Pinned to UTC in the formatter, so this holds wherever CI runs.
  expect(dayParts("2026-07-23", "en").day).toBe("23");
  expect(dayParts("2026-01-01", "en").day).toBe("1");
});

test("formatDate omits the weekday and includes the year", () => {
  const out = formatDate("2026-07-23", "en");
  expect(out).toContain("2026");
  expect(out).not.toContain("Thu");
});

test("units use the locale decimal separator, not a hardcoded dot", () => {
  expect(formatKm(2.5, "en")).toBe("2.5 km");
  // fr-CH and pl use a comma — the bug in `${km.toFixed(1)} km`, which hardcoded a dot.
  expect(formatKm(2.5, "fr")).toContain("2,5");
  expect(formatKm(2.5, "pl")).toContain("2,5");
  // …but SWISS German and Italian use a DOT, unlike de-DE/it-IT. Pinned because it is
  // counter-intuitive and because it is why datefmt formats with de-CH/it-CH, not de/it.
  expect(formatKm(2.5, "de")).toContain("2.5");
  expect(formatKm(2.5, "it")).toContain("2.5");
});

test("km always shows one fraction digit, matching the previous toFixed(1)", () => {
  expect(formatKm(3, "en")).toBe("3.0 km");
});

test("celsius formats through Intl rather than string concatenation", () => {
  expect(formatCelsius(28, "en")).toContain("28");
  expect(formatCelsius(28, "en")).toContain("C");
});

// ---- the day tail's hour labels ------------------------------------------------------

test("formatHour returns the same HH:00 shape the Gantt axis renders, in every locale", () => {
  // Pinned as a LITERAL, in all five, because the collapsed card's strip and the expanded
  // card's `gantt.ts` axis label the same hours and must not read differently.
  for (const loc of LOCALES) {
    expect(formatHour(6, loc)).toBe("06:00");
  }
  expect(formatHour(21, "pl")).toBe("21:00");
});

test("HOUR_OPTS pins h23 — asserted against en-US, the only tag that can tell", () => {
  // en-US is NOT one of our locales, and that is exactly why it is here. DO NOT "tidy it
  // away" as irrelevant: all five `FORMAT_LOCALE` tags already DEFAULT to h23, so against
  // any of them this assertion holds whether or not `HOUR_OPTS` sets `hourCycle` — the
  // output string and `resolvedOptions().hourCycle` alike. en-US defaults to h12, so it
  // is the one tag where the option is observable: "06:00" with it, "06:00 AM" without.
  // Delete `hourCycle` from HOUR_OPTS and this test — and only this test — goes red.
  const us = new Intl.DateTimeFormat("en-US", {
    ...HOUR_OPTS,
    timeZone: "UTC",
  });
  expect(us.format(new Date(Date.UTC(1970, 0, 1, 6)))).toBe("06:00");
});
