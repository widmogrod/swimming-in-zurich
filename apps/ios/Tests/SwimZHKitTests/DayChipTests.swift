// What one day chip says — the part of the day strip a screenshot would otherwise be the only
// witness for.
//
// The reader is passed explicitly in every case here, as a `Format` rather than as a bare
// `Locale`: since S4 the chip's formatting locale is derived from the app's own language
// (`AppLocale`), so en means en-GB and never en-US. Two of the facts being pinned are exactly
// the ones a system-locale formatter gets wrong for someone else's device: a non-Gregorian
// calendar locale would produce a day NUMBER that belongs to no row in the store, and a
// formatter left on the system time zone would name the wrong weekday for a reader on another
// continent.
//
// The caption is a `Wording`, and which CASE it is carries meaning: `.key("common.today")` is
// OUR word and is translated, `.verbatim(weekday)` is the FORMATTER's and is not. Both halves
// are asserted, because a caption that became a message on every chip would ask the catalog for
// a weekday name it has no business holding.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Day chips")
struct DayChipTests {
  /// The English reader — en-GB formatting, so dates are day-first and the weekday is "Mon".
  static let english = Format(AppLocale(.en))
  static let en = CatalogFixture.english

  @Test("today says so, and the rest name their weekday")
  func todayIsNamed() {
    // 2026-08-24 is a Monday. "Today" beats the weekday because it is the one chip a user
    // looks for, and it is the only caption not derivable from the number beside it.
    let today = dayChip(for: "2026-08-24", today: "2026-08-24", format: Self.english)
    #expect(today.isToday)
    // OUR word, so a message: the chip a user hunts for must be in the language they chose.
    #expect(today.caption == .key("common.today"))
    #expect(Self.en(today.caption) == "Today")
    #expect(today.number == "24")

    let tomorrow = dayChip(for: "2026-08-25", today: "2026-08-24", format: Self.english)
    #expect(!tomorrow.isToday)
    // The FORMATTER's word, so verbatim: no catalog holds weekday names, and Polish alone
    // would defeat one (it lower-cases them and inflects the month beside them).
    #expect(tomorrow.caption == .verbatim("Tue"))
    #expect(Self.en(tomorrow.caption) == "Tue")
    #expect(tomorrow.number == "25")

    // In EVERY language: the today chip says a translated word, and it is not the weekday's.
    // A missing `common.today` would otherwise render as the key itself, which on a chip reads
    // like a design choice rather than a hole in the catalog.
    for (language, localized) in CatalogFixture.all {
      let chip = dayChip(
        for: "2026-08-24", today: "2026-08-24", format: Format(AppLocale(language)))
      let said = localized(chip.caption)
      #expect(said != "common.today", "\(language) has no translation for common.today")
      #expect(!said.isEmpty)
      let other = dayChip(
        for: "2026-08-25", today: "2026-08-24", format: Format(AppLocale(language)))
      #expect(said != localized(other.caption), "\(language): today reads as a weekday")
    }
  }

  @Test("the day number has no leading zero and matches the store key")
  func numbersAreBare() {
    let chip = dayChip(for: "2026-09-05", today: "2026-08-24", format: Self.english)
    #expect(chip.number == "5")
    #expect(chip.day == "2026-09-05")
  }

  @Test("the accessibility label names the whole date")
  func accessibilityLabelIsFull() {
    let chip = dayChip(for: "2026-09-05", today: "2026-08-24", format: Self.english)
    #expect(chip.accessibilityLabel.contains("September"))
    #expect(chip.accessibilityLabel.contains("5"))
    // Even today's chip: the caption says "Today", so VoiceOver would otherwise never state
    // which date that is.
    let today = dayChip(for: "2026-08-24", today: "2026-08-24", format: Self.english)
    #expect(today.accessibilityLabel.contains("August"))
    // In every language it is a spelled-out date rather than the bare key — and it is the
    // FORMATTER's output, so it is never empty and never equal across two different days.
    for language in Language.allCases {
      let format = Format(AppLocale(language))
      let first = dayChip(for: "2026-09-05", today: "2026-08-24", format: format)
      let second = dayChip(for: "2026-09-06", today: "2026-08-24", format: format)
      #expect(!first.accessibilityLabel.isEmpty, "\(language)")
      #expect(first.accessibilityLabel != second.accessibilityLabel, "\(language)")
    }
  }

