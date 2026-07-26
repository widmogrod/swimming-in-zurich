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

  // --- InsightBar -----------------------------------------------------------------
  //
  // The summary is a LIST of independent clauses joined by ' · ', not one sentence
  // assembled from fragments. That distinction matters: the plan forbids building a
  // sentence by concatenation because word order differs per language — but a
  // middot-separated clause list is a visual list, and each clause below is a WHOLE
  // translatable unit that stands on its own. A translator may reorder words inside a
  // clause freely; the separator is punctuation, not grammar.
  "insight.day.pools": {
    one: "{count} pool with curated hours nearby",
    other: "{count} pools with curated hours nearby",
  },
  "insight.day.none": "No pools with curated hours for this day nearby",
  "insight.bestWindow":
    "best public window {public}/{total} at {facility} {start}–{end}",
  "insight.noSplit": "lane split not published yet",
  "insight.coverage": "{closed} closed, {unlisted} hours-not-listed nearby",
  "insight.pool.reliable":
    "Reliable public lanes at {facility}: up to {public} of {total} around {start}",
  "insight.pool.openDays": {
    one: "open {count} of 7 days this week",
    other: "open {count} of 7 days this week",
  },
  "insight.pool.none": "{facility}: no public sessions found this week",
  "insight.pool.thisPool": "this pool",

  // --- StateBlocks ----------------------------------------------------------------
  "state.closed.title": "Closed",
  "state.closed.body": "Closed — {detail}",
  "state.closed.bodyNoReason": "Closed for now.",
  "state.unlisted.title": "Hours not listed yet",
  "state.unlisted.body":
    "We don’t have this pool’s timetable yet — it may well be open. This is not the same as closed.",
  "state.none.title": "No pools nearby",
  "state.none.body":
    "Nothing matched here — try a wider area or a different day. Not the same as closed.",
  "state.unlisted.summary": {
    one: "{count} more pool nearby — hours not listed yet",
    other: "{count} more pools nearby — hours not listed yet",
  },

  // --- BoardLegend ----------------------------------------------------------------
  "legend.label": "Board legend",
  "legend.group.sessionType": "Session type",
  "legend.group.availability": "Availability",
  "legend.group.forYou": "For you",
  "legend.honestyNote":
    "Ribbon thickness is today’s real public-lane split — not busyness, which has no source yet.",
  "access.public": "Public swim",
  "access.lane": "Lane swim",
  "access.family": "Family time",
  "access.women": "Women only",
  "access.seniors": "Seniors only",
  "access.adults": "Adults only",
  "access.school": "School reserved",
  "access.club": "Club reserved",
  "legend.state.open": "Open (public lanes)",
  "legend.state.closed": "Closed — with reason",
  "legend.state.unknown": "Hours not listed yet",
  // --- Status codes from the API (S2 `detail_code`) --------------------------------
  //
  // Rendered from the CODE, never from the server's `detail` prose — that field is
  // English in one branch and curated German in the other. `closed_reason` still
  // interpolates the curated German text as DATA; S4 replaces it with a code.
  "status.closed": "Closed",
  "status.closed_reason": "Closed · {reason}",
  "status.uncurated": "Hours not listed",

  "elig.in": "You’re in",
  "elig.chk": "Check with the venue",
  "elig.no": "Not for you",
} as const;
