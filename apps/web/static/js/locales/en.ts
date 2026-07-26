// locales/en.ts — the SOURCE catalog. Every other locale's shape is derived from this
// one (see `CatalogFor` in ../i18n.ts), so this file defines the key set: a locale that
// omits a key, or supplies a bare string where English has a plural, fails `tsc`.
//
// Catalogs are `.ts` modules, not JSON, for two reasons: `tsc` emits only `.js` (a JSON
// file would never reach `static/dist/`), and the compile-time key/plural guarantees need
// a module the type-checker can see. See the plan's "Reversed decision: catalogs are .ts".
//
// SEED ONLY. S1 delivers the runtime; S3 moves the ~150 UI literals in here. The entries
// below are real strings already in the UI, chosen to exercise both entry kinds.
//
// Interpolation is `{name}`. A plural entry selects on the `count` param.

export const en = {
  "common.today": "Today",
  "board.hoursNotListed": "Hours not listed",

  // Plural entries. English needs only one/other; `pl` will need four, and the compiler
  // will insist on all four when locales/pl.ts is authored in S6.
  "board.poolCount": {
    one: "{count} pool",
    other: "{count} pools",
  },
  "basin.laneCount": {
    one: "{count} lane",
    other: "{count} lanes",
  },
} as const;
