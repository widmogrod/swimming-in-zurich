// The generated eligibility contract, replayed in Swift.
//
// `apps/web/tests/fixtures/eligibility_contract.json` is generated from
// `swimzh.domain.access.eligibility` itself. The browser module replays it; so does this.
// Three implementations of one rule, one file none of them can move without the others.
//
// The suite FAILS on a case-count mismatch rather than skipping (plan S2 acceptance 2): a
// replay that quietly runs zero cases is the failure mode that makes a contract test
// decorative.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Eligibility contract")
struct EligibilityContractTests {
  /// Every case in the committed contract, decoded into the arguments `eligibility` takes.
  struct ContractCase {
    let access: SessionAccess
    let accessName: String
    let params: [String: Any]
    let person: Person
    let allowed: Bool
    let code: String
    let mark: UIMark

    init?(_ raw: [String: Any]) {
      guard let accessName = raw["access"] as? String,
        let params = raw["access_params"] as? [String: Any],
        let genderLabel = raw["gender"] as? String,
        let allowed = raw["allowed"] as? Bool,
        let code = raw["code"] as? String,
        let markRaw = raw["ui"] as? String,
        let mark = UIMark(rawValue: markRaw)
      else { return nil }
      self.accessName = accessName
      self.params = params
      self.access = SessionAccess.decode(
        kind: accessName,
        params: AccessParams(
          minAge: params["min_age"] as? Int,
          club: params["club"] as? String,
          note: params["note"] as? String
        )
      )
      self.person = Person(
        gender: genderLabel.isEmpty ? nil : Gender(rawValue: genderLabel),
        age: raw["age"] as? Int
      )
      self.allowed = allowed
      self.code = code
      self.mark = mark
    }
  }

  /// Decoded fresh per test rather than cached in a `static let`: the case list is
  /// `[String: Any]` and so not `Sendable`, and 680 cells parse in microseconds.
  static func contract() throws -> [ContractCase] {
    try RepoFixtures.cases(at: RepoFixtures.eligibilityContract).compactMap(ContractCase.init)
  }

  @Test("every case decodes — a dropped case is a silently narrowed contract")
  func everyCaseDecodes() throws {
    let raw = try RepoFixtures.cases(at: RepoFixtures.eligibilityContract)
    #expect(raw.count > 0)
    #expect(try Self.contract().count == raw.count)
  }

  @Test("SwimZHKit agrees with the server on every access × gender × age")
  func agreesWithTheServer() throws {
    for testCase in try Self.contract() {
      let verdict = eligibility(testCase.person, testCase.access)
      let context = """
        \(testCase.accessName)\(testCase.params) gender=\(testCase.person.gender?.rawValue ?? "unset") \
        age=\(testCase.person.age.map(String.init) ?? "unknown")
        """
      #expect(verdict.allowed == testCase.allowed, "\(context): allowed")
      #expect(verdict.code.rawValue == testCase.code, "\(context): reason code")
      #expect(uiMark(verdict) == testCase.mark, "\(context): badge")
    }
  }

