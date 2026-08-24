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
  /// The English renderer. The golden fixture is Python's ENGLISH prose, so the warning
  /// comparisons render `DayWarning.message` through the English catalog and keep comparing to
  /// it byte for byte — `render_warning` is now the TEST's oracle rather than a second
  /// implementation living in Swift.
  static let en = CatalogFixture.english

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
      //
      // Compared against the golden with its ONE machine date formatted — see
      // `withFormattedDates`. Everything else is still byte-for-byte.
      let expectedWarnings = (testCase["warnings"] as? [String] ?? [])
        .map(Self.withFormattedDates).sorted()
      #expect(
        answer.warnings.map { Self.en($0.message(Self.en.format)) }.sorted() == expectedWarnings,
        "warnings for \(context)")
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

  /// A golden warning, with its machine date rendered the way the CLIENT renders it.
  ///
  /// THE ONE DELIBERATE DIVERGENCE from `etl/ios_export.render_warning`, and it is worth being
  /// precise about rather than hiding behind a looser comparison. Python interpolates
  /// `params["date"]` as `date.isoformat()` — `2026-12-25` — because it is writing a machine
  /// record. The client is writing to a reader, and a reader gets `25 December 2026` (and
  /// `25 grudnia 2026` in Polish), which is what the browser has always shown for the same
  /// fact. So the golden's date is formatted here and EVERY OTHER CHARACTER is still compared
  /// byte for byte: the wording, the punctuation, the pool list, the order.
  static func withFormattedDates(_ golden: String) -> String {
    var out = golden
    // A plain scan rather than `replacing(_:with:)`: the closure form of that method takes a
    // `Collection`, not a `Regex`, and the two overloads read identically at the call site.
    while let range = out.firstRange(of: /\b\d{4}-\d{2}-\d{2}\b/) {
      out.replaceSubrange(range, with: Self.en.format.storeDate(String(out[range])))
    }
    return out
  }

  @Test("the two warning codes render as find_swim_options renders them, dates aside")
  func warningRendering() {
    // Still the Python sentence, word for word — S4 moved the renderer into the catalog, not
    // the standard. The ENGLISH catalog entry is the thing under test here; the other four are
    // held to their own rule below.
    let coverage = DayWarning(code: DayWarning.calendarCoverage, params: ["year": "2027"])
    #expect(
      Self.en(coverage.message(Self.en.format))
        == "calendar data not available for 2027; holiday-dependent schedules may be inaccurate"
    )
    // A YEAR is not formatted: four digits are four digits in every locale here, and putting a
    // year through a date formatter would invent a day and a month for it.
    #expect(Self.en(coverage.message(Self.en.format)).contains("2027"))

    let holiday = DayWarning(
      code: DayWarning.holidayHoursUnverified,
      params: ["date": "2026-12-25", "pools": "Hallenbad City"]
    )
    // The DATE is formatted, and this is the assertion that says so out loud.
    #expect(
      Self.en(holiday.message(Self.en.format)) == """
        25 December 2026 is a public holiday and these pools do not publish their holiday \
        hours; the times shown are their usual weekday hours and are unconfirmed: \
        Hallenbad City
        """
    )
    // ...and it is the golden's own sentence, with only that field moved.
    #expect(
      Self.en(holiday.message(Self.en.format))
        == Self.withFormattedDates(
          """
          2026-12-25 is a public holiday and these pools do not publish their holiday hours; \
          the times shown are their usual weekday hours and are unconfirmed: Hallenbad City
          """)
    )
    // Every language formats it its own way, and none of them leaks the ISO form.
    for (language, localized) in CatalogFixture.all {
      let said = localized(holiday.message(localized.format))
      #expect(!said.contains("2026-12-25"), "\(language) leaks the machine date: \(said)")
      #expect(said.contains("2026"), "\(language) lost the year: \(said)")
    }
  }

  @Test("both warnings carry the query's own values into every language")
  func warningParamsSurviveTranslation() {
    // The golden fixture is Python's English and is silent about the other four, so what they
    // can be held to is this: the year, the date and the pool NAMES are DATA, and a catalog
    // that dropped a positional specifier would quietly render a warning about no year and no
    // pools — a caveat that qualifies nothing, which is worse than no caveat at all.
    let coverage = DayWarning(code: DayWarning.calendarCoverage, params: ["year": "2027"])
    let holiday = DayWarning(
      code: DayWarning.holidayHoursUnverified,
      params: ["date": "2026-12-25", "pools": "Hallenbad City"]
    )
    for (language, localized) in CatalogFixture.all {
      #expect(
        localized(coverage.message(localized.format)).contains("2027"),
        "\(language) dropped the year")
      let said = localized(holiday.message(localized.format))
      // The date SURVIVES, formatted for this reader — it must not vanish, and it must not
      // arrive as the machine form. "2026" is the part every locale shares.
      #expect(said.contains("2026"), "\(language) dropped the date")
      #expect(!said.contains("2026-12-25"), "\(language) leaks the machine date: \(said)")
      #expect(said.contains("Hallenbad City"), "\(language) dropped the pool names")
    }
  }

  @Test("an unrecognised warning code renders as itself, never as the holiday sentence")
  func unknownWarningCodeDoesNotFabricate() {
    // A store built by a newer export can carry a code this binary has never seen, and S5
    // downloads exactly such stores. Falling through to the holiday branch would have
    // produced " is a public holiday and these pools do not publish their holiday hours;
    // ... : " — a fabricated claim about pools it never named.
    let unknown = DayWarning(code: "some_future_advisory", params: ["year": "2028"])
    let holiday = DayWarning(code: DayWarning.holidayHoursUnverified, params: [:])
    // In EVERY language, because the passthrough is now a catalog entry (`warning.unknown`,
    // "%@" in all five) and a translator who "improved" it into prose would be inventing
    // exactly the fact this arm exists to refuse — in four languages English cannot see.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(unknown.message(localized.format)) == "some_future_advisory", "\(language)")
      // ...and it never borrows the holiday sentence. Compared as a WHOLE sentence rather than
      // by an English phrase, so the claim can be made about all five.
      #expect(
        localized(unknown.message(localized.format))
          != localized(holiday.message(localized.format)), "\(language)")
    }
    #expect(!Self.en(unknown.message(Self.en.format)).contains("public holiday"))
    // An EMPTY params map on a known code still renders that code's sentence — the shape is
    // decided by the code, not by which params happen to be present.
    #expect(Self.en(holiday.message(Self.en.format)).contains("public holiday"))
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
