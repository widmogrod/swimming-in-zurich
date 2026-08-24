// The two small ports: the price bracket and the clock comparison.
//
// Both are exercised end to end by the golden answers too; these tests pin the edges the
// golden fixture's three personas do not reach — the tie rule, the below-every-band case,
// and the half-open window boundary.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Pricing")
struct PricingTests {
  /// Zürich's real shape: adult from 20, youth from 16, child from 6, nothing below 6.
  static let zurich = PriceDoc(
    entries: [
      PriceEntry(
        category: .adult, amountCHF: 8, display: "Erwachsene (ab 20 J.) Fr. 8.00", minAge: 20),
      PriceEntry(
        category: .youth, amountCHF: 6, display: "Jugendliche (ab 16 J.) Fr. 6.00", minAge: 16),
      PriceEntry(category: .child, amountCHF: 4, display: "Kinder (ab 6 J.) Fr. 4.00", minAge: 6),
    ],
    validAsOf: "2026-08-23",
    sourceURL: "https://example.invalid/preise"
  )

  @Test(
    "the greatest published bound the age clears wins",
    arguments: [
      (6, PriceCategory.child), (15, .child), (16, .youth), (19, .youth), (20, .adult),
      (99, .adult),
    ])
  func bracket(age: Int, expected: PriceCategory) {
    #expect(priceFor(Self.zurich, Person(age: age))?.category == expected)
  }

  @Test("an unknown age takes the unreduced rate — the one answer that cannot undercharge")
  func unknownAgeIsTheTopBand() {
    #expect(priceFor(Self.zurich, Person())?.category == .adult)
  }

  @Test("an age below every published bound has no price — unknown is not the adult rate")
  func belowEveryBand() {
    #expect(priceFor(Self.zurich, Person(age: 3)) == nil)
  }

  @Test("an entry the source printed no bound for is skipped, not treated as universal")
  func unboundedEntryIsSkipped() {
    let doc = PriceDoc(entries: [
      PriceEntry(category: .adult, amountCHF: 9, display: "Eintritt", minAge: nil)
    ])
    #expect(priceFor(doc, Person(age: 40)) == nil)
  }

  @Test("two entries at the same bound resolve to the FIRST, as Python's max(key:) does")
  func tieTakesTheFirst() {
    // `Sequence.max(by:)` would take the last. A duplicated bound in one tariff is rare, not
    // impossible, and a silent disagreement about which row is charged is exactly the drift
    // a golden fixture over three personas would not necessarily catch.
    let doc = PriceDoc(entries: [
      PriceEntry(category: .adult, amountCHF: 8, display: "first", minAge: 20),
      PriceEntry(category: .adult, amountCHF: 9, display: "second", minAge: 20),
    ])
    #expect(priceFor(doc, Person(age: 40))?.display == "first")
  }

  @Test("a free or unpriced pool has no bracket, never a zero-franc one")
  func freeAndUnknownHaveNoBracket() {
    #expect(priceFor(Admission.free, Person(age: 40)) == nil)
    #expect(priceFor(Admission.unknown, Person(age: 40)) == nil)
    #expect(priceFor(Admission.tariff(Self.zurich), Person(age: 40))?.amountCHF == 8)
  }

  @Test("the stored document decodes, and a fourth category is malformed rather than adult")
  func decoding() {
    let json = """
      {"entries":[{"amount_chf":8.0,"category":"adult","display":"E","min_age":20}],\
      "source_url":"https://example.invalid","valid_as_of":"2026-08-23"}
      """
    let doc = PriceDoc.decode(json: json)
    #expect(doc?.entries.first?.minAge == 20)
    #expect(doc?.validAsOf == "2026-08-23")
    #expect(doc?.sourceURL == "https://example.invalid")
    let unknownCategory =
      #"{"entries":[{"amount_chf":8.0,"category":"student","display":"E","min_age":20}]}"#
    #expect(PriceDoc.decode(json: unknownCategory) == nil)
    #expect(PriceDoc.decode(json: "nonsense") == nil)
  }
}

@Suite("Clock")
struct ClockTests {
  @Test("the session window is half-open: open at the start, shut at the end")
  func halfOpen() throws {
    let window = TimeWindow(
      start: try #require(TimeOfDay(hhmm: "06:00")),
      end: try #require(TimeOfDay(hhmm: "22:00"))
    )
    #expect(openAtQueryTime(window, at: TimeOfDay(hour: 6, minute: 0)))
    #expect(openAtQueryTime(window, at: TimeOfDay(hour: 21, minute: 59)))
    #expect(!openAtQueryTime(window, at: TimeOfDay(hour: 22, minute: 0)))
    #expect(!openAtQueryTime(window, at: TimeOfDay(hour: 5, minute: 59)))
  }

