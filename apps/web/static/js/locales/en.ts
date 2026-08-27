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
  "access.girls": "Girls only",
  "access.genderDiverse": "Trans and non-binary",
  "access.accompanied": "Children with an adult",
  "legend.state.open": "Open (public lanes)",
  "legend.state.closed": "Closed — with reason",
  "legend.state.unknown": "Hours not listed yet",
  // --- The lane stack (lane-stack-board S4) ----------------------------------------
  // A row whose basin has a published Belegungsplan is drawn as one sub-row per lane.
  // The fourth entry decodes the pools that publish NO split — its own state, never
  // "no lanes free".
  "legend.group.laneStack": "Lane stack",
  "legend.lane.public": "Lane open to the public",
  "legend.lane.reserved": "Lane reserved (holder named where it fits)",
  "legend.lane.best": "Most public lanes free",
  "legend.lane.unpublished": "Lane split not published",
  // --- Status codes from the API (S2 `detail_code`) --------------------------------
  //
  // Rendered from the CODE, never from the server's `detail` prose — that field is
  // English in one branch and curated German in the other. `closed_reason` still
  // interpolates the curated German text as DATA; S4 replaces it with a code.
  "status.closed": "Closed",
  "status.closed_reason": "Closed · {reason}",
  "status.uncurated": "Hours not listed",
  // Three-state schedule freshness (S1): scrapeable-but-not-yet vs no source at all. Both are
  // honestly "unknown", never "closed" — kept distinct so the reader knows which.
  "status.awaiting_scrape": "Hours not published yet",
  "status.no_source": "Hours not listed",

  // --- Fair-weather sessions (seasonal-hours S4) -------------------------------------
  //
  // Per SESSION, never per day: the city publishes an outdoor pool's late block only for
  // good weather, and the earlier block unconditionally. The marker therefore NAMES the
  // conditional spans ("14:00–21:00") instead of flagging the whole pool — a day-level
  // "maybe" would turn the guaranteed morning into an unknown.
  "session.fairWeather": "Fair weather only · {spans}",

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
  // Derived by the resolver from the pool's OWN annual window, so it cannot know which
  // season it is outside — an outdoor pool is out of season in WINTER. Keep every
  // translation season-neutral; `closure.seasonal_break` above is the curated "Sommerpause"
  // and stays summer-specific.
  "closure.out_of_season": "Closed for the season",
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
  "place.locating": "Finding where you are…",
  "place.refused.denied":
    "SwimZH cannot see your location. You can allow it in Settings.",
  "place.refused.restricted": "This device does not allow location for apps.",
  "place.refused.unavailable":
    "No position available right now. Distances are from the place above.",
  "action.openSettings": "Open Settings",
  "ios.location.purpose":
    "SwimZH uses your location to measure how far each pool is and to show you on the map. It stays on your phone.",
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
  // The O2 group divider on the board: everything below it has no session to plan today —
  // shut pools, pools whose hours we do not have, and pools open with no published timetable.
  // It must NOT say "closed": an unknown schedule is not a closure (each row states its own).
  "board.noSessionsGroup": "No sessions published today",
  "detail.waterNotPublished": "Water temperature not published",
  "detail.tempMeasured": "measured",
  "detail.liveMeasuredAgo": "measured {age} ago",
  "detail.closedNote": "Closed — {reason}. {note}",
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
  "prov.scraped": "Official schedule — scraped from the pool’s own page",
  "prov.awaiting": "No timetable published yet",
  "prov.noSource": "No timetable source for this pool",
  "prov.lastChecked": " · last checked {date}",

  // --- Phone pool list (variant E) --------------------------------------------------
  //
  // The tier headings are the phone list's promise that its ranking is not arbitrary:
  // a surprising #1 is defensible once the group it sits in is named.
  "mobile.tier.now": "Swim now",
  "mobile.tier.soon": "Later today",
  "mobile.tier.unknown": "Hours not listed",
  "mobile.tier.closed": "Closed",

  // Verdict heads. "Partly reserved" exists so a session holding lanes back is never
  // announced as "Open now" — that would promise water that may not be there.
  "mobile.verdict.openNow": "Open now",
  "mobile.verdict.partlyReserved": "Partly reserved",
  "mobile.verdict.notYoursUntil": "Not yours until {hhmm}",
  "mobile.verdict.opensAt": "Opens {hhmm}",
  "mobile.verdict.doneForToday": "Done for today",
  "mobile.verdict.closedAllDay": "Closed all day",
  "mobile.verdict.hoursUnknown": "Hours not listed",
  // Trailing clauses — whole units, joined to the head by ' · ' as a visual list.
  "mobile.verdict.untilTime": "until {hhmm}",
  "mobile.lanesUntil": "{public} of {total} lanes public until {hhmm}",

  "mobile.openToYou": {
    one: "{count} pool open to you now",
    other: "{count} pools open to you now",
  },
  "mobile.openToYouOn": {
    one: "{count} open to you on {day}",
    other: "{count} open to you on {day}",
  },
  "mobile.filters": "Filters",
  "mobile.today": "Today",
  "mobile.lanePlan": "Lane plan",

  // --- The native iOS app (native-ios-app S4) --------------------------------------
  //
  // The phone is not a second product with a second vocabulary: it renders THIS catalog,
  // projected into `Localizable.xcstrings` by `scripts/locales_to_xcstrings.mjs`. Keys
  // added below are the ones the web has no surface for (a facility sheet, a VoiceOver
  // layout for a Canvas, an all-pools browser); everything the web already words —
  // `access.*`, `closure.*`, `mobile.verdict.*`, `toolbar.age.*` — is REUSED rather than
  // re-authored, which is the only way the two clients can be checked against each other.

  // Day states. Four of the five are admissions that we do not know a pool's hours; not one
  // of them may be worded as a closure. `stateLabelsAreDayAgnostic` (Swift) also forbids
  // "today"/"now" here: a state row is rendered for every date in the horizon.
  "state.openUnscheduled": "Open, but hours are not listed",
  "state.beyondHorizon": "Beyond the published horizon",
  "state.beyondHorizon.body":
    "We publish answers through {date}. This is not the same as the pools being closed — we simply have not resolved this day yet.",
  "state.notStated": "State not stated",
  // A status a newer store carries and this build has never seen: said as itself, never
  // guessed at. Guessing, given the vocabulary, would mean guessing "closed".
  "state.unrecognised": "{status}",
  // Whole sentences rather than a "Closed" head glued to a reason clause: the two halves
  // do not compose in every language, and `status.closed_reason` above already shows what
  // the nesting costs when the reason is itself a translated word.
  "state.closed.outOfSeason": "Closed — outside its season",
  "state.closed.noSessions": "Closed — no sessions",
  "state.closed.unmapped": "Closed — “{text}”",
  "state.closed.unclassified": "Closed — reason not classified",
  "state.closed.other": "Closed — {code}",
  "state.closed.unstated": "Closed — reason not stated",

  // Phone list tiers and verdicts beyond the web's set.
  "tier.scheduled": "Open that day",
  "verdict.notOpenToYou": "Not open to you",
  "verdict.hasSessions": "Has sessions",
  "headline.noneNowNextAt": "Nothing open to you now — next at {hhmm}",
  // The third of the four "nothing open right now" answers, and the one whose absence was a
  // defect: there IS a later session, but nothing we were told decides whether the reader may
  // attend it (a women-only hour, no gender set). `noneLeftToday` would state a definite
  // negative from an unknown, which is the one claim this app never makes.
  "headline.noneNowMaybeAt":
    "Nothing open to you now — check with the pool about {hhmm}",
  "headline.noneLeftToday": "Nothing more open to you today",
  "headline.poolsWithSessions": {
    one: "{count} pool with sessions",
    other: "{count} pools with sessions",
  },
  // Deliberately NOT plural entries: there is no noun to inflect, so a plural form per
  // locale would be four identical strings — which Polish's own `other`-is-the-decimal-form
  // rule then flags as a copy-paste. The count is a bare number here.
  "row.moreToday": "+{count} more today",
  "row.moreThatDay": "+{count} more that day",

  // Day-level banners. A warning is OURS (it qualifies the answer); a notice is the pool's
  // own words and is never translated, so it has no key.
  "banner.calendarCoverage.title": "Holiday calendar incomplete",
  "banner.holidayHoursUnverified.title": "Holiday hours unconfirmed",
  "banner.generic.title": "Please note",
  // BYTE-FOR-BYTE the sentence `etl/ios_export.render_warning` produces, capitalisation and
  // final punctuation included — which is why it reads as a fragment rather than as a sentence.
  // That is deliberate: `GoldenAnswerTests` renders this key through the English catalog and
  // compares it to the golden `find_swim_options` output, so any drift in MEANING between the
  // exporter and the client fails there. The other four locales are ordinary sentences; only
  // English is the oracle.
  "warning.calendar_coverage":
    "calendar data not available for {year}; holiday-dependent schedules may be inaccurate",
  "warning.holiday_hours_unverified":
    "{date} is a public holiday and these pools do not publish their holiday hours; the times shown are their usual weekday hours and are unconfirmed: {pools}",
  "warning.unknown": "{code}",

  // The access legend's explanations. The LABELS are `access.*` above, shared with the web
  // board's legend; only the sentences are new.
  "access.public.desc":
    "Open public swimming — anyone may enter during these hours.",
  "access.lane.desc":
    "Lane swimming (Bahnenschwimmen) — public, organised into lanes for laps/training.",
  "access.family.desc":
    "Family/children session — public, oriented to families and kids.",
  "access.women.desc":
    "Women-only session (Frauenbad / Frauenschwimmen) — reserved for women.",
  "access.seniors.desc":
    "Seniors session — reserved for guests aged 60 and over.",
  "access.school.desc": "Reserved for school classes — not open to the public.",
  "access.club.desc":
    "Reserved for a club/association — not open to the public.",
  "access.adults.desc":
    "Adults-only public window — reserved for guests aged 18 and over (typical for school-pool evening swims).",
  "access.girls.desc":
    "Girls-only session (für Mädchen) — the pool publishes no age cutoff, so confirm with the venue.",
  "access.genderDiverse.desc":
    "Session open to trans and non-binary people aged 16 and over.",
  "access.accompanied.desc":
    "For children only when accompanied by an adult (für Kinder nur mit Erwachsenen).",
  // Never "public swimming" for a class this build does not know: an unheard-of session is
  // a reason to ask, not a welcome.
  "access.unknown": "Session — check with the pool",

  // The WFS roster's kind vocabulary. `poolKind.unknown` passes an unseen kind through as
  // itself rather than folding it into "indoor" — a mislabelled pool sends somebody to the
  // wrong kind of water.
  "poolKind.indoor": "Indoor pool",
  "poolKind.outdoor": "Outdoor pool",
  "poolKind.lake": "Lake bath",
  "poolKind.river": "River bath",
  "poolKind.thermal": "Thermal bath",
  "poolKind.school": "School pool",
  "poolKind.paddling": "Paddling pool",
  "poolKind.unknown": "{kind}",

  // --- The facility sheet -----------------------------------------------------------
  //
  // iOS 26 renders a section header exactly as it is written — it no longer upper-cases
  // them — so every heading here is sentence case and must READ as a heading unaided.
  "detail.section.where": "Where",
  "detail.section.admission": "Admission",
  "detail.section.season": "Season",
  "detail.section.basins": "Basins",
  "detail.section.features": "Features",
  "detail.section.lockers": "Lockers",
  "detail.section.rentals": "Rentals",
  "detail.section.lanes": "Lane plans",
  "detail.section.provenance": "Where this came from",

  "detail.fact.address": "Address",
  "detail.fact.phone": "Phone",
  "detail.fact.website": "Website",
  "detail.fact.about": "About",
  "detail.fact.schedule": "Schedule",
  "detail.fact.entry": "Entry",
  "detail.fact.yourRate": "Your rate",
  "detail.fact.pricesRead": "Prices read",
  "detail.fact.tariffPage": "Tariff page",
  "detail.fact.lastAdmission": "Last admission",
  "detail.fact.season": "Open season",

  "freshness.scraped": "Published by the pool",
  "freshness.awaiting": "Not published yet",
  "freshness.noSource": "No timetable to read",
  "freshness.unknown": "Unrecognised state: {state}",
  "freshness.awaiting.caveat":
    "This pool has a timetable page, but it has not been read into this app yet.",
  "freshness.noSource.caveat":
    "This pool publishes no timetable of its own. That is not the same as being closed.",
  "freshness.unknown.caveat":
    "This app does not recognise this state; check with the pool.",

  "priceCategory.adult": "Adult",
  "priceCategory.youth": "Youth",
  "priceCategory.child": "Child",
  "priceCategory.senior": "Senior",
  "priceCategory.unknown": "{category}",
  "price.minAgeCaveat": "Published for ages {minAge} and over.",
  "price.staleCaveat":
    "Prices come from the pool’s own page and can change without notice.",

  "admission.free": "Free",
  "admission.tariff": "Paid — see the rates below",
  // NOT "free": an unstated admission is unknown, and "free" sends somebody to a turnstile
  // with no money.
  "admission.unknown": "Not published — check with the pool",
  "detail.lastAdmission.value": "{duration} before closing",

  "season.range": "{from} to {to}",
  "season.rangeWithDays": "{startDay} {from} to {endDay} {to}",
  "season.fairWeatherCaveat":
    "Published for fair weather; the pool may not open in poor weather.",

  "basin.fact.size": "Size",
  "basin.fact.lanes": "Lanes",
  "basin.fact.water": "Water",
  "basin.fact.diving": "Diving",
  "basin.fact.lanePlan": "Lane plan",
  "basin.size.lengthByWidth": "{length} × {width}",
  "basin.size.length": "{length}",
  "basin.size.width": "{width} wide",
  "basin.tempNominalCaveat": "The pool’s stated temperature, not a reading.",
  "basin.parsedProseCaveat":
    "Read from the pool’s prose, so it may be approximate.",
  "basinKind.swimmer": "Swimmers’ pool",
  "basinKind.non_swimmer": "Non-swimmers’ pool",
  "basinKind.diving": "Diving pool",
  "basinKind.learner": "Learner pool",
  "basinKind.paddling": "Paddling pool",
  "basinKind.multi_purpose": "Multi-purpose pool",
  "basinKind.thermal": "Thermal pool",
  "basinKind.outdoor": "Outdoor pool",
  "basinKind.unknown": "{kind}",

  "feature.fact.surcharge": "Surcharge",
  "feature.fact.temperature": "Temperature",
  "feature.fact.hours": "Hours on this date",
  "feature.hoursNotListed": "Hours not listed for this date",
  "feature.closed": "Closed — {reason}",
  // Lower-case clauses, because they are read INSIDE `feature.closed` above. They are the
  // one place this catalog nests, and they are worded as fragments on purpose.
  "closureClause.out_of_season": "outside its season",
  "closureClause.no_sessions": "no hours published for this date",
  "closureClause.closure": "the pool states a closure",
  "closureClause.unknown": "{reason}",
  "featureKind.sauna": "Sauna",
  "featureKind.gastronomy": "Restaurant or kiosk",
  "featureKind.sunbathing": "Sunbathing lawn",
  "featureKind.playground": "Playground",
  "featureKind.slide": "Water slide",
  "featureKind.wellness": "Wellness area",
  "featureKind.sport": "Sports facility",
  "featureKind.unknown": "{kind}",

  "lockerKind.wardrobe": "Wardrobe locker",
  "lockerKind.valuables": "Valuables locker",
  "lockerKind.cabin": "Changing cabin",
  "lockerKind.unknown": "{kind}",
  "rentalKind.towel": "Towel",
  "rentalKind.locker": "Locker",
  "rentalKind.deck_chair": "Deck chair",
  "rentalKind.swim_aid": "Swimming aid",
  "rentalKind.unknown": "{kind}",
  "fee.free": "Free",
  "fee.unstated": "Price not published",
  "fee.amount": "{amount}",
  "fee.perPeriod": "per {period}",
  "fee.deposit": "deposit {amount}",

  "panel.bestWindow": {
    one: "{start}–{end}, {count} lane",
    other: "{start}–{end}, {count} lanes",
  },
  // NOT a plural entry: the string names the lanes ("lane 3", "lanes 3, 4") without
  // counting them, and `xcstringstool` refuses a plural variation whose forms do not
  // interpolate the number — its own advice is "use separate top-level strings for one
  // and greater than one". No language here needs more than the two, because the noun
  // has no numeral in front of it.
  "panel.clubSlot.oneLane": "{start}–{end}, lane {lanes}",
  "panel.clubSlot.manyLanes": "{start}–{end}, lanes {lanes}",
  "prov.fact.readFrom": "Read from",
  "prov.fact.accurateAsOf": "Accurate as of",
  "prov.fact.curation": "Curation",
  "prov.curated.yes": "Hand-checked",
  "prov.curated.no": "Read straight from the pool’s own page",

  // --- Lane plans -------------------------------------------------------------------
  "lane.incompleteCaveat":
    "Some lanes could not be read from the pool’s plan, so this is incomplete.",
  // Zero public lanes is NOT "0 of 8 open", which reads as a measurement. Each of the four
  // is a WHOLE sentence: the partial variants exist so no language has to glue "— some
  // lanes unreadable" onto the end of another sentence.
  "lane.nonePublic": "no lanes open to the public",
  "lane.nonePublic.partial":
    "no lanes open to the public — some lanes unreadable",
  "lane.publicOfTotal": {
    one: "{public} of {count} lane open",
    other: "{public} of {count} lanes open",
  },
  "lane.publicOfTotal.partial": {
    one: "{public} of {count} lane open — some lanes unreadable",
    other: "{public} of {count} lanes open — some lanes unreadable",
  },
  "lane.openToPublic": "open to the public",
  "lane.spoken": "Lane {lane}, {start} to {end}, {holder}",

  // --- VoiceOver over the ribbon canvas ---------------------------------------------
  //
  // `Canvas` offers no per-element accessibility, so these ARE the ribbon for a screen
  // reader. Day-agnostic without exception: a ribbon is painted for whichever day the
  // strip selects, so "today" here would be spoken on ninety-odd future dates.
  "a11y.blockLabel": "{start} to {end}, {access}",
  "a11y.fact.publicLanes": "Lanes open to the public",
  "a11y.value.ofTotal": "{public} of {total}",
  "a11y.fact.laneData": "Lane data",
  "a11y.value.laneDataIncomplete": "incomplete for this basin",
  "a11y.fact.lanes": "Lanes",
  "a11y.fact.reservedBy": "Reserved by",
  "a11y.value.ownerAndOthers": "{owner} and others",
  "a11y.fact.laneSplit": "Lane split",
  "a11y.value.laneSplitUnpublished": "not published for this pool",
  "a11y.selected": "Selected",

  // --- Phone chrome -----------------------------------------------------------------
  "map.poolsHere": {
    one: "{count} pool here",
    other: "{count} pools here",
  },
  "nav.map": "Map",
  "nav.list": "List",
  "action.directions": "Directions",
  "action.call": "Call",
  "action.openInMaps": "Open in Maps",
  "nav.allPools": "All pools",
  "nav.accessTypes": "What the labels mean",
  "nav.browse": "Browse",
  "nav.findAPool": "Find a pool",
  "accessTypes.title": "Session types",
  "accessTypes.footer":
    "A session’s own rules always win: what a pool publishes for a particular hour is what this app shows, and these are the categories it sorts them into.",
  "browser.noMatch.body": "Try a different name, or another kind.",
  "browser.filterByKind": "Filter by kind",
  "browser.kind": "Kind",
  "browser.allKinds": "All kinds",
  "gantt.title": "Lanes, hour by hour",
  "error.store.title": "Cannot read the pool data",
  "error.store.body":
    "The bundled pool data could not be opened, so there is nothing to show. Reinstalling the app restores it.",
  "state.none.body.phone":
    "Try a wider area, another day, or fewer filters. This is not the same as everything being closed.",
  "meta.dataFrom": "Data from",
  "meta.answersThrough": "Answers through",
  "meta.offlineNote":
    "Works offline. Everything here was resolved before the app shipped.",
  "action.favourite": "Favourite",
  "action.unfavourite": "Unfavourite",
  "action.showLanePlan": "Show the lane plan",
  "action.hideLanePlan": "Hide the lane plan",
  "action.done": "Done",
  "session.fairWeather.badge": "Fair weather only",
  "filter.none": "No filters",
  "filter.section.who": "Who",
  "filter.section.where": "Where",
  "filter.section.what": "What",
  "filter.eligibleOnly": "Open to me only",
  "filter.eligibleOnly.toggle": "Only sessions open to me",
  "filter.favourites": "Favourites",
  "filter.favouritesOnly.toggle": "Only my favourites",
  "filter.measureFrom": "Measure from",
  "filter.within": "Within",
  "filter.anyDistance": "Any distance",
  "filter.poolKinds": "Pool kinds",
  "filter.allKinds": "All",
  "place.anywhere": "Anywhere",
  "place.searchPrompt": "Search places",
  "place.hb": "Zürich HB (main station)",
} as const;
