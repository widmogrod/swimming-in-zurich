// i18n.ts — the message runtime: `t(key, params)`, plus the SINGLE locale-resolution seam.
//
// Hand-rolled rather than vendored, because the build is `tsc` alone (no bundler, raw
// `<script type=module>`), and because owning the catalog types is what makes plural
// completeness a compile error — see plurals.ts and the plan's "Polish cannot be broken".
//
// Correctness that would otherwise need a library comes from the platform:
// `Intl.PluralRules` for CLDR categories, `Intl.*Format` (in datefmt.ts) for dates,
// numbers and units. What is left is key lookup, plural selection and interpolation.

import { de } from "./locales/de.js";
import { en } from "./locales/en.js";
import { fr } from "./locales/fr.js";
import { it } from "./locales/it.js";
import { pl } from "./locales/pl.js";
import {
  DEFAULT_LOCALE,
  isLocale,
  pluralCategory,
  type Locale,
  type Plural,
  type PluralCategory,
} from "./plurals.js";

export type { Locale };

export type MessageKey = keyof typeof en;

/**
 * The shape every locale's catalog must have: the same keys as `en`, with each plural
 * entry re-keyed to the categories THAT locale uses.
 *
 * This one type carries all the parity guarantees the plan lists as separate gates —
 * a missing key, a bare string where English has a plural, and a `pl` plural missing
 * `many` are each a `tsc` error rather than a runtime fallback.
 */
export type CatalogFor<L extends Locale> = {
  [K in MessageKey]: (typeof en)[K] extends string ? string : Plural<L>;
};

// The source catalog must itself satisfy the shape it defines (guards against `en` being
// edited into something `CatalogFor` cannot express).
const _EN_CONFORMS: CatalogFor<"en"> = en;
void _EN_CONFORMS;

export type MessageParams = Record<string, string | number>;

// The RUNTIME view of a catalog. Strictness lives at authoring time — `locales/pl.ts`
// declares `satisfies CatalogFor<'pl'>` and is rejected if it omits `many` — so the
// registry only needs the shape `t()` actually walks. Typing the registry as
// `CatalogFor<Locale>` would distribute into a union demanding EVERY locale's categories
// of every catalog, which no single locale can satisfy.
//
// `Partial<Record<Intl.LDMLPluralRule, string>>` (rather than an index signature) is what
// lets a concrete `{ one, other }` object be stored without a cast.
type RuntimeEntry = string | Partial<Record<Intl.LDMLPluralRule, string>>;
type RuntimeCatalog = { readonly [K in MessageKey]: RuntimeEntry };

// Every locale's catalogue. Lookup still falls back to `en`, so a key absent from a
// partial catalogue degrades to English rather than to a raw key.
const CATALOGS: Partial<Record<Locale, RuntimeCatalog>> = {
  de,
  en,
  fr,
  it,
  pl,
};

/**
 * The locales a USER may be offered.
 *
 * `pl` is complete and type-checked but NOT here: it has not been reviewed by a native
 * speaker, and the plan makes that a release gate ("Polish cannot be broken" §7). Gating
 * the switcher on this list rather than on catalogue presence is deliberate — it makes
 * "translated" and "shippable" different states, so an unreviewed locale cannot be
 * reached by clicking, only by setting the cookie by hand.
 *
 * Move `pl` here when a native speaker has signed off.
 */
export const OFFERED_LOCALES: readonly Locale[] = ["en", "de", "fr", "it"];

export const LOCALE_COOKIE = "swimzh_locale";

// Resolved AT MODULE SCOPE, deliberately.
//
// Many blocks build their label tables at module scope (`const FAMILIES = [{ label:
// t('access.public') }, …]`), which freezes those strings when the module is imported.
// ES modules evaluate dependencies BEFORE importers, and every one of those modules
// imports this file — so setting the locale here means it is already correct by the time
// any of them evaluates. Setting it in `app.ts`'s main() would be far too late: the
// tables would already hold English.
let active: Locale = resolveLocaleFromBrowser();

/**
 * The locale currently in effect. Read this rather than the cookie: `resolveLocale` is
 * the only place locale is derived, so adding `/{locale}/` URL prefixes later is a change
 * here and nowhere else.
 */
export function locale(): Locale {
  return active;
}

export function setLocale(next: Locale): void {
  active = next;
}

function cookieLocale(source: string): string | null {
  for (const part of source.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === LOCALE_COOKIE) return rest.join("=");
  }
  return null;
}

/**
 * Resolve the locale from (in order) the cookie, localStorage, then the browser's
 * languages, falling back to `en`.
 *
 * THE COOKIE IS CANONICAL, not localStorage: the shell is server-rendered and must emit
 * `<html lang>`, and the server cannot read localStorage. localStorage is a client-side
 * mirror only, so it is consulted second and never overrides the cookie.
 *
 * Env is injected so this is testable headless and so no other module reads `document`
 * or `navigator` for locale purposes.
 */
export function resolveLocale(
  env: {
    cookie?: string;
    stored?: string | null;
    languages?: readonly string[];
  } = {},
): Locale {
  const fromCookie = env.cookie ? cookieLocale(env.cookie) : null;
  if (isLocale(fromCookie)) return fromCookie;
  if (isLocale(env.stored)) return env.stored;
  for (const tag of env.languages ?? []) {
    const base = tag.split("-")[0];
    if (isLocale(base)) return base;
  }
  return DEFAULT_LOCALE;
}

/** Read the ambient browser env. Split from `resolveLocale` so that stays pure. */
export function resolveLocaleFromBrowser(): Locale {
  const doc = typeof document === "undefined" ? null : document;
  let stored: string | null = null;
  try {
    stored =
      typeof localStorage === "undefined"
        ? null
        : localStorage.getItem(LOCALE_COOKIE);
  } catch {
    // localStorage throws in private-mode / blocked-cookie browsers; the cookie still works.
    stored = null;
  }
  return resolveLocale({
    cookie: doc?.cookie,
    stored,
    languages: typeof navigator === "undefined" ? [] : navigator.languages,
  });
}

/** `'{count} pools'` + `{count: 3}` → `'3 pools'`. Unknown placeholders are left intact
 * so a missing param is visible in the UI rather than silently blank. */
function interpolate(template: string, params: MessageParams): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

function entryFor(key: MessageKey, loc: Locale): RuntimeEntry {
  const catalog = CATALOGS[loc];
  return catalog ? catalog[key] : en[key];
}

/**
 * `t('board.poolCount', { count: 22 })` → `'22 pools'` (and in `pl`, the `few` form —
 * 22 is `few`, not `many`).
 *
 * A plural entry requires a numeric `count`; without one there is no defensible form to
 * choose, so it falls back to `other` rather than guessing.
 */
export function t(key: MessageKey, params: MessageParams = {}): string {
  const entry = entryFor(key, active);
  if (typeof entry === "string") return interpolate(entry, params);
  const count = params.count;
  const category: PluralCategory<Locale> =
    typeof count === "number" ? pluralCategory(active, count) : "other";
  // A catalog is only reachable here if it type-checked, so the category is present.
  // `other` is defined for every CLDR locale, making it a total fallback.
  const form = entry[category] ?? entry.other ?? "";
  return interpolate(form, params);
}
