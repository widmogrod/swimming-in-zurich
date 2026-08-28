#!/usr/bin/env node
// locales_to_xcstrings.mjs — the ONE bridge from the web's message catalogs to iOS.
//
// The web catalogs (`apps/web/static/js/locales/*.ts`) are the source of truth for every
// sentence this product says, in all five languages. iOS does not get a second catalog:
// it gets a PROJECTION of that one, exactly as `ios.sqlite` is a projection of the gold
// store. Two catalogs would be two places for a translation to drift.
//
// WHY NODE, AND WHY `dist/`. The catalogs are TypeScript modules (not JSON — see
// CLAUDE.md: `tsc` emits only `.js`, and the compile-time plural guarantees need a module
// the checker sees). Hand-parsing TypeScript from Python would be a second, worse
// TypeScript parser. So this reads the COMPILED `apps/web/static/dist/locales/*.js`, the
// same way `scripts/crap_ts.mjs` reads TS-side build artifacts. Run `npm run build` first.
//
// THE PLACEHOLDER PROBLEM, and why the output is positional.
// The web writes `{name}`; iOS needs printf specifiers. A translation is free to REORDER
// its placeholders ("um {hhmm} geöffnet" vs "opens {hhmm}"), so a bare `%@` stream would
// silently swap two values in some locale. Every specifier is therefore POSITIONAL
// (`%1$@`, `%2$@`), numbered by the order the placeholder first appears in the ENGLISH
// entry — the one catalog every other is derived from.
//
// THE PLURAL PROBLEM. `xcstringstool` refuses a plural variation whose forms do not
// reference the number ("Plural variation requires referencing the number in the string"),
// and Foundation selects the category from an INTEGER argument. So in a plural entry the
// `count` placeholder is emitted as `%N$lld`, never `%N$@`: a `%@` there both fails to
// compile and, if it did, would not drive selection.
//
// A plural entry's categories are copied VERBATIM from the catalog, which `plurals.ts`
// already forces to be exactly the CLDR set for that locale. The Run Script build phase
// (`scripts/xcstrings_plural_gate.py`) re-checks that on the emitted file, because Xcode
// itself has no error and no documented warning for a missing category — a Polish `many`
// left out falls back to `other`, the DECIMAL form, which is the broken grammar
// `plurals.ts` exists to prevent.
//
// Usage:
//   node scripts/locales_to_xcstrings.mjs              # write the catalog + the Swift table
//   node scripts/locales_to_xcstrings.mjs --check      # fail if either is stale

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");
const DIST = resolve(REPO, "apps/web/static/dist");
const XCSTRINGS = resolve(
  REPO,
  "apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings",
);
const SWIFT_TABLE = resolve(
  REPO,
  "apps/ios/Sources/SwimZHKit/Catalog.generated.swift",
);
// THE THIRD OUTPUT, and it goes to the APP target rather than the package. iOS reads
// permission purpose strings out of the app bundle's `InfoPlist.xcstrings` before any of
// our code runs, so they cannot live in `SwimZHKit`'s resources with every other sentence.
const INFOPLIST_XCSTRINGS = resolve(
  REPO,
  "apps/ios/App/SwimZH/InfoPlist.xcstrings",
);

/** Web catalog key -> the Info.plist key iOS shows it under.
 *
 *  A purpose string is a SENTENCE this product says, so it is authored in the web catalogs
 *  with every other one — the same rule that puts `state.none.body.phone` there despite the
 *  web never rendering it. What is different is only WHERE it has to be installed, which is
 *  what this table is.
 *
 *  It matters that these are localised at all: iOS renders a purpose string in the SYSTEM's
 *  language, so a build setting (`INFOPLIST_KEY_NSLocation…`) can only ever be one language,
 *  and a German reader would be asked for their location in English by an app that speaks
 *  German everywhere else. */
const INFOPLIST_KEYS = {
  "ios.location.purpose": "NSLocationWhenInUseUsageDescription",
};

/** The plural-selecting placeholder. Exactly one per entry, by construction. */
const COUNT = "count";

const SOURCE_LANGUAGE = "en";

/** Placeholders in `text`, in order of first appearance, de-duplicated. */
export function placeholderOrder(text) {
  const seen = [];
  for (const match of text.matchAll(/\{(\w+)\}/g)) {
    if (!seen.includes(match[1])) seen.push(match[1]);
  }
  return seen;
}

/** Every string form of a catalog entry: one for a plain entry, one per category. */
export function forms(entry) {
  return typeof entry === "string" ? [entry] : Object.values(entry);
}

/**
 * `{name}` -> `%N$@` (or `%N$lld` for the plural count), and a literal `%` -> `%%`.
 *
 * The `%` escape runs FIRST and on the raw text, so it cannot corrupt a specifier this
 * function itself just wrote. A catalog message containing a percent sign is legitimate
 * ("50% of lanes"); left unescaped it would be read as a format specifier and print
 * whatever happened to be next on the argument list.
 */
