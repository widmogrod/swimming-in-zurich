// What one day chip says — the part of the day strip a screenshot would otherwise be the only
// witness for.
//
// The locale is passed explicitly in every case here. Two of the facts being pinned are exactly
// the ones a system-locale formatter gets wrong for someone else's device: a non-Gregorian
// calendar locale would produce a day NUMBER that belongs to no row in the store, and a
// formatter left on the system time zone would name the wrong weekday for a reader on another
// continent.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Day chips")
struct DayChipTests {
  static let english = Locale(identifier: "en_GB")

  @Test("today says so, and the rest name their weekday")
  func todayIsNamed() {
    // 2026-08-24 is a Monday. "Today" beats the weekday because it is the one chip a user
    // looks for, and it is the only caption not derivable from the number beside it.
    let today = dayChip(for: "2026-08-24", today: "2026-08-24", locale: Self.english)
    #expect(today.isToday)
    #expect(today.caption == "Today")
    #expect(today.number == "24")

    let tomorrow = dayChip(for: "2026-08-25", today: "2026-08-24", locale: Self.english)
    #expect(!tomorrow.isToday)
    #expect(tomorrow.caption == "Tue")
    #expect(tomorrow.number == "25")
  }

  @Test("the day number has no leading zero and matches the store key")
  func numbersAreBare() {
    let chip = dayChip(for: "2026-09-05", today: "2026-08-24", locale: Self.english)
    #expect(chip.number == "5")
    #expect(chip.day == "2026-09-05")
  }

  @Test("the accessibility label names the whole date")
  func accessibilityLabelIsFull() {
    let chip = dayChip(for: "2026-09-05", today: "2026-08-24", locale: Self.english)
    #expect(chip.accessibilityLabel.contains("September"))
    #expect(chip.accessibilityLabel.contains("5"))
    // Even today's chip: the caption says "Today", so VoiceOver would otherwise never state
    // which date that is.
    let today = dayChip(for: "2026-08-24", today: "2026-08-24", locale: Self.english)
    #expect(today.accessibilityLabel.contains("August"))
  }

  @Test("the weekday is Zurich's, not the reader's device zone")
  func weekdayIsZurich() {
    // A reader in Auckland is thirteen hours ahead; a formatter on the system zone would name
    // the wrong day for a store keyed by Zurich calendar days.
    let auckland = Locale(identifier: "en_NZ")
    let chip = dayChip(for: "2026-08-24", today: "2026-08-01", locale: auckland)
    #expect(chip.number == "24")
    #expect(chip.caption == "Mon")
  }

  @Test("a locale with another calendar still yields the store's own day number")
  func nonGregorianLocales() {
    // The chips ADDRESS rows in the store. A Buddhist- or Japanese-calendar locale that
    // renumbered the day would produce a chip that selects nothing at all.
    //
    // `contains`, not `==`: ja_JP renders the day as "24日", which is the locale being right
    // rather than the number being wrong. What must hold is that the NUMBER is the store's own,
    // and that the key it carries is untouched by the calendar.
    for identifier in ["th_TH@calendar=buddhist", "ja_JP@calendar=japanese", "pl_PL"] {
      let chip = dayChip(
        for: "2026-08-24", today: "2026-01-01", locale: Locale(identifier: identifier))
      #expect(chip.day == "2026-08-24")
      #expect(chip.number.contains("24"), "\(identifier) renumbered the day to \(chip.number)")
      #expect(!chip.number.contains("2569"), "\(identifier) leaked a non-Gregorian year")
    }
  }

  @Test("a malformed key shows itself rather than vanishing")
  func malformedKeysAreVisible() {
    // The strip is built from the store's own horizon, so an unparseable day means the STORE
    // is wrong. A blank chip would hide that; a visible one reports it.
    let chip = dayChip(for: "not-a-day", today: "2026-08-24", locale: Self.english)
    #expect(chip.caption == "not-a-day")
    #expect(chip.number == "not-a-day")
    #expect(!chip.isToday)
  }

  @Test("the strip spans the whole horizon, in order, with exactly one `today`")
  func chipsSpanTheHorizon() async throws {
    let meta = try await Store.bundled().metadata()
    let chips = dayChips(
      from: meta.horizonStart, through: meta.horizonEnd, today: meta.horizonStart,
      locale: Self.english)
    #expect(chips.first?.day == meta.horizonStart)
    #expect(chips.last?.day == meta.horizonEnd)
    #expect(chips.map(\.day) == chips.map(\.day).sorted())
    #expect(chips.filter(\.isToday).count == 1)
    // Every chip is a real key of the store's horizon — so tapping one can never select a day
    // that has no rows.
    for chip in chips { #expect(meta.covers(day: chip.day)) }
  }

  @Test("day arithmetic crosses a DST boundary without losing or repeating a day")
  func dayArithmeticSurvivesDST() {
    // Zurich moves to winter time on 2026-10-25. Adding 86_400 seconds across it would land on
    // the same date twice; going through `Calendar` at midday does not.
    #expect(ZurichClock.day("2026-10-24", plus: 1) == "2026-10-25")
    #expect(ZurichClock.day("2026-10-25", plus: 1) == "2026-10-26")
    #expect(ZurichClock.day("2026-03-28", plus: 1) == "2026-03-29")
    #expect(ZurichClock.day("2026-03-29", plus: 1) == "2026-03-30")
    #expect(ZurichClock.day("2026-12-31", plus: 1) == "2027-01-01")
    #expect(ZurichClock.day("nonsense", plus: 1) == nil)
    let across = ZurichClock.days(from: "2026-10-23", through: "2026-10-27")
    #expect(across == ["2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27"])
  }

  @Test("the horizon walk is bounded, and an inverted range is empty")
  func horizonWalkIsBounded() {
    // The horizon comes from a store this binary did not write — S5 downloads them — so a
    // corrupt `horizon_end` far in the future must not become an unbounded allocation.
    #expect(ZurichClock.days(from: "2026-01-01", through: "2099-01-01", limit: 5).count == 5)
    #expect(ZurichClock.days(from: "2026-02-01", through: "2026-01-01").isEmpty)
    #expect(ZurichClock.days(from: "nonsense", through: "2026-01-01").isEmpty)
    #expect(ZurichClock.days(from: "2026-01-01", through: "2026-01-01") == ["2026-01-01"])
  }
}
