// The all-pools browser's two rules.
//
// They are small, and that is exactly why they are here rather than inside the view: the search
// predicate must be the SAME one the find screen uses, and the kind list must come from the
// roster rather than from a day's answer. Both equalities are invisible in a `body` and
// checkable in a function.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The all-pools browser")
struct PoolBrowserTests {
  /// The English renderer. The two label assertions below are about a SENTENCE, so they keep
  /// asserting the sentence; the RULES ("a kind is never folded into another", "no freshness
  /// state reads as closed") run over all five languages, because a catalog is where they are
  /// now easiest to break.
  static let en = CatalogFixture.english

  static func pool(_ id: String, _ name: String, _ kind: String) -> PoolRecord {
    PoolRecord(
      id: id, name: name, kind: kind, address: nil, geo: nil, url: nil, freshness: "scraped",
      admission: .unknown)
  }

  static let roster = [
    pool("a", "Hallenbad Bläsi", "indoor"),
    pool("b", "Freibad Letzigraben", "outdoor"),
    pool("c", "Seebad Utoquai", "lake"),
    pool("d", "Hallenbad City", "indoor"),
  ]

  @Test("no kind filter means every kind — the ABSENCE of a filter, not a kind called `all`")
  func noKindMeansEveryKind() {
    #expect(browsePools(Self.roster, kind: nil, search: "").count == Self.roster.count)
    #expect(browsePools(Self.roster, kind: "indoor", search: "").map(\.id) == ["a", "d"])
    // A kind nothing carries yields nothing — never everything, which a `nil`-ish fallback
    // would have produced.
    #expect(browsePools(Self.roster, kind: "river", search: "").isEmpty)
  }

  @Test("search is the SAME predicate the find screen uses")
  func searchMatchesTheFindScreen() {
    // Diacritic- and case-insensitive, because that is what `matchesSearch` promises and what
    // the list screen already does. A query that finds a pool on one screen must find it on
    // the other.
    #expect(browsePools(Self.roster, kind: nil, search: "blasi").map(\.id) == ["a"])
    #expect(browsePools(Self.roster, kind: nil, search: "HALLENBAD").map(\.id) == ["a", "d"])
    // Whitespace only is no filter at all.
    #expect(browsePools(Self.roster, kind: nil, search: "   ").count == Self.roster.count)
  }

  @Test("the two filters compose, and the order is stable")
  func filtersComposeAndOrderIsStable() {
    #expect(browsePools(Self.roster, kind: "indoor", search: "city").map(\.id) == ["d"])
    // Name order, so the list does not reshuffle under the user's thumb between rebuilds.
    #expect(
      browsePools(Self.roster, kind: nil, search: "").map(\.name)
        == Self.roster.map(\.name).sorted())
  }

  @Test("the kind list comes from the roster, in a stable order")
  func kindsComeFromTheRoster() {
    #expect(poolKinds(Self.roster) == ["indoor", "lake", "outdoor"])
    #expect(poolKinds([]).isEmpty)
  }

  @Test("a kind this binary has never seen is shown as itself, never folded into another")
  func unknownKindIsShownAsItself() {
    // The store can be newer than the app, and a mislabelled pool sends somebody to the wrong
    // kind of water.
    #expect(Self.en(poolKindLabel("indoor")) == "Indoor pool")
    #expect(Self.en(poolKindLabel("wave_park")) == "Wave Park")
    // In EVERY language: the unknown token is DATA, so it rides through `poolKind.unknown`
    // unchanged, and it may never pick up the words of a kind we do know. A catalog that gave
    // `poolKind.unknown` a body of its own ("Hallenbad %@") would fold the store's newer kind
    // into ours in four languages while English stayed innocent.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(poolKindLabel("wave_park")) == "Wave Park", "\(language)")
      let known = ["indoor", "outdoor", "lake", "river", "thermal", "school", "paddling"]
        .map { localized(poolKindLabel($0)) }
      #expect(!known.contains("Wave Park"), "\(language) renders a known kind as the unknown one")
    }
  }

  @Test("the browser sees every pool the store has, including the ones with no schedule")
  func browserSeesTheWholeRoster() async throws {
    // The point of the screen: a pool absent from today's answer — no schedule, out of radius,
    // wrong kind — is still a pool, and this is where it is still findable.
    let store = try Store.bundled()
    let pools = try await store.pools()
    #expect(pools.count >= 50, "the roster is \(pools.count) pools")
    #expect(browsePools(pools, kind: nil, search: "").count == pools.count)
    // And every freshness state in the store has a sentence, none of which says "closed" —
    // IN ANY OF THE FIVE LANGUAGES. "No timetable to read" is the sentence a translator is
    // likeliest to shorten to "geschlossen", and it is the one state where that is a lie:
    // a pool that publishes no timetable may well be open right now.
    //
    // The shut-word lists are `DayStateTests`' own, deliberately: there is one answer per
    // language to "how does this language say a pool is shut", and two copies would drift.
    for (language, localized) in CatalogFixture.all {
      let shut = DayStateTests.shutWords[language] ?? []
      #expect(!shut.isEmpty, "no shut-word list for \(language)")
      for freshness in Set(pools.map(\.freshness)) {
        let message = freshnessLabel(freshness)
        let said = localized(message)
        #expect(!said.isEmpty)
        #expect(said != message.key, "\(language) has no sentence for \(freshness)")
        let folded = said.folding(
          options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        for word in shut {
          #expect(!folded.contains(word), "\(language)/\(freshness) reads as \"\(said)\"")
        }
      }
    }
  }
}
