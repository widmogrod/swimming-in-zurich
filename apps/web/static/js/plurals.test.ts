import { describe, expect, test } from "vitest";
import {
  isLocale,
  LOCALES,
  PLURAL_CATEGORIES,
  pluralCategory,
} from "./plurals.js";

describe("PLURAL_CATEGORIES cannot drift from CLDR", () => {
  // The table is hand-written and used as a TYPE source, so it must equal what the
  // platform actually implements. If a future CLDR revision changes a category set (fr/it
  // gained `many` in CLDR 42), this fails rather than the table silently lying to tsc.
  test.each(LOCALES)("%s matches Intl.PluralRules", (locale) => {
    expect([...PLURAL_CATEGORIES[locale]]).toEqual(
      new Intl.PluralRules(locale).resolvedOptions().pluralCategories,
    );
  });
});

describe("Polish plural categories — the traps", () => {
  // Polish is the reason this project does not hand-roll plural rules. Each row here is a
  // case that a plausible hand-written rule gets WRONG; they are pinned so that any future
  // "optimisation" of pluralCategory() fails loudly.
  test.each([
    // n, category, why this row exists
    [0, "many", "zero takes genitive plural — NOT other"],
    [1, "one", ""],
    [2, "few", ""],
    [3, "few", ""],
    [4, "few", ""],
    [5, "many", ""],
    [11, "many", "11-14 are many despite ending in 1-4"],
    [12, "many", ""],
    [14, "many", ""],
    [
      21,
      "many",
      "21 is many, but 22 is few — the ones digit alone decides nothing",
    ],
    [22, "few", "breaks every `n >= 5 ? many` rule"],
    [23, "few", ""],
    [25, "many", ""],
    [101, "many", ""],
    [102, "few", ""],
    [
      1.5,
      "other",
      "fractions take genitive singular — `other` is NOT a plural fallback",
    ],
    [2.5, "other", ""],
  ])("pl: %d → %s", (n, expected) => {
    expect(pluralCategory("pl", n as number)).toBe(expected);
  });
});

test("English collapses to one/other", () => {
  expect(pluralCategory("en", 1)).toBe("one");
  expect(pluralCategory("en", 0)).toBe("other");
  expect(pluralCategory("en", 22)).toBe("other");
});

test("isLocale accepts supported tags and rejects everything else", () => {
  expect(isLocale("pl")).toBe(true);
  expect(isLocale("en")).toBe(true);
  expect(isLocale("es")).toBe(false);
  expect(isLocale("pl-PL")).toBe(false); // base tags only; callers split first
  expect(isLocale(null)).toBe(false);
  expect(isLocale(42)).toBe(false);
});
