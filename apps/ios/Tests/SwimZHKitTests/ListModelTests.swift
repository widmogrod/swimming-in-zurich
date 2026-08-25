// The primary screen, as a value — filters, tiers, order, verdicts, favourites.
//
// Every assertion here is about a decision the VIEW must not be allowed to make. The app
// target is outside the CRAP gate and a SwiftUI body cannot be unit-tested at all, so a rule
// that drifted into a `body` would be a rule nothing measures — which is exactly what this
// file exists to prevent, one predicate at a time.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The day list model")
struct ListModelTests {
  /// The English renderer. Most assertions here are about a SENTENCE a swimmer reads, and
  /// reading one language keeps them legible; the ones that are about a RULE ("no off-today row
  /// claims a moment", "only `closed` says closed") run over all five, because the catalog is
  /// now where those rules are easiest to break.
  static let en = CatalogFixture.english

  /// The English rendering of an optional message — `try? #require` hands back optionals here,
  /// and unwrapping each one at the assertion site would drown the sentence being asserted.
  static func said(_ message: Message?) -> String? { message.map { en($0) } }

  static func said(_ wording: Wording?) -> String? { wording.map { en($0) } }

  static let horizon = StoreMetadata(
    schemaVersion: 1,
    builtAt: "2026-08-24T00:00:00+02:00",
    horizonStart: "2026-08-23",
    horizonEnd: "2027-01-09",
    goldValidAsOf: "2026-08-24",
    contentHash: "deadbeef"
  )
  static let noon = TimeOfDay(hour: 12, minute: 0)

  static func option(
    pool: String,
    name: String? = nil,
    kind: String = "indoor",
    from: Int,
    to: Int,
    access: SessionAccess = .publicSwim,
    distanceKm: Double? = 1.0,
    person: Person = Person()
  ) -> SwimOption {
    let window = TimeWindow(
      start: TimeOfDay(hour: from, minute: 0), end: TimeOfDay(hour: to, minute: 0))
    return SwimOption(
      poolID: pool,
      poolName: name ?? pool,
      poolKind: kind,
      basinID: "\(pool)-b",
      basinName: "Hauptbecken",
      lengthM: 25,
      lanes: 6,
      window: window,
      access: access,
      weather: "any",
      eligibility: eligibility(person, access),
      openAtQueryTime: window.contains(noon),
      price: nil,
      distanceKm: distanceKm
    )
  }

  static func status(
    pool: String,
    name: String? = nil,
    kind: String = "indoor",
    status: String,
    closure: String? = nil,
    distanceKm: Double? = 2.0
  ) -> PoolDayStatus {
    PoolDayStatus(
      poolID: pool,
      poolName: name ?? pool,
      poolKind: kind,
      status: status,
      detailCode: "d",
      closureCode: closure,
      detailParams: [:],
      distanceKm: distanceKm
    )
  }

  static func answer(
    options: [SwimOption] = [],
    statuses: [PoolDayStatus] = [],
    day: String = "2026-08-24"
  ) -> Answer {
    Answer(day: day, options: options, statuses: statuses, notices: [], warnings: [])
  }

  /// By default the answer's own day IS today, so the wall-clock tiers are exercised. The
  /// off-today behaviour is driven explicitly by `today:`, which is the whole of B1.
  static func model(
    _ answer: Answer,
    filters: Filters? = nil,
    favourites: Favourites = Favourites(),
    today: String? = nil,
    at time: TimeOfDay = noon
  ) -> ListModel {
    listModel(
      answer: answer,
      filters: filters ?? Filters(day: answer.day),
      favourites: favourites,
      horizon: horizon,
      today: today ?? answer.day,
      at: time,
      // Only the VALUES a message interpolates depend on this, and none of the assertions here
      // is about a number's shape — `Format`'s own regional rules are pinned in its own suite.
      format: en.format
    )
  }

  // MARK: - Tiers

  @Test("a running session is `now`, a later one `soon`, a finished day `past`")
  func tiersFollowTheClock() {
    let built = Self.model(
      Self.answer(options: [
        Self.option(pool: "running", from: 11, to: 13),
        Self.option(pool: "later", from: 18, to: 21),
        Self.option(pool: "over", from: 6, to: 9),
      ])
    )
    let tiers = Dictionary(
      uniqueKeysWithValues: built.sections.flatMap(\.rows).map { ($0.poolID, $0.tier) })
    #expect(tiers["running"] == .now)
    #expect(tiers["later"] == .soon)
    #expect(tiers["over"] == .past)
  }

