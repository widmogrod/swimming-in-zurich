// parity.test.ts — the completeness gates the plan lists for the catalogues.
//
// Key parity and plural-category completeness are already COMPILE errors (`CatalogFor<L>`
// in i18n.ts). What the compiler cannot see is whether a translation silently DROPPED an
// interpolation placeholder — `{count}` missing from a Polish plural still type-checks
// perfectly and still reads as broken output. That is what this file catches.

import { describe, expect, test } from "vitest";
import { LOCALES, PLURAL_CATEGORIES, type Locale } from "../plurals.js";
import { de } from "./de.js";
import { en } from "./en.js";
import { fr } from "./fr.js";
import { it } from "./it.js";
import { pl } from "./pl.js";

type Entry = string | Record<string, string>;
const CATALOGS: Record<Locale, Record<string, Entry>> = { en, de, fr, it, pl };

const placeholders = (s: string): string[] =>
  [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

const forms = (entry: Entry): string[] =>
  typeof entry === "string" ? [entry] : Object.values(entry);

describe("every locale is registered and complete", () => {
  test("a catalogue exists for every supported locale", () => {
    expect(Object.keys(CATALOGS).sort()).toEqual([...LOCALES].sort());
  });

  test.each(LOCALES)("%s has exactly the English key set", (locale) => {
    // Also a compile error, but asserted so a failure names the locale plainly.
    expect(Object.keys(CATALOGS[locale]).sort()).toEqual(
      Object.keys(en).sort(),
    );
  });
});

describe("the access legend is fully translated in every locale", () => {
  // The parity gates above only compare the catalogues WITH EACH OTHER: five catalogues that
  // all lack a key are perfectly "in parity" and perfectly broken. So the access vocabulary
  // is asserted BY NAME — a new domain access kind (school-access-vocabulary S1 added three)
  // must reach the legend in all five languages, not just English.
  const ACCESS_KEYS = [
    "access.public",
    "access.lane",
    "access.family",
    "access.women",
    "access.seniors",
    "access.adults",
    "access.school",
    "access.club",
    "access.girls",
    "access.genderDiverse",
    "access.accompanied",
  ];

  test.each(LOCALES)("%s carries every access.* label, non-empty", (locale) => {
    for (const key of ACCESS_KEYS) {
      const entry = CATALOGS[locale][key];
      expect(entry, `${locale} is missing ${key}`).toBeDefined();
      expect(typeof entry, `${locale}/${key} must be a plain string`).toBe(
        "string",
      );
      expect(
        (entry as string).trim().length,
        `${locale}/${key} is blank`,
      ).toBeGreaterThan(0);
    }
  });

  test.each(LOCALES)(
    "%s does not reuse one word for two distinct access kinds",
    (locale) => {
      // A copy-paste placeholder ("Girls only" left as "Women only") is invisible to key
      // parity and reads as a factual error about who the session is for.
      const labels = ACCESS_KEYS.map((k) => CATALOGS[locale][k] as string);
      expect(new Set(labels).size, `${locale}: duplicate access labels`).toBe(
        ACCESS_KEYS.length,
      );
    },
  );
});

describe("every closure code the resolver can emit is translated", () => {
  // Same reasoning as the access legend: parity alone is green when all five catalogues lack
  // a key. `closure.out_of_season` is a NEW resolver-generated code (seasonal-hours S2) and
  // must be worded SEASON-NEUTRALLY — it is derived from a pool's own annual window and does
  // not know which season it is outside, so a lido is out of season in winter.
  const CLOSURE_KEYS = [
    "closure.seasonal_break",
    "closure.seasonal_break_maintenance",
    "closure.maintenance",
    "closure.operational_break",
    "closure.christmas_eve",
    "closure.public_holiday",
    "closure.no_sessions",
    "closure.out_of_season",
    "closure.special",
  ];

  test.each(LOCALES)(
    "%s carries every closure.* label, non-empty",
    (locale) => {
      for (const key of CLOSURE_KEYS) {
        const entry = CATALOGS[locale][key];
        expect(entry, `${locale} is missing ${key}`).toBeDefined();
        expect(typeof entry, `${locale}/${key} must be a plain string`).toBe(
          "string",
        );
        expect(
          (entry as string).trim().length,
          `${locale}/${key} is blank`,
        ).toBeGreaterThan(0);
      }
    },
  );

  test.each(LOCALES)(
    "%s does not word out_of_season as the summer break",
    (locale) => {
      // The bug this code exists to fix: reusing `seasonal_break` rendered a lido's January
      // closure as "Summer break". Sharing the string would reintroduce it verbatim.
      expect(CATALOGS[locale]["closure.out_of_season"]).not.toBe(
        CATALOGS[locale]["closure.seasonal_break"],
      );
    },
  );

  test.each(LOCALES)("%s names no season in out_of_season", (locale) => {
    // "winter" in any of the five languages would be a guess the code cannot support.
    const label = (
      CATALOGS[locale]["closure.out_of_season"] as string
    ).toLocaleLowerCase();
    for (const season of [
      "winter",
      "hiver",
      "invern",
      "zim",
      "summer",
      "sommer",
      "estiv",
      "été",
      "letni",
    ]) {
      expect(label, `${locale}: out_of_season names a season`).not.toContain(
        season,
      );
    }
  });
});

describe("plural entries carry exactly the categories their locale uses", () => {
  test.each(LOCALES)("%s", (locale) => {
    const expected = [...PLURAL_CATEGORIES[locale]].sort();
    for (const [key, entry] of Object.entries(CATALOGS[locale])) {
      if (typeof entry === "string") continue;
      expect(Object.keys(entry).sort(), `${locale}/${key}`).toEqual(expected);
    }
  });
});

describe("no translation drops or invents a placeholder", () => {
  // The highest-value gate here: `{count}` missing from a `pl` plural type-checks fine
  // and renders "basenów" with no number. Only this catches it.
  test.each(LOCALES)("%s matches en's placeholders for every key", (locale) => {
    for (const [key, source] of Object.entries(en) as [string, Entry][]) {
      const want = placeholders(forms(source).join(" "));
      for (const form of forms(CATALOGS[locale][key])) {
        const got = placeholders(form);
        for (const p of got) {
          expect(
            want,
            `${locale}/${key}: unknown placeholder {${p}}`,
          ).toContain(p);
        }
      }
      // Every placeholder the English uses must survive in EVERY plural form.
      if (want.length) {
        for (const form of forms(CATALOGS[locale][key])) {
          for (const p of new Set(want)) {
            expect(form, `${locale}/${key} dropped {${p}}`).toContain(`{${p}}`);
          }
        }
      }
    }
  });
});

test("Polish never uses `other` as a plural fallback", () => {
  // `other` is the FRACTION form (1,5 basenu — genitive singular). Copying the plural
  // there produces "1,5 baseny", which is wrong. If `other` ever equals `many` or `few`
  // verbatim, that is the tell.
  for (const [key, entry] of Object.entries(pl)) {
    if (typeof entry === "string") continue;
    const e = entry as Record<string, string>;
    // openDays is genuinely invariant across forms in Polish ("z 7 dni"), so exempt it.
    if (key === "insight.pool.openDays") continue;
    expect(e.other, `${key}: other must not reuse the 'many' form`).not.toBe(
      e.many,
    );
    expect(e.other, `${key}: other must not reuse the 'few' form`).not.toBe(
      e.few,
    );
  }
});
