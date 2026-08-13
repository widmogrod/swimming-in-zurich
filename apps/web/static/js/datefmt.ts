// datefmt.ts — all date/number/unit rendering, via `Intl`. The single home for the
// formatting that was previously hand-rolled English in five places.
//
// What this replaces, and why each mattered:
//   - two independent weekday tables (`api.js` WEEKDAY_LABELS, `datestepper.js` DAYS)
//   - a MONTHS table: Polish takes a GENITIVE month (`20 lipca`, never `20 lipiec`) and
//     lowercases month/weekday names, which no lookup table can express
//   - `board.js`'s `formatLabel(...).split(' ')`, which assumed a 3-token date and broke
//     silently on any locale that formats otherwise — hence `dayParts()` below returns
//     the parts, so nothing ever re-parses a formatted string
//   - `.toFixed(1) + ' km'` and `${t} °C`, which hardcode the `.` decimal separator
//     (de/fr/it/pl all use `,`) and the English unit form
//   - three copies of `mondayOf()`
//
// TIMEZONE: every formatter is pinned to `timeZone: 'UTC'` and every ISO date is parsed
// as UTC midnight. These are date-only values, not moments; without the pin a viewer in a
// negative-offset zone would see the previous day. `datestepper_tz.test.js` guards this.

import { DEFAULT_LOCALE, type Locale } from "./plurals.js";

// The BCP-47 tag each UI locale FORMATS with.
//
// `en` maps to `en-GB`, not bare `en`: bare `en` resolves to US conventions, which put
// the month first ("Thu, Jul 23") and pick a 12-hour clock. This app is about Zürich —
// day-first and 24-hour are what the previous hand-rolled formatter produced and what
// its audience reads. de/fr/it take their Swiss regional forms for the same reason.
// The message catalogue is still keyed by the plain locale; only formatting differs.
const FORMAT_LOCALE: Record<Locale, string> = {
  en: "en-GB",
  de: "de-CH",
  fr: "fr-CH",
  it: "it-CH",
  pl: "pl",
};

function tag(locale: Locale): string {
  return FORMAT_LOCALE[locale];
}

// ---- pure ISO date arithmetic (was duplicated in api.js, toolbar.js, urlstate.ts) ----

/** Parse an ISO date as UTC midnight, so arithmetic never drifts by a day. */
export function parseUtc(iso: string): Date {
  const [y, m, d] = String(iso).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** `shiftIso('2026-07-23', 2)` → `'2026-07-25'`. */
export function shiftIso(iso: string, days: number): string {
  const d = parseUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

/** The ISO Monday (Mon=0) of a date's week. */
export function mondayOf(iso: string): string {
  const d = parseUtc(iso);
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  d.setUTCDate(d.getUTCDate() - dow);
  return isoDate(d);
}

/** The 7 ISO dates Mon…Sun of `iso`'s week. */
export function weekDates(iso: string): string[] {
  const monday = mondayOf(iso);
  return Array.from({ length: 7 }, (_, i) => shiftIso(monday, i));
}

// ---- Intl formatters (memoised: the same few locales recur on every render) ----------

const CACHE = new Map<string, Intl.DateTimeFormat>();

function dtf(
  locale: Locale,
  opts: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  // eslint-disable-next-line i18next/no-literal-string -- a memoisation cache key, not copy
  const key = `${locale}|${JSON.stringify(opts)}`;
  const cached = CACHE.get(key);
  if (cached) return cached;
  const made = new Intl.DateTimeFormat(tag(locale), {
    ...opts,
    timeZone: "UTC",
  });
  CACHE.set(key, made);
  return made;
}

export interface DayParts {
  weekday: string;
  day: string;
  month: string;
}

/**
 * The named parts of a formatted day — `{ weekday: 'Thu', day: '23', month: 'Jul' }`.
 *
 * Callers that need to interleave their own separators (the board's `"Mon · 20 Jul"`)
 * compose from these. Nothing splits a formatted string on spaces: Polish and German
 * do not tokenise like English, which is exactly how the old `board.js` broke.
 */
export function dayParts(
  iso: string,
  locale: Locale = DEFAULT_LOCALE,
): DayParts {
  const parts = dtf(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).formatToParts(parseUtc(iso));
  const find = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? "";
  return { weekday: find("weekday"), day: find("day"), month: find("month") };
}

/** A whole short day label — `'Thu, 23 Jul'` in `en`, `'czw, 23 lip'` in `pl`. */
export function formatDay(
  iso: string,
  locale: Locale = DEFAULT_LOCALE,
): string {
  return dtf(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(parseUtc(iso));
}

/** A date with no weekday — for "last checked" stamps, where the weekday is noise. */
export function formatDate(
  iso: string,
  locale: Locale = DEFAULT_LOCALE,
): string {
  return dtf(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(parseUtc(iso));
}

// ---- numbers and units ---------------------------------------------------------------

const NUM_CACHE = new Map<string, Intl.NumberFormat>();

function nf(locale: Locale, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  // eslint-disable-next-line i18next/no-literal-string -- a memoisation cache key, not copy
  const key = `${locale}|${JSON.stringify(opts)}`;
  const cached = NUM_CACHE.get(key);
  if (cached) return cached;
  const made = new Intl.NumberFormat(tag(locale), opts);
  NUM_CACHE.set(key, made);
  return made;
}

/**
 * `'2.5 km'` in `en`, `'2,5 km'` in de/fr/it/pl.
 *
 * Unit formatting deliberately bypasses the message catalog: CLDR supplies the correct
 * form per locale, including fractional cases, so there is no plural entry to get wrong.
 * Only genuine domain nouns (pool, lane, day) need catalog plurals.
 */
export function formatKm(km: number, locale: Locale = DEFAULT_LOCALE): string {
  return nf(locale, {
    style: "unit",
    unit: "kilometer",
    unitDisplay: "short",
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  }).format(km);
}

/** `'28 °C'`, with the locale's decimal separator and spacing. */
export function formatCelsius(
  c: number,
  locale: Locale = DEFAULT_LOCALE,
): string {
  return nf(locale, {
    style: "unit",
    unit: "celsius",
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(c);
}

/**
 * `8` → `'CHF 8.00'` (en-GB/de-CH) or `'8,00 CHF'` (pl) — the symbol POSITION and the
 * decimal separator both move with the locale, which is precisely why this cannot be a
 * catalogue string with the amount pasted in.
 */
export function formatChf(
  amount: number,
  locale: Locale = DEFAULT_LOCALE,
): string {
  return nf(locale, { style: "currency", currency: "CHF" }).format(amount);
}