  @Test("a pool whose sessions are over is `past`, and NEVER worded closed")
  func aFinishedDayIsNotAClosure() {
    // The web files this case under its "Closed" tier. Here it is its own, because a pool that
    // opened at 06:00 and shut at 09:00 was not CLOSED in the sense the data means — and the
    // one thing this screen may never do is say "closed" where the source did not.
    let built = Self.model(Self.answer(options: [Self.option(pool: "over", from: 6, to: 9)]))
    let row = try? #require(built.sections.first?.rows.first)
    #expect(row?.tier == .past)
    #expect(Self.said(row?.verdict.head) == "Done for today")
    #expect(Self.en(Tier.past.title).lowercased().contains("closed") == false)
  }

  @Test("the ghost states land in `unknown`, a real closure in `closed`")
  func ghostStatesAreNotClosures() {
    let built = Self.model(
      Self.answer(statuses: [
        Self.status(pool: "a", status: "awaiting_scrape"),
        Self.status(pool: "b", status: "no_source"),
        Self.status(pool: "c", status: "open_unscheduled"),
        Self.status(pool: "d", status: "closed", closure: "out_of_season"),
      ])
    )
    let tiers = Dictionary(
      uniqueKeysWithValues: built.sections.flatMap(\.rows).map { ($0.poolID, $0.tier) })
    #expect(tiers["a"] == .unknown)
    #expect(tiers["b"] == .unknown)
    #expect(tiers["c"] == .unknown)
    #expect(tiers["d"] == .closed)
    // ...and no ghost row is marked ✕. Nobody was excluded from anything.
    for row in built.sections.flatMap(\.rows) {
      #expect(row.mark == .check)
      #expect(row.state != nil)
      #expect(row.options.isEmpty)
    }
  }

  @Test("sections come in display order and empty ones are absent")
  func sectionsAreOrdered() {
    let built = Self.model(
      Self.answer(
        options: [Self.option(pool: "n", from: 11, to: 13)],
        statuses: [Self.status(pool: "c", status: "closed", closure: "no_sessions")]
      )
    )
    #expect(built.sections.map(\.tier) == [.now, .closed])
    #expect(built.sections.map { Self.en($0.title) } == ["Swim now", "Closed"])
  }

  // MARK: - The wall clock may only speak about today

  @Test("a day that is not today makes NO present-tense claim, at any hour")
  func theClockNeverLeaksAcrossDays() {
    // The bug this pins: the day strip spans ~400 days, so the selected day is usually not the
    // one the user is standing in. Tiering it by the wall clock put a 06:00–09:00 session four
    // months out into "Open now · until 09:00" at 07:30, and declared every future day already
    // over at 22:00 — a present-tense claim about a date nobody is in. The second is the same
    // family of harm as a false "closed": a false "done".
    let future = Self.answer(
      options: [
        Self.option(pool: "morning", from: 6, to: 9),
        Self.option(pool: "evening", from: 18, to: 21),
      ],
      day: "2026-12-20"
    )
    for hour in [7, 12, 19, 22] {
      let built = Self.model(
        future, today: "2026-08-24", at: TimeOfDay(hour: hour, minute: 30))
      #expect(!built.isToday)
      let rows = built.sections.flatMap(\.rows)
      #expect(rows.count == 2)
      for row in rows {
        #expect(row.tier == .scheduled, "at \(hour):30 a future day tiered as \(row.tier)")
        #expect(!row.tier.isWallClockClaim)
        let head = Self.en(row.verdict.head)
        #expect(head != "Open now", "at \(hour):30: \(head)")
        #expect(head != "Not open to you")
        #expect(head != "Done for today")
        #expect(!row.openToYou)
      }
      // ...and the headline changes tense with the day, because the count does.
      #expect(built.openToYouCount == 0)
      #expect(built.scheduledPoolCount == 2)
      #expect(Self.en(built.headline) == "2 pools with sessions")
    }
  }

