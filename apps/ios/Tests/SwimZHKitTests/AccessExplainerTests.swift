// The access-types legend, held to the domain's own words.
//
// `Fixtures/access_types.json` is generated from `swimzh.domain.access.ACCESS_TYPES`. The phone
// ships its own copy of that prose because it has no network, and a copy drifts — invisibly,
// because each side stays self-consistent while telling swimmers different things. This is the
// gate that stops it.
//
// S4 moved the prose into the catalog, and the parity SURVIVED rather than being relaxed: the
// legend's messages are rendered through the ENGLISH catalog and compared to the generated
// JSON word for word, exactly as before. `access_types.json` is the ENGLISH oracle and makes no
// claim about the other four languages, so those are held to the weaker — but still real —
// rule that every one of them carries a non-empty sentence that is not the key itself.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The access-types legend")
struct AccessExplainerTests {
  static let en = CatalogFixture.english

  static func generated() throws -> [[String: Any]] {
    let url = RepoFixtures.root.appending(
      path: "apps/ios/Tests/SwimZHKitTests/Fixtures/access_types.json")
    let object = try RepoFixtures.json(at: url)
    return (object["types"] as? [[String: Any]]) ?? []
  }

  @Test("the phone's legend reproduces the domain's, key for key and word for word")
  func legendMatchesTheDomain() throws {
    let generated = try Self.generated()
    #expect(
      generated.count == accessExplanations.count,
      "\(generated.count) vs \(accessExplanations.count)")
    #expect(generated.count >= 11)
    for (raw, mine) in zip(generated, accessExplanations) {
      // ORDER too: the legend reads in the domain's own order, so a reader comparing the two
      // surfaces sees the same list rather than the same set.
      #expect(raw["class_name"] as? String == mine.className)
      #expect(raw["key"] as? String == mine.key, "\(mine.className)")
      // Word for word, through the ENGLISH catalog. This is a stronger check than the string
      // equality it replaced: it proves the English catalog still says what the domain says
      // AND that the key resolves at all, where before it only proved one Swift literal
      // matched one JSON literal.
      #expect(raw["label"] as? String == Self.en(mine.label), "\(mine.className)")
      #expect(raw["description"] as? String == Self.en(mine.description), "\(mine.className)")
    }
  }

  @Test("every legend entry is really translated, in all five languages")
  func everyEntryIsTranslated() {
    // `access_types.json` is the ENGLISH oracle and says nothing about the other four, so this
    // is the strongest claim available for them: a key the converter never wrote renders as
    // ITSELF, which on the legend screen reads like a design choice rather than a missing
    // string — and the legend is the one screen whose entire content is prose.
    for (language, localized) in CatalogFixture.all {
      for entry in accessExplanations {
        for message in [entry.label, entry.description] {
          let said = localized(message)
          #expect(!said.isEmpty, "\(language)/\(entry.className)")
          #expect(said != message.key, "\(language) has no translation for \(message.key)")
        }
      }
    }
  }

  @Test("every access class the ribbon can colour also has an explanation")
  func everyFamilyIsExplained() {
    // The two vocabularies must not diverge: a session drawn in its own colour with no legend
    // entry is a colour nobody can read.
    for className in accessFamilies.keys {
      #expect(accessExplanation(for: className) != nil, "\(className) has no explanation")
    }
    #expect(Set(accessExplanations.map(\.className)) == Set(accessFamilies.keys))
  }

  @Test("an access class this binary has never heard of has NO explanation")
  func unknownClassHasNoExplanation() {
    // Nil, not a generic "public swimming" fallback. A store built by a newer export can carry
    // an arm this app does not know, and describing it as open to everyone is the
    // welcome-by-default failure the whole eligibility vocabulary exists to prevent.
    #expect(accessExplanation(for: "SomethingNew") == nil)
  }

  @Test("no explanation of a RESTRICTED session says it is open to everyone")
  func restrictedSessionsAreNeverDescribedAsOpen() {
    let restricted = ["WomenOnly", "GirlsOnly", "SchoolReserved", "ClubReserved", "SeniorsOnly"]
    for className in restricted {
      let message = accessExplanation(for: className)?.description
      let said = message.map { Self.en($0) }?.lowercased() ?? ""
      #expect(!said.contains("anyone may enter"), "\(className)")
      #expect(!said.isEmpty)
    }
    // The English phrase is English, so the rule is restated in a form all five can be held to:
    // no restricted class ever borrows the PUBLIC class's sentence. That is the shape the harm
    // takes in a catalog — a translator handed eleven similar descriptions pastes one twice —
    // and it is exactly the welcome-by-default failure the vocabulary exists to prevent.
    let publicDescription = accessExplanation(for: "PublicSwim")?.description
    for (language, localized) in CatalogFixture.all {
      let open = publicDescription.map { localized($0) }
      for className in restricted {
        let said = (accessExplanation(for: className)?.description).map { localized($0) }
        #expect(said != open, "\(language)/\(className) is described as the public session")
      }
    }
  }
}
