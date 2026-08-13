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
/**
 * Turn the `en` catalogue into an accented, expanded PSEUDOLOCALE.
 *
 * This is the gate no static rule can provide. `no-literal-string` sees SOURCE literals;
 * it cannot see a string that arrives from the API, is built by a template the rule was
 * told to ignore, or lives in a `.js` module still outside the lint scope. Under pseudo,
 * anything that renders WITHOUT accents was never routed through the catalogue.
 *
 * The ~40% padding is the second job: German and Polish run longer than English, and a
 * label that only just fits in `en` will clip. Padding surfaces that before a translator
 * does.
 *
 * Dev-only: enabled by `?pseudo=1`. Placeholders are left intact — accenting `{count}`
 * would break interpolation and hide the very bug this is meant to expose.
 */
const ACCENTS: Record<string, string> = {
  a: "á",
  b: "ḃ",
  c: "ç",
  d: "ḋ",
  e: "é",
  f: "ḟ",
  g: "ġ",
  h: "ĥ",
  i: "í",
  j: "ĵ",
  k: "ķ",
  l: "ł",
  m: "ṁ",
  n: "ñ",
  o: "ó",
  p: "ṗ",
  q: "q̈",
  r: "ŕ",
  s: "š",
  t: "ţ",
  u: "ú",
  v: "ṽ",
  w: "ŵ",
  x: "ẋ",
  y: "ý",
  z: "ž",
  A: "Á",
  B: "Ḃ",
  C: "Ç",
  D: "Ḋ",
  E: "É",
  F: "Ḟ",
  G: "Ġ",
  H: "Ĥ",
  I: "Í",
  J: "Ĵ",
  K: "Ķ",
  L: "Ł",
  M: "Ṁ",
  N: "Ñ",
  O: "Ó",
  P: "Ṗ",
  Q: "Q̈",
  R: "Ŕ",
  S: "Š",
  T: "Ţ",
  U: "Ú",
  V: "Ṽ",
  W: "Ŵ",
  X: "Ẋ",
  Y: "Ý",
  Z: "Ž",
};

export function pseudo(text: string): string {
  const accented = text.replace(
    /(\{\w+\})|([A-Za-z])/g,
    (_m, ph: string | undefined, ch: string | undefined) =>
      ph ?? ACCENTS[ch as string] ?? (ch as string),
  );
  // eslint-disable-next-line i18next/no-literal-string -- pseudolocale scaffolding, not copy
  return `⟦${accented}${"·".repeat(Math.ceil(text.length * 0.4))}⟧`;
}

function pseudoCatalog(source: RuntimeCatalog): RuntimeCatalog {
  const out: Record<string, RuntimeEntry> = {};
  for (const [key, entry] of Object.entries(source)) {
    out[key] =
      typeof entry === "string"
        ? pseudo(entry)
        : Object.fromEntries(
            Object.entries(entry).map(([k, v]) => [k, pseudo(v as string)]),
          );
  }
  return out as RuntimeCatalog;
}

/** Swap every message for its pseudolocalised form. Dev-only; irreversible for the page. */
export function enablePseudo(): void {
  CATALOGS[active] = pseudoCatalog(en);
}

export const OFFERED_LOCALES: readonly Locale[] = [
  "en",
  "de",
  "fr",
  "it",
  "pl",
];

/**
 * Each locale's name IN ITS OWN LANGUAGE (its endonym).
 *
 * Deliberately NOT catalogue entries: a language menu shows "Deutsch" to everyone, not
 * "German" to an English reader and "Tedesco" to an Italian one. Someone looking for their
 * own language scans for the word they would use — translating these would defeat the
 * menu's entire purpose. They are invariant data, like a pool's name.
 */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  de: "Deutsch",
  fr: "Français",
  it: "Italiano",
  pl: "Polski",
};

/**
 * Persist the chosen locale and reload.
 *
 * The RELOAD is required, not laziness: `<html lang>` is server-rendered, and many blocks
 * build their label tables at module scope (see `active` above), so re-translating the DOM
 * in place would leave both stale. The cookie is written rather than localStorage because
 * the server must be able to read it.
 */
export function chooseLocale(next: Locale): void {
  const year = 60 * 60 * 24 * 365;
  document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${year}; samesite=lax`;
  location.reload();
}

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

// Applied AT MODULE SCOPE, for the same reason the locale is (see `active` above): the
// blocks build their label tables when they are imported, and this module is imported
// before all of them. Calling enablePseudo() from app.ts's main() left every module-scope
// table in plain English — which the pseudo pass then dutifully reported as
// "uncatalogued", a false alarm caused by the tool itself.
if (
  typeof location !== "undefined" &&
  new URLSearchParams(location.search).has("pseudo")
) {
  enablePseudo();
}

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