  @Test("the same answer, on the same day, DOES use the clock")
  func todayStillTiersByTheClock() {
    // The other half: `today` must not have disabled the feature it guards.
    let answer = Self.answer(options: [Self.option(pool: "p", from: 11, to: 13)], day: "2026-08-24")
    let built = Self.model(answer, today: "2026-08-24", at: TimeOfDay(hour: 12, minute: 0))
    #expect(built.isToday)
    #expect(built.sections[0].rows[0].tier == .now)
    #expect(Self.en(built.sections[0].rows[0].verdict.head) == "Open now")
    // "…now" is the catalog's own wording for `mobile.openToYou`, which the phone now shares
    // with the web rather than keeping a second English sentence of its own. The tense is the
    // point either way: this line may only ever be said about today.
    #expect(Self.en(built.headline) == "1 open to you now")
  }

  @Test("an off-today verdict states the day's own hours")
  func scheduledVerdictSpansTheDay() {
    let answer = Self.answer(
      options: [
        // An EARLY session that runs LATER than the last one to start — so a verdict built from
        // `options.last` rather than from the maximum end would understate the day.
        Self.option(pool: "p", from: 6, to: 22),
        Self.option(pool: "p", from: 18, to: 21),
      ],
      day: "2026-12-20"
    )
    let row = Self.model(answer, today: "2026-08-24").sections[0].rows.first
    #expect(Self.said(row?.verdict.head) == "Opens 06:00")
    #expect(Self.said(row?.verdict.tail ?? nil) == "until 22:00")
  }

  @Test("the fixed off-today moment is the web's own constant")
  func dayMomentMatchesTheWeb() {
    // `apps/web/static/js/api.ts`: `const DAY_MOMENT = "T12:00"`. The two clients ask a
    // non-today date at the same instant, so `open_now` cannot differ between them.
    #expect(dayMoment.hhmm == "12:00")
  }

  // MARK: - Verdicts

  @Test("`Open now` is a claim about THIS person")
  func openNowIsPersonal() {
    // A club-reserved hour is running. The pool is open; it is not open to them, and the
    // difference is a wasted trip.
    let club = Self.option(
      pool: "club", from: 11, to: 13, access: .clubReserved(club: "SC Zürich"))
    let built = Self.model(Self.answer(options: [club]))
    let row = try? #require(built.sections.first?.rows.first)
    #expect(row?.tier == .now)
    #expect(Self.said(row?.verdict.head) == "Not open to you")
    #expect(Self.said(row?.verdict.tail ?? nil) == "until 13:00")
    #expect(row?.openToYou == false)
    #expect(built.openToYouCount == 0)
  }

  @Test("the open-to-you count is over POOLS, not sessions")
  func openToYouCountsPools() {
    let built = Self.model(
      Self.answer(options: [
        Self.option(pool: "two-basins", from: 10, to: 14),
        Self.option(pool: "two-basins", from: 11, to: 13),
        Self.option(pool: "other", from: 11, to: 13),
        Self.option(pool: "later", from: 19, to: 21),
      ])
    )
    #expect(built.openToYouCount == 2)
  }

  @Test("a later session reports when it opens")
  func laterSessionsSayWhen() {
    let built = Self.model(
      Self.answer(options: [
        Self.option(pool: "p", from: 19, to: 21),
        Self.option(pool: "p", from: 17, to: 18),
      ])
    )
    let row = try? #require(built.sections.first?.rows.first)
    // The NEXT one, not the first in the list: the sessions are sorted by start before the
    // verdict is decided, which is what makes "Opens 17:00" the useful sentence.
    #expect(Self.said(row?.verdict.head) == "Opens 17:00")
    #expect(row?.options.map { $0.window.start.hhmm } == ["17:00", "19:00"])
  }

  // MARK: - Filters

  @Test("the kind filter admits everything when it is empty")
  func emptyKindFilterAdmitsAll() {
    let answer = Self.answer(
      options: [Self.option(pool: "in", kind: "indoor", from: 11, to: 13)],
      statuses: [Self.status(pool: "out", kind: "outdoor", status: "no_source")]
    )
    #expect(Self.model(answer).sections.flatMap(\.rows).count == 2)
    let filtered = Self.model(
      answer, filters: Filters(day: answer.day, kinds: ["outdoor"]))
    #expect(filtered.sections.flatMap(\.rows).map(\.poolID) == ["out"])
  }