export function toFormat(text, order, isPlural) {
  let out = text.replace(/%/g, "%%");
  for (const [index, name] of order.entries()) {
    const specifier = isPlural && name === COUNT ? "lld" : "@";
    out = out.split(`{${name}}`).join(`%${index + 1}$${specifier}`);
  }
  return out;
}

function unit(value) {
  return { stringUnit: { state: "translated", value } };
}

/**
 * Build the `.xcstrings` document.
 *
 * `catalogs` is `{ en, de, fr, it, pl }` of `key -> string | Record<category, string>`.
 */
export function buildDocument(catalogs) {
  const en = catalogs[SOURCE_LANGUAGE];
  if (!en) throw new Error(`no '${SOURCE_LANGUAGE}' catalog`);
  const languages = Object.keys(catalogs).sort();

  const strings = {};
  for (const key of Object.keys(en).sort()) {
    const isPlural = typeof en[key] !== "string";
    // The parameter order is ENGLISH's, for every locale. A translation that reorders its
    // placeholders still points each specifier at the same argument.
    const order = placeholderOrder(forms(en[key]).join(" "));
    if (isPlural && !order.includes(COUNT)) {
      throw new Error(`${key}: a plural entry must interpolate {${COUNT}}`);
    }

    const localizations = {};
    for (const language of languages) {
      const entry = catalogs[language][key];
      if (entry === undefined) throw new Error(`${language} is missing ${key}`);
      if (typeof entry === "string") {
        if (isPlural) throw new Error(`${language}/${key}: expected a plural entry`);
        localizations[language] = unit(toFormat(entry, order, false));
        continue;
      }
      if (!isPlural) throw new Error(`${language}/${key}: expected a plain string`);
      const plural = {};
      for (const category of Object.keys(entry).sort()) {
        plural[category] = unit(toFormat(entry[category], order, true));
      }
      localizations[language] = { variations: { plural } };
    }
    strings[key] = { extractionState: "manual", localizations };
  }
  return { sourceLanguage: SOURCE_LANGUAGE, strings, version: "1.0" };
}

/**
 * The Swift side of the same contract: which parameters each key takes, in order.
 *
 * Foundation's compiled catalog keeps only positional specifiers, so the NAMES are gone
 * by the time the phone reads a string. Swift call sites pass a named dictionary (an
 * ordered array would make a two-argument message a coin flip), so the ordering has to
 * travel out of band — this table is that channel, generated from the same pass that
 * numbered the specifiers, so the two cannot disagree.
 */
export function buildSwiftTable(document, orders) {
  const rows = [];
  for (const [key, value] of Object.entries(document.strings)) {
    const source = value.localizations[SOURCE_LANGUAGE];
    const text = source.stringUnit
      ? source.stringUnit.value
      : Object.values(source.variations.plural)
          .map((v) => v.stringUnit.value)
          .join(" ");
    // Read the parameter list back off the EMITTED text, so the table describes what was
    // actually written rather than what the builder intended to write.
    const found = new Map();
    for (const match of text.matchAll(/%(\d+)\$(lld|@)/g)) {
      found.set(Number(match[1]), match[2]);
    }
    const arity = found.size === 0 ? 0 : Math.max(...found.keys());
    const order = orders.get(key) ?? [];
    const parameters = [];
    for (let position = 1; position <= arity; position += 1) {
      const kind = found.get(position);
      if (kind === undefined) throw new Error(`${key}: gap at argument ${position}`);
      const name = order[position - 1];
      if (name === undefined) throw new Error(`${key}: no name for argument ${position}`);
      parameters.push(
        `Parameter(name: "${name}", kind: ${kind === "lld" ? ".integer" : ".text"})`,
      );
    }
    const isPlural = source.variations !== undefined;
    // Emitted the way `swift format --strict` wants it read back: one parameter per line with
    // a trailing comma, so the file this writes needs no formatting pass. A generator whose
    // output the linter rejects is a generator nobody can run twice.
    if (parameters.length === 0) {
      rows.push(`    "${key}": Entry(parameters: [], isPlural: ${isPlural}),`);
    } else {
      rows.push(`    "${key}": Entry(`);
      rows.push(`      parameters: [`);
      // A trailing comma on the last element only when there IS more than one. That is
      // `swift format --strict`'s TrailingComma rule, which treats a single-element literal as
      // "single line" however it is laid out — determined by running the formatter on this
      // file's own output rather than by reading the rule, and encoded here so the generated
      // file needs no formatting pass. A generator whose output the linter rejects is a
      // generator nobody can run twice.
      for (const [index, parameter] of parameters.entries()) {
        const comma = parameters.length > 1 || index < parameters.length - 1 ? "," : "";
        rows.push(`        ${parameter}${comma}`);
      }
      rows.push(`      ], isPlural: ${isPlural}),`);
    }
  }
  return `// Catalog.generated.swift — GENERATED by scripts/locales_to_xcstrings.mjs. Do not edit.
//
// The argument shape of every message in \`Resources/Localizable.xcstrings\`.
//
// Foundation's compiled catalog is positional: \`%1$@\`, \`%2$@\`. The placeholder NAMES
// (\`{hhmm}\`, \`{total}\`) exist only in the web catalogs this file is generated from, so a
// Swift call site that passes a dictionary needs the ordering from somewhere. This is that
// somewhere, written by the same pass that numbered the specifiers.
//
// \`isPlural\` decides which lookup Foundation needs: a plural entry compiles to a
// \`.stringsdict\` whose format must be expanded by \`String(format:locale:)\` with the
// READER'S locale — the bundle picks the language, the locale picks the plural rule, and
// getting only one of them right renders Polish with English grammar (see Localized.swift).

extension Catalog {
  /// One positional argument: the name the catalogs use for it, and how it is rendered.
  public struct Parameter: Sendable, Equatable {
    public enum Kind: Sendable, Equatable {
      /// Rendered with \`%lld\` — the plural-selecting count.
      case integer
      /// Rendered with \`%@\` — an already-formatted value (a time, a place, a price).
      case text
    }
    public let name: String
    public let kind: Kind
    public init(name: String, kind: Kind) {
      self.name = name
      self.kind = kind
    }
  }

  /// What one message expects: its arguments, in the order the format string numbers them.
  public struct Entry: Sendable, Equatable {
    public let parameters: [Parameter]
    public let isPlural: Bool
    public init(parameters: [Parameter], isPlural: Bool) {
      self.parameters = parameters
      self.isPlural = isPlural
    }
  }

  /// Every key in the catalog, with its argument shape.
  public static let entries: [String: Entry] = [
${rows.join("\n")}
  ]
}
`;
}