  @Test("the contract covers every access type the domain publishes")
  func coversEveryAccessType() throws {
    let covered = Set(try Self.contract().map(\.accessName))
    #expect(
      covered == [
        "PublicSwim", "LaneSwim", "FamilyTime", "WomenOnly", "SeniorsOnly", "SchoolReserved",
        "ClubReserved", "AdultsOnly", "GirlsOnly", "GenderDiverse", "AccompaniedChildren",
      ]
    )
  }

  @Test("the PARAMETERISED arms appear at bounds that are not their defaults")
  func parameterisedArmsAreExercised() throws {
    // Without this the replay proves nothing about reading the published bound: a client
    // that hardcodes 60 / 18 / 16 would pass every cell drawn at the default.
    var bounds: [String: Set<Int>] = [:]
    for testCase in try Self.contract() {
      if let minAge = testCase.params["min_age"] as? Int {
        bounds[testCase.accessName, default: []].insert(minAge)
      }
    }
    #expect(bounds["SeniorsOnly"] == [59, 60, 61])
    #expect(bounds["AdultsOnly"] == [17, 18, 19])
    #expect(bounds["GenderDiverse"] == [15, 16, 17])
  }

  @Test("the published bound decides, not a constant")
  func theBoundDecides() {
    #expect(eligibility(Person(age: 17), .adultsOnly(minAge: 17, note: "")).allowed)
    #expect(!eligibility(Person(age: 18), .adultsOnly(minAge: 19, note: "")).allowed)
    #expect(eligibility(Person(age: 59), .seniorsOnly(minAge: 59)).allowed)
    #expect(!eligibility(Person(age: 60), .seniorsOnly(minAge: 61)).allowed)
    #expect(
      eligibility(Person(age: 16), .genderDiverse(minAge: 17)).code == .genderDiverseTooYoung
    )
    #expect(eligibility(Person(age: 15), .genderDiverse(minAge: 15)).code == .genderDiverseConfirm)
  }

  @Test("NO arm invents a published bound when the store omits one")
  func noArmInventsABound() {
    // `access.py` gives SeniorsOnly 60 and AdultsOnly 18 as DATACLASS defaults — what the
    // domain falls back to when a page states nothing. That is not licence for a client to
    // assume them: the export always writes the field, so a row without it is unreadable,
    // and answering "check with the pool" is the only claim the data supports. Defaulting
    // instead is exactly the hardcoded-threshold harm the widened contract exists to close.
    for kind in ["SeniorsOnly", "AdultsOnly", "GenderDiverse"] {
      let access = SessionAccess.decode(kind: kind, params: AccessParams())
      #expect(access == .unknown(kind: kind), "\(kind) invented a bound")
      #expect(uiMark(eligibility(Person(age: 8), access)) == .check)
      #expect(uiMark(eligibility(Person(age: 80), access)) == .check)
    }
    // `note` and `club` are display text, not decision inputs, so their absence defaults
    // harmlessly and the arm still decodes.
    #expect(
      SessionAccess.decode(kind: "AdultsOnly", params: AccessParams(minAge: 18))
        == .adultsOnly(minAge: 18, note: ""))
    #expect(
      SessionAccess.decode(kind: "ClubReserved", params: AccessParams()) == .clubReserved(club: ""))
    #expect(SessionAccess.decode(kind: "LaneSwim", params: AccessParams()) == .laneSwim(note: ""))
  }

  @Test("a GenderDiverse row with no published bound is unknown, never an invented one")
  func genderDiverseWithoutABoundIsUnknown() {
    // The domain REQUIRES `min_age` on this arm, so a row without one cannot be read. The
    // browser module's documented harm was inventing 16 here; this returns the honest
    // "check with the pool" instead and never a hard denial.
    let access = SessionAccess.decode(kind: "GenderDiverse", params: AccessParams())
    #expect(access == .unknown(kind: "GenderDiverse"))
    let verdict = eligibility(Person(age: 12), access)
    #expect(!verdict.allowed)
    #expect(uiMark(verdict) == .check)
  }

  @Test("an access kind from a newer store is ? , never ✓ and never ✕")
  func unknownAccessIsCheck() {
    let access = SessionAccess.decode(kind: "SomeFutureAccessKind", params: AccessParams())
    let verdict = eligibility(Person(gender: .male, age: 40), access)
    #expect(uiMark(verdict) == .check)
    #expect(access.kind == "SomeFutureAccessKind")
  }

  @Test("the round trip through (kind, params) preserves every arm")
  func decodingRoundTrips() {
    let arms: [SessionAccess] = [
      .publicSwim, .laneSwim(note: "n"), .familyTime(note: "n"), .womenOnly(note: "n"),
      .seniorsOnly(minAge: 62), .schoolReserved, .clubReserved(club: "SC Zürich"),
      .adultsOnly(minAge: 21, note: "n"), .girlsOnly, .genderDiverse(minAge: 14),
      .accompaniedChildren,
    ]
    for arm in arms {
      let params: AccessParams
      switch arm {
      case .seniorsOnly(let minAge): params = AccessParams(minAge: minAge)
      case .genderDiverse(let minAge): params = AccessParams(minAge: minAge)
      case .adultsOnly(let minAge, let note): params = AccessParams(minAge: minAge, note: note)
      case .clubReserved(let club): params = AccessParams(club: club)
      case .laneSwim(let note), .familyTime(let note), .womenOnly(let note):
        params = AccessParams(note: note)
      default: params = AccessParams()
      }
      #expect(SessionAccess.decode(kind: arm.kind, params: params) == arm)
    }
  }

  @Test("a club name rides as a param, never spliced into a sentence")
  func clubNameIsAParam() {
    let verdict = eligibility(Person(), .clubReserved(club: "SC Zürich"))
    #expect(verdict.params["club"] == .string("SC Zürich"))
    #expect(eligibility(Person(), .clubReserved(club: "")).params.isEmpty)
  }

  @Test("a day's badge is in > chk > no, and ? never collapses to ✕")
  func dayBadgePriority() {
    #expect(dayEligibility([.no, .check, .attend]) == .attend)
    #expect(dayEligibility([.no, .check]) == .check)
    #expect(dayEligibility([.no, .no]) == .no)
    #expect(dayEligibility([]) == .no)
  }

  @Test("AccessParams decoding survives a malformed document")
  func malformedParamsDecodeToEmpty() {
    #expect(AccessParams.decode(json: "not json") == AccessParams())
    #expect(AccessParams.decode(json: "{}") == AccessParams())
    #expect(
      AccessParams.decode(json: #"{"min_age":18,"note":""}"#) == AccessParams(minAge: 18, note: ""))
  }
}