  @Test("search folds case and diacritics, and reaches ghost rows too")
  func searchFolds() {
    let answer = Self.answer(
      options: [Self.option(pool: "k", name: "Wärmebad Käferberg", from: 11, to: 13)],
      statuses: [Self.status(pool: "o", name: "Freibad Oberer Letten", status: "no_source")]
    )
    // "Zurich" for "Zürich" is the everyday case: the phone keyboard makes the plain vowel
    // far likelier than the umlaut.
    for query in ["kaferberg", "KÄFER", " käferberg "] {
      let built = Self.model(answer, filters: Filters(day: answer.day, search: query))
      #expect(built.sections.flatMap(\.rows).map(\.poolID) == ["k"], "query \(query)")
    }
    let ghost = Self.model(answer, filters: Filters(day: answer.day, search: "letten"))
    #expect(ghost.sections.flatMap(\.rows).map(\.poolID) == ["o"])
  }

  @Test("`eligible only` drops the SESSIONS, and a pool left with none has no row")
  func eligibleOnlyDropsSessions() {
    let answer = Self.answer(
      options: [
        Self.option(pool: "mixed", from: 10, to: 12),
        Self.option(pool: "mixed", from: 12, to: 14, access: .schoolReserved),
        Self.option(pool: "school", from: 11, to: 13, access: .schoolReserved),
      ],
      statuses: [Self.status(pool: "ghost", status: "no_source")]
    )
    let built = Self.model(answer, filters: Filters(day: answer.day, eligibleOnly: true))
    let rows = Dictionary(
      uniqueKeysWithValues: built.sections.flatMap(\.rows).map { ($0.poolID, $0) })
    #expect(rows["mixed"]?.options.count == 1)
    // `school` is GONE — not moved to `closed` and not turned into a ghost. "Nothing here for
    // you" and "we do not know its hours" are different sentences, and turning one into the
    // other is the harm the four-state vocabulary exists to prevent.
    #expect(rows["school"] == nil)
    // ...while a pool whose hours are unknown stays: it was never excluded, only unknown.
    #expect(rows["ghost"] != nil)
  }

  // MARK: - Order and favourites

  @Test("nearest first; an unknown distance sorts LAST, never as zero")
  func unknownDistanceSortsLast() {
    let built = Self.model(
      Self.answer(options: [
        Self.option(pool: "far", from: 11, to: 13, distanceKm: 9),
        Self.option(pool: "unknown", from: 11, to: 13, distanceKm: nil),
        Self.option(pool: "near", from: 11, to: 13, distanceKm: 0.4),
      ])
    )
    #expect(built.sections[0].rows.map(\.poolID) == ["near", "far", "unknown"])
  }

  @Test("equal distances break by name, so the order is total and stable")
  func tiesBreakByName() {
    let built = Self.model(
      Self.answer(options: [
        Self.option(pool: "b", name: "Bravo", from: 11, to: 13, distanceKm: 1),
        Self.option(pool: "a", name: "Alpha", from: 11, to: 13, distanceKm: 1),
      ])
    )
    #expect(built.sections[0].rows.map(\.poolName) == ["Alpha", "Bravo"])
  }

  @Test("favourites sort first within their tier, and can be shown alone")
  func favouritesLead() {
    let answer = Self.answer(options: [
      Self.option(pool: "near", from: 11, to: 13, distanceKm: 0.2),
      Self.option(pool: "loved", from: 11, to: 13, distanceKm: 8),
    ])
    let built = Self.model(answer, favourites: Favourites(["loved"]))
    #expect(built.sections[0].rows.map(\.poolID) == ["loved", "near"])
    #expect(built.sections[0].rows[0].isFavourite)

    let only = Self.model(
      answer, filters: Filters(day: answer.day, favouritesOnly: true),
      favourites: Favourites(["loved"]))
    #expect(only.sections.flatMap(\.rows).map(\.poolID) == ["loved"])
    #expect(only.openToYouCount == 1)
  }

