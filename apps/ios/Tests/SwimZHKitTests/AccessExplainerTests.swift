// The access-types legend, held to the domain's own words.
//
// `Fixtures/access_types.json` is generated from `swimzh.domain.access.ACCESS_TYPES`. The phone
// ships its own copy of that prose because it has no network, and a copy drifts — invisibly,
// because each side stays self-consistent while telling swimmers different things. This is the
// gate that stops it.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The access-types legend")
struct AccessExplainerTests {
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
      #expect(raw["label"] as? String == mine.label, "\(mine.className)")
      #expect(raw["description"] as? String == mine.description, "\(mine.className)")
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
    for className in ["WomenOnly", "GirlsOnly", "SchoolReserved", "ClubReserved", "SeniorsOnly"] {
      let said = (accessExplanation(for: className)?.description ?? "").lowercased()
      #expect(!said.contains("anyone may enter"), "\(className)")
      #expect(!said.isEmpty)
    }
  }
}
