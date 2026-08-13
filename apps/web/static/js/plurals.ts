// plurals.ts — the CLDR plural categories each supported locale actually uses.
//
// This table is the TYPE SOURCE for plural messages. `Plural<'pl'>` is a record keyed by
// exactly `one | few | many | other`, so a Polish catalog entry missing `many` is a `tsc`
// error rather than a runtime fallback that silently reads as broken grammar to a native
// speaker. That is the whole reason the i18n runtime is hand-rolled instead of vendored:
// we own the catalog types, so completeness is a compile error, not a test we must
// remember to write (see docs/plan/2026-07-25-i18n-plan.md, "Polish cannot be broken").
//
// The table is hand-written, so `plurals.test.ts` asserts it equals the platform's own
// `Intl.PluralRules(...).resolvedOptions().pluralCategories`. It therefore cannot drift
// from CLDR and quietly lie to the type system (`fr`/`it` gained `many` in CLDR 42 —
// exactly the kind of change that test catches).

export const LOCALES = ["en", "de", "fr", "it", "pl"] as const;

export type Locale = (typeof LOCALES)[number];

/** `en` is BOTH the source locale and the fallback: a missing message degrades to
 * English, never to a blank or a raw key. */
export const DEFAULT_LOCALE: Locale = "en";

export const PLURAL_CATEGORIES = {
  en: ["one", "other"],
  de: ["one", "other"],
  fr: ["one", "many", "other"],
  it: ["one", "many", "other"],
  pl: ["one", "few", "many", "other"],
} as const satisfies Record<Locale, readonly Intl.LDMLPluralRule[]>;

/** The categories `L` uses — `'one' | 'few' | 'many' | 'other'` for `pl`. */
export type PluralCategory<L extends Locale> =
  (typeof PLURAL_CATEGORIES)[L][number];

/** A plural message: exactly one string per category THIS locale uses. */
export type Plural<L extends Locale> = Record<PluralCategory<L>, string>;

export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string" && (LOCALES as readonly string[]).includes(value)
  );
}

// `Intl.PluralRules` construction is not free and the same few locales recur on every
// render, so the rules are memoised per locale.
const RULES = new Map<Locale, Intl.PluralRules>();

function rulesFor(locale: Locale): Intl.PluralRules {
  const cached = RULES.get(locale);
  if (cached) return cached;
  const made = new Intl.PluralRules(locale);
  RULES.set(locale, made);
  return made;
}

/**
 * The CLDR category for `n` in `locale` — `pluralCategory('pl', 22)` → `'few'`.
 *
 * Delegates to the platform rather than re-deriving the rules: every hand-rolled
 * `n >= 5 ? 'many'` gets 22 wrong, and every `n === 0 ? 'other'` gets Polish zero wrong.
 */
export function pluralCategory<L extends Locale>(
  locale: L,
  n: number,
): PluralCategory<L> {
  return rulesFor(locale).select(n) as PluralCategory<L>;
}
