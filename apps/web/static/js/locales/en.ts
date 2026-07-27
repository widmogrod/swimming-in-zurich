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
  // The board ribbon's own label — sentence-cased, distinct from the insight clause.
  "insight.noSplit.label": "Lane split not published",
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

  // --- Closure codes (S4) -----------------------------------------------------------
  //
  // The curated German is now CLASSIFIED at build time, so these are translatable words
  // rather than passthrough prose. `closure.unmapped` is the fail-safe: a phrase the
  // builder could not classify rides through verbatim, so the label stays TRUE rather
  // than going blank — and `swimzh build` reported it on stderr.
  "closure.seasonal_break": "Summer break",
  "closure.seasonal_break_maintenance": "Summer break / maintenance",
  "closure.maintenance": "Maintenance",
  "closure.operational_break": "Company holidays",
  "closure.christmas_eve": "Christmas Eve",
  "closure.public_holiday": "Public holiday",
  "closure.public_holiday_named": "{holiday}",

  // --- Public holidays (S4) ---------------------------------------------------------
  //
  // Three tiers, per the plan's "Resolved: holidays":
  //   * shared feasts translate cleanly (Auffahrt is just Swiss German for Ascension);
  //   * Bundesfeier is nameable descriptively, the way Bastille Day is abroad;
  //   * Berchtoldstag is Swiss/Liechtenstein-only with NO equivalent — keep the German
  //     and gloss it rather than inventing a translation.
  // For fr/it these must be SOURCED from the Confederation's official names, not invented:
  // French and Italian are Swiss national languages, so an authoritative name exists.
  "holiday.new_year": "New Year’s Day",
  "holiday.berchtoldstag": "Berchtoldstag (2 January, Swiss public holiday)",
  "holiday.good_friday": "Good Friday",
  "holiday.easter_monday": "Easter Monday",
  "holiday.labour_day": "May Day",
  "holiday.ascension": "Ascension Day",
  "holiday.whit_monday": "Whit Monday",
  "holiday.national_day": "Swiss National Day",
  "holiday.christmas": "Christmas Day",
  "holiday.st_stephens": "St Stephen’s Day",
  // Fail-safe: an unrecognised name rides through verbatim.
  "holiday.unknown": "{holiday}",
  "closure.no_sessions": "No sessions scheduled",
  "closure.special": "Closed",
  "closure.unmapped": "{text}",

  "elig.in": "You’re in",
  "elig.chk": "Check with the venue",
  "elig.no": "Not for you",
  "elig.chk.short": "Check",

  // --- StatePill --------------------------------------------------------------------
  "pill.open": "Open",
  "pill.opensLater": "Opens later",
  "pill.closed": "Closed",
  "pill.unknown": "Hours not listed",

  // --- Badges -----------------------------------------------------------------------
  "badge.teachingPool": "Teaching pool",
  "badge.metres": "{length} m",
  "age.minutes": "{count} min",
  "age.hours": "{count} h",
  "age.days": {
    one: "{count} day",
    other: "{count} days",
  },
  "badge.poolAria": "{length} metre pool, {lanes}",

  // --- SourceStrip ------------------------------------------------------------------
  "sources.label": "Sources",
  "sources.official": "Official page",
  "sources.lanePlan": "Lane plan",
  "sources.prices": "Prices",
  "sources.pdf": "PDF",
  "sources.pdfLabel": "{label} PDF",
  "sources.chipAria": "{name} — opens {host} in a new tab",

  // --- Combobox / PlaceTypeahead ----------------------------------------------------
  "combo.noMatches": "No matches",
  "combo.noPoolsMatch": "No pools match",
  "place.useMyLocation": "Use my location",
  "place.myLocation": "My location",

  // --- DateStepper ------------------------------------------------------------------
  "date.selectedDay": "Selected day",
  "date.previousDay": "Previous day",
  "date.nextDay": "Next day",
  "date.selectedWeek": "Selected week",
  "date.previousWeek": "Previous week",
  "date.nextWeek": "Next week",
  "date.weekOf": "Week of {date}",

  // --- Header -----------------------------------------------------------------------
  "app.title": "Swimming in Zürich",
  "header.language": "Language",
  "header.copyLink": "Copy link",
  "header.copied": "Copied",
  "header.copyAria": "Copy a shareable link to this view",
  "header.themeAria": "Theme: {theme} (click to change)",
  "theme.auto": "Auto",
  "theme.light": "Light",
  "theme.dark": "Dark",

  // --- LaneGantt --------------------------------------------------------------------
  "gantt.lane": "Lane {lane}",
  "gantt.public": "Public",
  "gantt.reserved": "Reserved",
  "gantt.readout": "{hhmm} · {public} of {total} lanes public",

  // --- FilterToolbar ----------------------------------------------------------------
  "toolbar.label": "Search filters",
  "toolbar.view": "View",
  "toolbar.viewMode": "View mode",
  "toolbar.mode.day": "Day",
  "toolbar.mode.pool": "Pool",
  "toolbar.near": "Near",
  "toolbar.wherefrom": "Where from?",
  "toolbar.gender": "Gender",
  "toolbar.gender.any": "Any",
  "toolbar.gender.female": "Female",
  "toolbar.gender.male": "Male",
  "toolbar.gender.diverse": "Diverse",
  "toolbar.age": "Age",
  "toolbar.age.any": "Any age",
  "toolbar.age.child": "Child",
  "toolbar.age.teen": "Teen",
  "toolbar.age.adult": "Adult",
  "toolbar.age.senior": "Senior",
  "toolbar.lapOnly": "Lap lanes only",
  "toolbar.busyness": "Busyness",
  "toolbar.busynessReason": "Busyness has no data source yet — not available.",
  "toolbar.searchPool": "Search a pool…",
  "toolbar.pool": "Pool",

  // --- DetailPanel ------------------------------------------------------------------
  "detail.fact.today": "Today",
  "detail.fact.basin": "Basin",
  "detail.fact.distance": "Distance",
  "detail.fact.price": "Price",
  "detail.fact.water": "Water",
  "detail.fact.liveWater": "Live water",
  "detail.fact.eligibility": "Eligibility",
  "detail.fact.busyness": "Busyness",
  "detail.fact.freshness": "Freshness",
  // Price rows are GENERATED from `category` + `amount_chf`, never translated from the
  // curated German `display` ("Erwachsene CHF 8.00") — the category is already a machine
  // value, and the currency is formatted by Intl so its symbol position follows the
  // locale (CHF 8.00 in en/de-CH, 8,00 CHF in fr-CH/pl).
  "price.adult": "Adult {amount}",
  "price.youth": "Youth {amount}",
  "price.child": "Child {amount}",
  "price.senior": "Senior {amount}",
  "detail.notListed": "Not listed",
  "detail.notShown": "Not shown",
  "detail.notDated": "Not dated",
  "detail.notAvailable": "Not available",
  "detail.notAvailableYet": "Not available yet",
  "detail.notYetMeasured": "Not yet measured",
  "live.not_configured": "Not configured",
  "live.provider_error": "Source unavailable",
  "live.no_key": "Not available",
  "detail.liveOpen": "open",
  "detail.liveClosed": "closed",
  "board.nearestFirst": "Nearest first",
  "detail.waterNotPublished": "Water temperature not published",
  "detail.tempMeasured": "measured",
  "detail.tempNominal": "nominal (design)",
  "detail.checked": "Checked {date}",
  "detail.weekButton": "See this pool’s week →",
  "detail.pool": "Pool",
  "detail.openLaneSplit": "Open · lane split not published",
  "detail.noPublicLanes": "No public lanes today",
  "detail.openRange": "Open · {from}–{to}",
  "detail.closedReason": "Closed · {reason}",
  "detail.hoursUnknown": "Hours not listed — may well be open",
  "detail.headline": "of {total} lanes public · {hhmm}",
  "detail.peakNote": "peak {peak} of {total}",
  "detail.headlineAria":
    "{public} of {total} lanes public at {hhmm} (peak {peak})",
  "detail.note.lanesUnknown":
    "No published lane plan for this pool yet — the hours are curated, but the per-lane public/reserved split isn’t.",
  "detail.note.closed":
    "This pool is closed for a stated reason on this day — it is not merged with pools we simply lack data for.",
  "detail.note.uncurated":
    "We have this pool’s location but no session timetable yet. Unknown is not the same as closed — it may well be open.",
  "detail.emptyPanel": "Click any pool to see its hours, price and lane plan.",

  // --- Provenance -------------------------------------------------------------------
  "prov.official": "Official schedule",
  "prov.illustrative": "Illustrative — read from the pool’s website",
  "prov.lastChecked": " · last checked {date}",
} as const;