async function loadCatalogs() {
  const catalogs = {};
  for (const language of ["en", "de", "fr", "it", "pl"]) {
    const module = await import(`file://${DIST}/locales/${language}.js`);
    const catalog = module[language];
    if (!catalog) throw new Error(`dist/locales/${language}.js exports no '${language}'`);
    catalogs[language] = catalog;
  }
  return catalogs;
}

function readOrNull(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/** The app bundle's `InfoPlist.xcstrings`: the permission purpose strings, keyed by the
 *  Info.plist name iOS looks them up under.
 *
 *  Deliberately flat — no plurals and no placeholders. A purpose string is one sentence shown
 *  once in a system dialog, and neither iOS nor this generator has anywhere to put an argument
 *  in it, so the plural and positional machinery the main catalog needs would be dead weight
 *  here and a second place for it to go wrong. */
function buildInfoPlist(catalogs) {
  const strings = {};
  for (const [catalogKey, plistKey] of Object.entries(INFOPLIST_KEYS)) {
    const localizations = {};
    for (const [language, entries] of Object.entries(catalogs)) {
      const value = entries[catalogKey];
      if (typeof value !== "string") {
        throw new Error(
          `${catalogKey} is missing from ${language}.ts, or is a plural entry — ` +
            "an Info.plist purpose string must be one plain sentence per language",
        );
      }
      localizations[language] = { stringUnit: { state: "translated", value } };
    }
    strings[plistKey] = { extractionState: "manual", localizations };
  }
  return { sourceLanguage: SOURCE_LANGUAGE, strings, version: "1.0" };
}

async function main() {
  const check = process.argv.includes("--check");
  const catalogs = await loadCatalogs();
  const document = buildDocument(catalogs);
  const orders = new Map(
    Object.keys(catalogs[SOURCE_LANGUAGE]).map((key) => [
      key,
      placeholderOrder(forms(catalogs[SOURCE_LANGUAGE][key]).join(" ")),
    ]),
  );
  const json = `${JSON.stringify(document, null, 2)}\n`;
  const swift = buildSwiftTable(document, orders);
  const infoPlist = `${JSON.stringify(buildInfoPlist(catalogs), null, 2)}\n`;

  const stale = [];
  if (readOrNull(XCSTRINGS) !== json) stale.push(XCSTRINGS);
  if (readOrNull(SWIFT_TABLE) !== swift) stale.push(SWIFT_TABLE);
  if (readOrNull(INFOPLIST_XCSTRINGS) !== infoPlist) stale.push(INFOPLIST_XCSTRINGS);

  if (check) {
    if (stale.length) {
      console.error(
        `stale, regenerate with \`node scripts/locales_to_xcstrings.mjs\`:\n  ${stale.join("\n  ")}`,
      );
      process.exit(1);
    }
    console.log(`locales -> xcstrings: up to date (${Object.keys(document.strings).length} keys)`);
    return;
  }
  writeFileSync(XCSTRINGS, json);
  writeFileSync(SWIFT_TABLE, swift);
  writeFileSync(INFOPLIST_XCSTRINGS, infoPlist);
  console.log(
    `wrote ${Object.keys(document.strings).length} keys x 5 locales to ${XCSTRINGS}`,
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await main();
}