  @Test("HH:MM parses, round-trips, and refuses anything else")
  func parsing() {
    #expect(TimeOfDay(hhmm: "06:05")?.hhmm == "06:05")
    #expect(TimeOfDay(hhmm: "24:00")?.minutesSinceMidnight == 1_440)
    #expect(TimeOfDay(hhmm: "6:5")?.hhmm == "06:05")
    #expect(TimeOfDay(hhmm: "25:00") == nil)
    #expect(TimeOfDay(hhmm: "06:60") == nil)
    #expect(TimeOfDay(hhmm: "0600") == nil)
    #expect(TimeOfDay(hhmm: "") == nil)
    #expect(TimeOfDay(hhmm: "aa:bb") == nil)
  }

  @Test("a Zurich instant maps to the store's day key and wall-clock time")
  func zurichConversion() throws {
    let instant = try #require(
      ZurichClock.instant(day: "2026-08-24", at: TimeOfDay(hour: 12, minute: 0))
    )
    #expect(ZurichClock.day(of: instant) == "2026-08-24")
    #expect(ZurichClock.timeOfDay(of: instant) == TimeOfDay(hour: 12, minute: 0))
  }

  @Test("the day key is Zurich's, not UTC's — 00:30 CEST is still the same local day")
  func dayKeyIsLocal() throws {
    // 2026-08-24 00:30 in Zürich is 2026-08-23 22:30 UTC. A UTC-based key would show the
    // previous day's schedule to anyone checking after midnight.
    let instant = try #require(
      ZurichClock.instant(day: "2026-08-24", at: TimeOfDay(hour: 0, minute: 30))
    )
    #expect(ZurichClock.day(of: instant) == "2026-08-24")
  }

  @Test("a malformed day key yields no instant rather than a coerced one")
  func malformedDayKey() {
    #expect(ZurichClock.instant(day: "not-a-day", at: TimeOfDay(hour: 12, minute: 0)) == nil)
    #expect(ZurichClock.instant(day: "2026-08", at: TimeOfDay(hour: 12, minute: 0)) == nil)
  }

  /// A known week, named day by day. 2026-08-24 is a Monday, so this walks Mon→Sun and back
  /// round to Monday — the SUNDAY WRAP included, which is the only place `(weekday + 5) % 7`
  /// can go wrong (`Calendar` numbers Sunday 1, so Sunday is the value that has to fold).
  static let knownWeek: [(day: String, weekday: Int, name: String)] = [
    ("2026-08-24", 0, "Monday"),
    ("2026-08-25", 1, "Tuesday"),
    ("2026-08-26", 2, "Wednesday"),
    ("2026-08-27", 3, "Thursday"),
    ("2026-08-28", 4, "Friday"),
    ("2026-08-29", 5, "Saturday"),
    ("2026-08-30", 6, "Sunday"),
    ("2026-08-31", 0, "Monday again"),
  ]

  @Test("every weekday maps to the export's MONDAY == 0 numbering, Sunday wrap included")
  func weekdayNumbering() {
    // This function is the date→lane-plan JOIN: `Store.laneDays` reads `lane_day WHERE
    // weekday = ?` through it. Nothing tested it, and an off-by-one would be SILENT — all six
    // real basins publish a plan for all seven weekdays, so a wrong day returns a full,
    // plausible plan (a club's Sunday reservations shown on a Wednesday) with the chain green.
    for entry in Self.knownWeek {
      #expect(ZurichClock.weekday(of: entry.day) == entry.weekday, "\(entry.name)")
    }
    #expect(ZurichClock.weekday(of: "not-a-day") == nil)
  }

  @Test("the numbering agrees with Foundation's own, independently of the shift being tested")
  func weekdayAgreesWithFoundation() throws {
    // An oracle rather than a second copy of the table: `DateFormatter` with a fixed POSIX
    // locale names the day, so this fails if the shift is wrong even where the table above is
    // also wrong. Walked over a whole year so no single month's alignment can carry it.
    let names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = ZurichClock.timeZone
    formatter.dateFormat = "EEEE"
    var day = "2026-01-01"
    for _ in 0..<366 {
      let instant = try #require(ZurichClock.instant(day: day, at: TimeOfDay(hour: 12, minute: 0)))
      let index = try #require(ZurichClock.weekday(of: day))
      #expect(names[index] == formatter.string(from: instant), "\(day)")
      day = try #require(ZurichClock.day(day, plus: 1))
    }
  }

  // The store-backed half lives in `LanePlanTests.storeJoinsTheRightWeekdaysPlan`, next to the
  // lane fixture it needs. Note that asserting `option.laneDayView?.weekday ==
  // ZurichClock.weekday(of: day)` would be a TAUTOLOGY — `Store.laneDays` passes the queried
  // weekday into `LaneDay.decode` rather than reading the row's own column — so that test
  // compares the STRIPS against an independently derived weekday instead.
}