  @Test("favourites round-trip through their stored string, tolerantly")
  func favouritesEncoding() {
    var favourites = Favourites()
    favourites.toggle("b")
    favourites.toggle("a")
    #expect(favourites.encoded == "a\nb")
    favourites.toggle("a")
    #expect(favourites.encoded == "b")
    #expect(Favourites.decode("a\nb").ids == ["a", "b"])
    // A string an older version wrote must cost at most one favourite, never the whole list.
    #expect(Favourites.decode("  a  \n\n\n b ").ids == ["a", "b"])
    #expect(Favourites.decode("").ids.isEmpty)
  }

  // MARK: - The horizon

  @Test("past the horizon the whole screen says so — and shows no rows at all")
  func beyondHorizonIsWholeScreen() {
    let built = Self.model(
      Self.answer(
        options: [Self.option(pool: "p", from: 11, to: 13)],
        statuses: [Self.status(pool: "c", status: "closed", closure: "no_sessions")],
        day: "2027-06-01"
      )
    )
    #expect(built.beyondHorizon)
    #expect(built.sections.isEmpty)
    #expect(built.openToYouCount == 0)
    // The headline states the HORIZON, not a false zero: past `horizon_end` both counts are
    // structurally zero, so "0 pools with sessions" would read as an answer we do not have.
    #expect(built.headline == dayStateLabel(.beyondHorizon))
    // In every language, and as "no number at all" rather than "not the character 0": the harm
    // is a COUNT beside a screen that correctly says we have not resolved this day yet, and a
    // catalog that reached for the plural headline would produce one in whatever digits it
    // liked.
    for (language, localized) in CatalogFixture.all {
      let said = localized(built.headline)
      #expect(!said.isEmpty, "\(language)")
      #expect(said.allSatisfy { !$0.isNumber }, "\(language) headlines a count: \(said)")
    }
    // Emphatically not a per-pool closure: E2 is about the DATE.
    #expect(built.isEmpty)
  }

  // MARK: - Filter state

