// The golden answers: what `find_swim_options` returns, reproduced from the baked store.
//
// `tests/fixtures/ios_parity/answers.json` is generated from the DOMAIN query — 3 pools ×
// 5 dates × 3 personas, the dates straddling an ordinary weekday, a Sunday, a public
// holiday and an UNSEEDED calendar year. This suite reads the bundled export and asserts
// the same options, statuses, eligibility verdicts, prices, `open_at_query_time` values and
// warnings come back out (plan S2 acceptance 3).
//
// Together with S1's parity sweep (which proves the export equals the live query for every
// pool on every horizon date) this closes the loop: Python proves the STORE is right, and
// this proves Swift READS it right, including the three things the export deliberately does
// not bake — eligibility, price and the clock.
//
// The DATA-DEPENDENT counts are derived, never hardcoded: the recorded fixture gold store
// is thinner than live gold (6 lane-plan basins, 1 notice), so pinning those numbers would
// fail the day the cassettes are re-recorded, for reasons that have nothing to do with this
// code. The one literal below — 45 cases — is not such a number: it is the fixture's own
// SHAPE, the plan's 3 pools × 5 dates × 3 personas, and it must fail if that shrinks.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Golden answers")
struct GoldenAnswerTests {
  /// Read fresh per test: `[String: Any]` is not `Sendable`, and a static cache of it is a
  /// concurrency error rather than an optimisation worth having.
  static func cases() throws -> [[String: Any]] {
    try RepoFixtures.cases(at: RepoFixtures.parityAnswers)
  }

  /// The canonical rendering of one option, built identically from the fixture and from
  /// `SwimZHKit`, so a mismatch names the field rather than dumping two structs.
  static func key(
    basinID: String,
    start: String,
    end: String,
    access: String,
    minAge: Int?,
    weather: String,
    openNow: Bool,
    eligible: Bool,
    reason: String,
    price: String
  ) -> String {
    [
      basinID, start, end, access, minAge.map(String.init) ?? "-", weather,
      openNow ? "open" : "shut", eligible ? "eligible" : "not-eligible", reason, price,
    ].joined(separator: " | ")
  }

  static func minAge(of access: SessionAccess) -> Int? {
    switch access {
    case .seniorsOnly(let minAge), .genderDiverse(let minAge): return minAge
    case .adultsOnly(let minAge, _): return minAge
    default: return nil
    }
  }

  static func priceKey(_ price: PriceEntry?) -> String {
    guard let price else { return "no-price" }
    let bound = price.minAge.map(String.init) ?? "-"
    return "\(price.category.rawValue)/\(price.amountCHF)/\(bound)/\(price.display)"
  }

  static func expectedPriceKey(_ raw: Any?) -> String {
    guard let price = raw as? [String: Any],
      let category = price["category"] as? String,
      let amount = price["amount_chf"] as? Double,
      let display = price["display"] as? String
    else { return "no-price" }
    let bound = (price["min_age"] as? Int).map(String.init) ?? "-"
    return "\(category)/\(amount)/\(bound)/\(display)"
  }

  @Test("the fixture is present and non-trivial")
  func fixtureIsLoaded() throws {
    let cases = try Self.cases()
    #expect(cases.count == 45, "3 pools × 5 dates × 3 personas")
    #expect(cases.contains { ($0["options"] as? [[String: Any]])?.isEmpty == false })
    #expect(cases.contains { ($0["statuses"] as? [[String: Any]])?.isEmpty == false })
    #expect(cases.contains { ($0["warnings"] as? [String])?.isEmpty == false })
  }