  @Test("the weekday is Zurich's, not the reader's device zone")
  func weekdayIsZurich() {
    // A reader in Auckland is thirteen hours ahead; a formatter on the system zone would name
    // the wrong day for a store keyed by Zurich calendar days. The zone is no longer a caller's
    // choice — `Format` pins `ZurichClock.timeZone` on every style — so this drives the fact
    // rather than the parameter: 2026-08-24 is a Monday in Zurich, and its NUMBER is 24. A
    // device-zone formatter reading the chip's noon instant from Auckland would say 25.
    let chip = dayChip(for: "2026-08-24", today: "2026-08-01", format: Self.english)
    #expect(chip.number == "24")
    #expect(chip.caption == .verbatim("Mon"))
    for (language, localized) in CatalogFixture.all {
      let other = dayChip(
        for: "2026-08-24", today: "2026-08-01", format: Format(AppLocale(language)))
      #expect(other.number.contains("24"), "\(language) named the wrong Zurich day")
      #expect(!localized(other.caption).isEmpty, "\(language)")
    }
  }

  @Test("a locale with another calendar still yields the store's own day number")
  func nonGregorianLocales() {
    // The chips ADDRESS rows in the store. A Buddhist- or Japanese-calendar locale that
    // renumbered the day would produce a chip that selects nothing at all.
    //
    // Since S4 the formatting locale is no longer whatever the device reports: it comes from
    // the closed `AppLocale` set, whose five regional locales are all Gregorian — which is the
    // structural half of this guarantee, and is asserted here so that adding a language with
    // another default calendar fails HERE rather than as a chip that selects no row.
    for language in Language.allCases {
      let locale = AppLocale(language).formatting
      #expect(locale.calendar.identifier == .gregorian, "\(language) formats in \(locale.calendar)")
      let chip = dayChip(
        for: "2026-08-24", today: "2026-01-01", format: Format(AppLocale(language)))
      // `contains`, not `==`: a locale is free to render "24." or "24日", which is the locale
      // being right rather than the number being wrong. What must hold is that the NUMBER is
      // the store's own, and that the key it carries is untouched by the calendar.
      #expect(chip.day == "2026-08-24")
      #expect(chip.number.contains("24"), "\(language) renumbered the day to \(chip.number)")
      #expect(!chip.number.contains("2569"), "\(language) leaked a non-Gregorian year")
      #expect(!chip.accessibilityLabel.contains("2569"), "\(language) leaked a non-Gregorian year")
    }
  }

  @Test("a malformed key shows itself rather than vanishing")
  func malformedKeysAreVisible() {
    // The strip is built from the store's own horizon, so an unparseable day means the STORE
    // is wrong. A blank chip would hide that; a visible one reports it.
    //
    // The key is the STORE's text, so it rides through as `.verbatim` — a catalog message here
    // would hide which key was unparseable behind a sentence of ours.
    let chip = dayChip(for: "not-a-day", today: "2026-08-24", format: Self.english)
    #expect(chip.caption == .verbatim("not-a-day"))
    #expect(Self.en(chip.caption) == "not-a-day")
    #expect(chip.number == "not-a-day")
    #expect(!chip.isToday)
  }

  @Test("the strip spans the whole horizon, in order, with exactly one `today`")
  func chipsSpanTheHorizon() async throws {
    let meta = try await Store.bundled().metadata()
    let chips = dayChips(
      from: meta.horizonStart, through: meta.horizonEnd, today: meta.horizonStart,
      format: Self.english)
    #expect(chips.first?.day == meta.horizonStart)
    #expect(chips.last?.day == meta.horizonEnd)
    #expect(chips.map(\.day) == chips.map(\.day).sorted())
    #expect(chips.filter(\.isToday).count == 1)
    // Exactly one chip carries OUR word; every other caption is the formatter's. A caption that
    // became a message on every chip would be asking the catalog for weekday names.
    #expect(chips.filter { $0.caption == .key("common.today") }.count == 1)
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