  @Test("the summary shows only what the user actually chose")
  func summaryTagsOmitDefaults() {
    var filters = Filters(day: "2026-08-24", place: nil)
    #expect(filters.summaryTags.isEmpty)
    filters.place = Places.default
    filters.gender = .female
    filters.age = 34
    filters.eligibleOnly = true
    #expect(
      filters.summaryTags.map { Self.en($0) }
        == ["Zürich HB (main station)", "Female", "Adult", "Open to me only"])
  }

  @Test("every summary tag the bar can show is reachable")
  func summaryTagsCoverEveryControl() {
    var filters = Filters(day: "2026-08-24", place: nil)
    filters.favouritesOnly = true
    filters.kinds = ["indoor", "outdoor"]
    // One tag per kind, and each is the kind's own SENTENCE. They used to be the export's raw
    // tokens joined with a comma ("indoor, outdoor") — a domain token on screen, which S4 would
    // have carried into five catalogs as an untranslated one.
    #expect(
      filters.summaryTags.map { Self.en($0) } == ["Favourites", "Indoor pool", "Outdoor pool"])
  }

  @Test("the filter button fills for every control that narrows, and for nothing else")
  func isNarrowedCoversEveryControl() {
    // The filled glyph is the ONLY evidence a reader has that the list is showing less than
    // everything — the controls themselves are behind a sheet. So each branch is named here:
    // an untested predicate would have failed open (always filled) or shut (never), and both
    // read as "this control does nothing".
    let none = Filters(day: "2026-08-24", place: nil)
    #expect(!none.isNarrowed)

    for narrow in [
      { (f: inout Filters) in f.gender = .female },
      { (f: inout Filters) in f.age = 34 },
      { (f: inout Filters) in f.eligibleOnly = true },
      { (f: inout Filters) in f.kinds = ["indoor"] },
      { (f: inout Filters) in f.place = Places.default },
      { (f: inout Filters) in f.radiusKm = 2 },
      { (f: inout Filters) in f.favouritesOnly = true },
    ] {
      var filters = none
      narrow(&filters)
      #expect(filters.isNarrowed)
    }

    // ...and the two that are deliberately NOT narrowings. Every answer is about some day, so
    // counting the day would leave the control filled forever; and while you are typing, the
    // search field on screen is its own evidence.
    var dated = none
    dated.day = "2026-12-24"
    #expect(!dated.isNarrowed)
    var searched = none
    searched.search = "letzi"
    #expect(!searched.isNarrowed)
  }

  @Test("the six section titles are distinct, and only `closed` says closed")
  func tierTitlesAreDistinctAndHonest() {
    #expect(Tier.allCases == [.now, .soon, .past, .scheduled, .unknown, .closed])
    #expect(Self.en(Tier.closed.title) == "Closed")
    // Both halves hold PER LANGUAGE. Two tiers that collapse to one German heading are
    // indistinguishable to a German reader however different their English is; and a
    // translator handed "Hours not listed" out of context can reasonably reach for
    // "Geschlossen", which is the one word this screen may never say where the source did not.
    //
    // The shut-word lists are `DayStateTests`' own: there is one answer per language to "how
    // does this language say a pool is shut", and a second copy would drift from it.
    for (language, localized) in CatalogFixture.all {
      let titles = Tier.allCases.map { localized($0.title) }
      #expect(Set(titles).count == titles.count, "\(language): two tiers share a heading")
      #expect(titles.allSatisfy { !$0.isEmpty })
      let shut = DayStateTests.shutWords[language] ?? []
      #expect(!shut.isEmpty, "no shut-word list for \(language)")
      for tier in Tier.allCases where tier != .closed {
        let said = localized(tier.title)
        let folded = said.folding(
          options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        for word in shut {
          #expect(!folded.contains(word), "\(language): \(tier) is headed \"\(said)\"")
        }
      }
    }
    // Exactly the three clock tiers make a present-tense claim. If a fourth ever did, the
    // off-today guard in `listModel` would have a hole this assertion closes.
    #expect(Tier.allCases.filter(\.isWallClockClaim) == [.now, .soon, .past])
  }

  // MARK: - Rules that a view must not own

  @Test("the inline-session cap and its remainder come from the model")
  func inlineSessionsAreDecidedHere() {
    // A threshold that governs what a swimmer sees. In a view body it was a `prefix(3)` and a
    // `count - 3` — the same number written twice, tested by nothing.
    #expect(inlineSessionLimit == 3)
    let many = (0..<7).map { Self.option(pool: "p", from: 6 + $0, to: 7 + $0) }
    let row = Self.model(Self.answer(options: many)).sections[0].rows.first
    #expect(row?.options.count == 7)
    #expect(row?.inlineOptions.count == inlineSessionLimit)
    #expect(row?.hiddenSessionCount == 4)
    #expect(Self.said(row?.moreSessionsLabel ?? nil) == "+4 more today")
    // The inline ones are the FIRST by start, so the row leads with the day's earliest.
    #expect(row?.inlineOptions.first?.window.start.hhmm == "06:00")

    // A short day hides nothing, and the count never goes negative: "+0 more today" would be
    // worse than saying nothing.
    let few = Self.model(Self.answer(options: [Self.option(pool: "q", from: 11, to: 13)]))
    let short = few.sections[0].rows.first
    #expect(short?.hiddenSessionCount == 0)
    #expect(short?.inlineOptions.count == 1)
    #expect(short?.moreSessionsLabel == nil, "\"+0 more\" is worse than saying nothing")
  }

  @Test("the more-sessions phrase says `today` ONLY on today")
  func moreSessionsPhraseIsNotTemporalOffToday() {
    // The last off-today temporal claim the app could still make: a pool with five sessions on a
    // date four months out said "Opens 06:00 · until 22:00" and, two lines below, "+2 more
    // TODAY". The wording turns on `isToday`, which a row does not carry — so it is decided
    // here, not branched on in a view.
    let format = Self.en.format
    #expect(
      Self.said(moreSessionsLabel(hidden: 2, isToday: true, format: format)) == "+2 more today")
    #expect(
      Self.said(moreSessionsLabel(hidden: 2, isToday: false, format: format)) == "+2 more that day")
    #expect(moreSessionsLabel(hidden: 0, isToday: true, format: format) == nil)
    #expect(moreSessionsLabel(hidden: 0, isToday: false, format: format) == nil)

    // ...and through the whole model, which is where it actually reached a screen.
    let many = (0..<5).map { Self.option(pool: "p", from: 6 + $0, to: 7 + $0) }
    let future = Self.model(
      Self.answer(options: many, day: "2026-12-20"), today: "2026-08-24")
    let row = future.sections[0].rows.first
    #expect(row?.hiddenSessionCount == 2)
    #expect(Self.said(row?.moreSessionsLabel ?? nil) == "+2 more that day")

    // No row anywhere in an off-today model may claim a moment — IN ANY OF THE FIVE LANGUAGES.
    // The English sentences were written with this rule in mind and the translations were not
    // written by whoever wrote the rule: "+2 weitere heute" is the natural German for the
    // more-sessions line and is exactly wrong on a date nobody is standing in.
    //
    // The temporal-word lists are `DayStateTests`' own, for the same reason its shut-words are:
    // one answer per language, in one place.
    for (language, localized) in CatalogFixture.all {
      let temporal = DayStateTests.temporalWords[language] ?? []
      #expect(!temporal.isEmpty, "no temporal-word list for \(language)")
      for row in future.sections.flatMap(\.rows) {
        let lines = [row.verdict.head, row.verdict.tail, row.moreSessionsLabel]
          .compactMap { $0 }
          .map { localized($0) }
        for said in lines {
          let folded = said.folding(
            options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
          for word in temporal {
            #expect(!folded.contains(word), "\(language): off-today row says \"\(said)\"")
          }
        }
      }
    }
  }

  @Test("the fair-weather token lives here, not in a view body")
  func fairWeatherIsARule() {
    // The web keeps the same constant in its MEASURED module. Compared inside a `body`, a change
    // to the export's spelling would make the badge vanish with every gate still green.
    #expect(fairOnlyWeather == "fair_only")
    var fair = Self.option(pool: "p", from: 9, to: 14)
    fair = SwimOption(
      poolID: fair.poolID, poolName: fair.poolName, poolKind: fair.poolKind,
      basinID: fair.basinID, basinName: fair.basinName, lengthM: fair.lengthM, lanes: fair.lanes,
      window: fair.window, access: fair.access, weather: fairOnlyWeather,
      eligibility: fair.eligibility, openAtQueryTime: fair.openAtQueryTime, price: fair.price,
      distanceKm: fair.distanceKm)
    #expect(fair.isFairWeatherOnly)
    #expect(!Self.option(pool: "p", from: 9, to: 14).isFairWeatherOnly)
  }

  @Test("the radius value domain is pinned, and excludes the no-limit case")
  func radiusOptionsArePinned() {
    #expect(RadiusOption.all == [1, 2, 5, 10])
    #expect(RadiusOption.all == RadiusOption.all.sorted())
    // `nil` — no radius at all — is deliberately NOT a member: it is the ABSENCE of a limit,
    // and with it a pool that publishes no coordinates is still listed.
    #expect(!RadiusOption.all.contains(0))
  }

  @Test("an absent gender or age stays absent in the person")
  func personKeepsUnknownsUnknown() {
    // A defaulted adult male would be a fabricated answer: `eligibility` says "check with the
    // pool" for what it was not told, and that is the honest verdict.
    let filters = Filters(day: "2026-08-24")
    #expect(filters.person.gender == nil)
    #expect(filters.person.age == nil)
    #expect(eligibility(filters.person, .womenOnly(note: "")).code == .womenOnlyNeedsGender)
  }

  @Test("age bands carry the same representative ages the web offers")
  func ageBandsMatchTheWeb() {
    #expect(AgeBand.all.map(\.age) == [nil, 8, 16, 34, 70])
    #expect(Self.en(AgeBand.band(for: nil).label) == "Any age")
    #expect(Self.en(AgeBand.band(for: 8).label) == "Child")
    #expect(Self.en(AgeBand.band(for: 20).label) == "Teen")
    #expect(Self.en(AgeBand.band(for: 70).label) == "Senior")
    #expect(Self.en(AgeBand.band(for: 99).label) == "Senior")
    // Below every band's representative age: still a child, never "unknown".
    #expect(Self.en(AgeBand.band(for: 3).label) == "Child")
  }

  @Test("the place presets are the web's, and the typeahead folds diacritics")
  func placesMatchTheWeb() {
    #expect(Places.default.id == "hb")
    #expect(Places.matching("", in: Self.en).count == 3)
    // Both Zürich names match the plain-vowel spelling, which is the whole point of folding.
    #expect(Places.matching("zurich", in: Self.en).map(\.id) == ["hb", "zuerichhorn"])
    #expect(Places.matching("BELLE", in: Self.en).map(\.id) == ["bellevue"])
    #expect(Places.matching("nowhere", in: Self.en).isEmpty)
    // The typeahead matches the RENDERED label, which is why it takes a renderer at all: a
    // French reader types "gare", a German "Hauptbahnhof", and matching the key or the English
    // would silently fail for four of the five languages.
    #expect(Places.matching("gare", in: CatalogFixture.localized(.fr)).map(\.id) == ["hb"])
    #expect(Places.matching("hauptbahnhof", in: CatalogFixture.localized(.de)).map(\.id) == ["hb"])
    // ...and every language can still find the two proper nouns, which are never translated.
    for (language, localized) in CatalogFixture.all {
      #expect(Places.matching("", in: localized).count == 3, "\(language)")
      #expect(Places.matching("bellevue", in: localized).map(\.id) == ["bellevue"], "\(language)")
    }
  }

  // MARK: - No machine value reaches a reader (the other half of the sheet's sweep)

  @Test("nothing the LIST screen says shows a raw store date, in any language")
  func theListScreenShowsNoMachineDates() async throws {
    // The sheet has the same sweep (`FacilityDetailTests.everyStoreDateIsFormatted`), and this
    // is the rest of the surface: section titles, row verdicts, the "+2 more" line, every
    // banner, the headline, and the VoiceOver layout over the ribbon canvas — which is the one
    // a raw value could hide in longest, because nobody looks at it.
    //
    // Driven from the COMMITTED STORE rather than from constructed rows, because the values
    // that turn out to be machine dates are the ones a fixture would not have thought to
    // include: `meta.gold_valid_as_of` was live on all 57 pools.
    //
    // EVERY DAY IN THE HORIZON, not a sample. The first version of this test sampled three
    // days and passed — and the store's one `holiday_hours_unverified` warning falls on
    // 2026-12-25, three days past the last sample, carrying `date` as a raw ISO string. A
    // sample is a guess about where the bug is; a sweep is not. The cost is one indexed read
    // per day, which is what makes the sweep affordable at all.
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    var checked = 0
    var banners = 0
    let days = ZurichClock.days(from: metadata.horizonStart, through: metadata.horizonEnd)
    for (language, localized) in CatalogFixture.all {
      for day in days where metadata.covers(day: day) {
        let answer = try await store.answer(
          onDay: day, at: TimeOfDay(hour: 12, minute: 0), for: Person(age: 30))
        let model = listModel(
          answer: answer, filters: Filters(day: day), favourites: Favourites(),
          horizon: metadata, today: metadata.horizonStart, at: TimeOfDay(hour: 12, minute: 0),
          format: localized.format)

        var said: [String] = [localized(model.headline)]
        for banner in model.banners {
          banners += 1
          // A NOTICE is the pool's own sentence and may legitimately quote a date the way the
          // pool wrote it; only our own warnings are ours to format.
          guard banner.kind == .warning else { continue }
          said += [localized(banner.title), localized(banner.text)]
        }
        for section in model.sections {
          said.append(localized(section.title))
          for row in section.rows {
            said.append(localized(row.verdict.head))
            if let tail = row.verdict.tail { said.append(localized(tail)) }
            if let more = row.moreSessionsLabel { said.append(localized(more)) }
            for option in row.options {
              if let lanes = option.laneSummary(isToday: false, format: localized.format) {
                said.append(localized(lanes))
              }
            }
            for block in a11yBlocks(for: dayRibbon(for: row), width: 300, in: localized) {
              said.append(localized(block.label))
              for fact in block.customContent {
                said += [localized(fact.label), localized(fact.value)]
              }
            }
          }
        }
        for text in said {
          checked += 1
          if FacilityDetailTests.looksLikeAStoreDate(text) {
            Issue.record("\(language)/\(day) shows a raw date: \"\(text)\"")
          }
        }
      }
    }
    #expect(checked > 2000, "the sweep read \(checked) strings — it is scanning nothing")
    // ...and it really reached the banner path, which is the one that carries a `{date}` param.
    // A floor of FIVE, one per language: the store carries exactly one holiday warning and one
    // calendar-coverage warning, so a sweep that saw fewer has narrowed somewhere.
    #expect(banners >= 5, "only \(banners) banners in the sweep — the `{date}` param went unread")
  }
}