  @Test("SwimZHKit reproduces every golden answer")
  func reproducesTheGoldenAnswers() async throws {
    let store = try Store.bundled()
    var optionsChecked = 0
    var statusesChecked = 0
    var warningsChecked = 0

    for testCase in try Self.cases() {
      let poolID = try #require(testCase["pool_id"] as? String)
      let day = try #require(testCase["date"] as? String)
      let persona = try #require(testCase["persona"] as? String)
      let atRaw = try #require(testCase["at"] as? String)
      let at = try #require(TimeOfDay(hhmm: atRaw))
      let person = Person(
        gender: (testCase["gender"] as? String).flatMap(Gender.init(rawValue:)),
        age: testCase["age"] as? Int
      )
      let context = "\(poolID) \(day) \(persona)"
      let answer = try await store.answer(onDay: day, at: at, for: person)

      // --- options
      let expectedOptions = (testCase["options"] as? [[String: Any]] ?? []).map { option in
        Self.key(
          basinID: option["basin_id"] as? String ?? "",
          start: option["start"] as? String ?? "",
          end: option["end"] as? String ?? "",
          access: option["access"] as? String ?? "",
          minAge: (option["access_params"] as? [String: Any])?["min_age"] as? Int,
          weather: option["weather"] as? String ?? "",
          openNow: option["open_at_query_time"] as? Bool ?? false,
          eligible: option["eligible"] as? Bool ?? false,
          reason: option["reason_code"] as? String ?? "",
          price: Self.expectedPriceKey(option["price"])
        )
      }.sorted()
      let gotOptions = answer.options.filter { $0.poolID == poolID }.map { option in
        Self.key(
          basinID: option.basinID,
          start: option.window.start.hhmm,
          end: option.window.end.hhmm,
          access: option.access.kind,
          minAge: Self.minAge(of: option.access),
          weather: option.weather,
          openNow: option.openAtQueryTime,
          eligible: option.eligibility.allowed,
          reason: option.eligibility.code.rawValue,
          price: Self.priceKey(option.price)
        )
      }.sorted()
      #expect(gotOptions == expectedOptions, "options for \(context)")
      optionsChecked += expectedOptions.count

      // --- statuses
      let expectedStatuses = (testCase["statuses"] as? [[String: Any]] ?? []).map { status in
        [
          status["status"] as? String ?? "",
          status["detail_code"] as? String ?? "",
          status["closure_code"] as? String ?? "-",
          String(
            describing: (status["detail_params"] as? [String: Any] ?? [:]).mapValues {
              String(describing: $0)
            }.sorted { $0.key < $1.key }),
        ].joined(separator: " | ")
      }.sorted()
      let gotStatuses = answer.statuses.filter { $0.poolID == poolID }.map { status in
        [
          status.status, status.detailCode, status.closureCode ?? "-",
          String(describing: status.detailParams.sorted { $0.key < $1.key }),
        ].joined(separator: " | ")
      }.sorted()
      #expect(gotStatuses == expectedStatuses, "statuses for \(context)")
      statusesChecked += expectedStatuses.count

      // --- warnings (a whole-query fact, so not filtered by pool)
      let expectedWarnings = (testCase["warnings"] as? [String] ?? []).sorted()
      #expect(
        answer.warnings.map(\.rendered).sorted() == expectedWarnings, "warnings for \(context)")
      warningsChecked += expectedWarnings.count

      // Every pool-day is answered by EITHER sessions or a status, never both and never
      // neither — the invariant that stops a schedule-less pool being drawn as "closed".
      #expect(
        gotOptions.isEmpty != gotStatuses.isEmpty,
        "\(context): a pool-day is either scheduled or explained, never both or neither"
      )
    }

    // Guard against a vacuous pass: the loop must actually have compared something of each
    // kind. A fixture that silently lost its options would otherwise report all-green.
    #expect(optionsChecked > 0)
    #expect(statusesChecked > 0)
    #expect(warningsChecked > 0)
  }

  @Test("the two warning codes render exactly as find_swim_options renders them")
  func warningRendering() {
    let coverage = DayWarning(code: DayWarning.calendarCoverage, params: ["year": "2027"])
    #expect(
      coverage.rendered
        == "calendar data not available for 2027; holiday-dependent schedules may be inaccurate"
    )
    let holiday = DayWarning(
      code: DayWarning.holidayHoursUnverified,
      params: ["date": "2026-12-25", "pools": "Hallenbad City"]
    )
    #expect(
      holiday.rendered == """
        2026-12-25 is a public holiday and these pools do not publish their holiday hours; \
        the times shown are their usual weekday hours and are unconfirmed: Hallenbad City
        """
    )
  }

  @Test("an unrecognised warning code renders as itself, never as the holiday sentence")
  func unknownWarningCodeDoesNotFabricate() {
    // A store built by a newer export can carry a code this binary has never seen, and S5
    // downloads exactly such stores. Falling through to the holiday branch would have
    // produced " is a public holiday and these pools do not publish their holiday hours;
    // ... : " — a fabricated claim about pools it never named.
    let unknown = DayWarning(code: "some_future_advisory", params: ["year": "2028"])
    #expect(unknown.rendered == "some_future_advisory")
    #expect(!unknown.rendered.contains("public holiday"))
    // An EMPTY params map on a known code still renders that code's sentence — the shape is
    // decided by the code, not by which params happen to be present.
    let holiday = DayWarning(code: DayWarning.holidayHoursUnverified, params: [:])
    #expect(holiday.rendered.contains("public holiday"))
  }

  @Test("a pool's own notice is carried through, in the pool's own words")
  func noticesAreCarried() async throws {
    // Derived, never hardcoded: the recorded fixture store carries fewer notices than live
    // gold, and pinning the count would break on a cassette re-record.
    let store = try Store.bundled()
    let meta = try await store.metadata()
    var found: [DayNotice] = []
    for offset in 0..<14 {
      guard
        let day = ZurichClock.instant(day: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0))?
          .addingTimeInterval(Double(offset) * 86_400)
      else { continue }
      let answer = try await store.answer(
        on: day,
        at: day,
        for: Person()
      )
      found.append(contentsOf: answer.notices)
    }
    #expect(!found.isEmpty, "the fixture store publishes at least one notice")
    #expect(found.allSatisfy { !$0.text.isEmpty && !$0.poolID.isEmpty })
  }
}
