// FormatTests.swift — S4 acceptance 4 and 5: values, and the rule about never re-parsing one.
//
// The web pins the same facts in `datefmt.test.ts`. They are pinned AGAIN here rather than
// assumed, and the plan said why: Apple ships its own ICU snapshot, so "the browser does X"
// is a claim about node's CLDR, not a promise about iOS. That caution earned its keep
// immediately — see `swissDecimalSeparators` below, where the two platforms genuinely disagree
// about French Switzerland.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Formatting values")
struct FormatTests {
  static func format(_ language: Language) -> Format { Format(AppLocale(language)) }

  /// 2026-07-23, noon in Zurich — the same date `datefmt.test.ts` uses.
  static let july23: Date = {
    var components = DateComponents()
    components.year = 2026
    components.month = 7
    components.day = 23
    components.hour = 12
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = ZurichClock.timeZone
    return calendar.date(from: components)!
  }()

  // MARK: - Acceptance 4: the regional locales

  @Test("the formatting locale is REGIONAL, and bare `en` is never used")
  func formattingLocalesAreRegional() {
    // Bare `en` means en-US and would flip every date to month-first for a Zürich audience;
    // bare `de`/`fr`/`it` would use German, French and Italian conventions rather than SWISS
    // ones, and the two differ in exactly the place a price is read.
    #expect(AppLocale(.en).formatting.identifier == "en_GB")
    #expect(AppLocale(.de).formatting.identifier == "de_CH")
    #expect(AppLocale(.fr).formatting.identifier == "fr_CH")
    #expect(AppLocale(.it).formatting.identifier == "it_CH")
    #expect(AppLocale(.pl).formatting.identifier == "pl")
  }

  @Test("the decimal separator is the reader's, and Apple's ICU is NOT the browser's")
  func swissDecimalSeparators() {
    // THE FINDING THIS TEST EXISTS FOR, and it is not the one the plan expected.
    //
    // The web pins (`datefmt.test.ts:85-93`) that de-CH and it-CH use a DOT — counter-intuitive
    // next to de-DE and it-IT, which use a comma — while fr-CH and pl use a comma. Measured on
    // Apple's ICU, that is true of de-CH, it-CH and pl, and FALSE of fr-CH: Foundation formats
    // 2.5 in fr-CH with a DOT, where node's `Intl.NumberFormat("fr-CH")` gives "2,5".
    //
    // So the two clients genuinely disagree for a French reader — the browser says "2,5 km" and
    // the phone says "2.5 km" — and neither is wrong: each is its own platform's CLDR snapshot.
    // The assertion records what THIS platform does, because that is what a swimmer sees; the
    // divergence is reported in the slice's ledger rather than papered over by hand-formatting,
    // which is the one fix that would be worse than the problem.
    for language in [Language.en, .de, .fr, .it] {
      #expect(
        Self.format(language).number(2.5, fractionDigits: 1) == "2.5",
        "\(language) no longer uses a dot — Apple's ICU snapshot has moved")
    }
    #expect(Self.format(.pl).number(2.5, fractionDigits: 1) == "2,5")
  }

  @Test("the Swiss group separator is an ASCII apostrophe, not a right single quote")
  func swissGroupSeparator() {
    // U+0027, not U+2019. Current CLDR moved Switzerland to the ASCII apostrophe and older
    // references still show the curly one; a hand-built separator would be invisible-wrong.
    // The web has no equivalent guard, so this is the only place the fact is pinned at all.
    for language in [Language.de, .fr, .it] {
      let grouped = Self.format(language).integer(1_234_567)
      #expect(grouped == "1'234'567", "\(language): \(grouped.unicodeScalars.map(\.value))")
      #expect(!grouped.contains("\u{2019}"), "\(language) uses U+2019")
    }
    // English groups with a comma and Polish with a space — neither is Swiss, and neither
    // should be quietly given the apostrophe by a shared code path.
    #expect(Self.format(.en).integer(1_234_567) == "1,234,567")
    #expect(!Self.format(.pl).integer(1_234_567).contains("'"))
  }

  @Test("Polish takes a genitive month and lower-cases its weekday")
  func polishGenitiveLowercaseMonth() {
    // The two facts `datefmt.ts` records as impossible for a lookup table: Polish inflects the
    // month INSIDE a date ("23 lipca", not the nominative "lipiec") and lower-cases both the
    // weekday and the month. No table of month names can produce the first and no
    // capitalisation rule can produce the second — only asking the formatter works, which is
    // the whole argument for `dayParts` reading the formatter's own field runs.
    let full = Self.format(.pl).dayParts(Self.july23).full
    #expect(full.contains("lipca"), "genitive month lost: \(full)")
    #expect(!full.contains("lipiec"), "nominative month used inside a date: \(full)")
    #expect(full.contains("czwartek"), "weekday missing or capitalised: \(full)")
    #expect(!full.contains("Czwartek"))
    // ...and the STANDALONE name is the nominative one, which is why `monthName` uses a
    // different symbol set from the one inside a date.
    #expect(Self.format(.pl).monthName(7) == "lipiec")
  }

  @Test("every language names the same day, in its own words")
  func dayPartsAreLocalised() {
    let expected: [Language: (weekday: String, full: String)] = [
      .en: ("Thu", "23 July 2026"),
      .de: ("Do", "23. Juli 2026"),
      .fr: ("jeu.", "23 juillet 2026"),
      .it: ("gio", "23 luglio 2026"),
      .pl: ("czw.", "23 lipca 2026"),
    ]
    for (language, want) in expected {
      let parts = Self.format(language).dayParts(Self.july23)
      #expect(parts.weekday == want.weekday, "\(language): \(parts.weekday)")
      #expect(parts.dayOfMonth == "23", "\(language): \(parts.dayOfMonth)")
      #expect(parts.full.contains(want.full), "\(language): \(parts.full)")
    }
  }

  @Test("a store date key is rendered as WORDS, never as the key itself")
  func storeDatesAreFormatted() {
    // The regression this exists to stop, and it shipped once: `meta.gold_valid_as_of` and
    // `meta.horizon_end` are the store's machine keys, and S4 put them on screen inside a
    // `Text(verbatim:)` — which looked right, because they ARE values, and was wrong, because
    // nothing had formatted them. A Polish reader saw `2026-08-24` where the browser shows
    // `24 sierpnia 2026`.
    let expected: [Language: String] = [
      .en: "23 July 2026",
      .de: "23. Juli 2026",
      .fr: "23 juillet 2026",
      .it: "23 luglio 2026",
      .pl: "23 lipca 2026",
    ]
    for (language, want) in expected {
      let said = Self.format(language).storeDate("2026-07-23")
      #expect(said == want, "\(language): \(said)")
      // ...and emphatically not the key, which is the whole point.
      #expect(said != "2026-07-23")
    }
  }

  @Test("the store-date path is the SAME formatter as `date(_:)`, on the Zurich day")
  func storeDateAgreesWithTheDateFormatter() {
    // `storeDate` is a parse plus `date(_:)`. Asserting they agree is what keeps it from
    // drifting into a second date format — and it pins the ZONE: the key names a Zurich
    // calendar day, so a formatter on another zone could render the day before.
    let instant = ZurichClock.instant(day: "2026-07-23", at: TimeOfDay(hour: 12, minute: 0))!
    for language in Language.allCases {
      let format = Self.format(language)
      #expect(format.storeDate("2026-07-23") == format.date(instant), "\(language)")
    }
    // A date key on a DST boundary still names its own day rather than sliding by an hour.
    #expect(Self.format(.en).storeDate("2026-03-29").contains("29"))
    #expect(Self.format(.en).storeDate("2026-10-25").contains("25"))
  }

  @Test("an unparseable store key is shown as itself, not blanked")
  func storeDateDegradesVisibly() {
    // A malformed key means the STORE is wrong — these strings come from its own horizon — so
    // a visible bad date reports that where a blank would hide it.
    #expect(Self.format(.en).storeDate("not-a-date") == "not-a-date")
    #expect(Self.format(.en).storeDate("2026-08") == "2026-08")
    #expect(Self.format(.en).storeDate("2026-08-24T12:00") == "2026-08-24T12:00")
    // MEASURED, and recorded rather than asserted as a wish: an out-of-RANGE key does NOT come
    // back as itself. `ZurichClock.instant` builds `DateComponents` and `Calendar` rolls them
    // over, so "2026-13-45" formats as 14 February 2027 — a plausible date that is not the one
    // in the store. That is S2's parser and the day strip depends on it, so this slice records
    // the behaviour instead of changing it; it only bites on a store that is already corrupt.
    #expect(Self.format(.en).storeDate("2026-13-45") == "14 February 2027")
  }

  @Test("the EMPTY key is a formatter no-op, and the policy for it lives at the call sites")
  func storeDateLeavesTheEmptyCaseToItsCallers() {
    // `""` is not a malformed date — it is the exporter saying "no stamp" (`ios_export.py`
    // writes `gold_valid_as_of or ""`). Rendering it as a blank beside a label would be the
    // invisible degradation the test above argues against, so it is NOT handled here: this is
    // a formatter, and "hide the row" is a policy about a screen.
    //
    // Every caller therefore guards it, and those guards are what is actually asserted:
    // `FacilityDetailTests.anEmptyStampIsOmitted` for the sheet's two dated rows, and
    // `TodayView.stampRow` for the two on the today screen. This assertion exists so the
    // no-op is deliberate rather than an oversight somebody later "fixes" here, breaking the
    // malformed-key case above in the process.
    #expect(Self.format(.en).storeDate("") == "")
    for (_, localized) in CatalogFixture.all {
      #expect(localized.format.storeDate("") == "")
    }
  }

  @Test("the day number has no leading zero and the date is a ZURICH date")
  func dayPartsUseTheZurichZone() {
    // A formatter left on the device zone names the wrong weekday for anyone reading from
    // another continent — and worse, the wrong DAY NUMBER, which would point at a date the
    // store has no row for.
    #expect(Self.format(.en).dayParts(Self.july23).dayOfMonth == "23")
    // 2026-01-01 at Zurich noon: single digit, no padding.
    var components = DateComponents()
    components.year = 2026
    components.month = 1
    components.day = 1
    components.hour = 12
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = ZurichClock.timeZone
    let newYear = calendar.date(from: components)!
    #expect(Self.format(.en).dayParts(newYear).dayOfMonth == "1")
  }

  @Test("a Zurich pool's metres stay metres, and its Celsius stays Celsius")
  func unitsAreNeverConverted() {
    // `usage: .asProvided`, and it is load-bearing rather than boilerplate: the default
    // converts to the locale's customary unit, and en-GB's is imperial. Without it a 12.5 m
    // basin renders as "41 ft" and a 1 m diving platform as "3 ft" — a Swiss pool's published
    // dimensions restated in units it never published.
    for language in Language.allCases {
      let format = Self.format(language)
      #expect(
        format.length(metres: 12.5).contains("12"), "\(language): \(format.length(metres: 12.5))")
      #expect(format.length(metres: 12.5).hasSuffix("m"), "\(language) converted metres")
      #expect(!format.temperature(celsius: 26.5).contains("F"), "\(language) converted Celsius")
      #expect(format.temperature(celsius: 26.5).contains("C"))
      // Kilometres too: the browser renders km in every locale, so a phone showing miles would
      // disagree with it about the same pool.
      #expect(format.distance(kilometres: 3.2).hasSuffix("km"), "\(language) converted km")
    }
  }

  @Test("the currency symbol goes where the locale puts it")
  func currencyPosition() {
    // CHF 8.00 in en-GB and the three Swiss locales, 8,00 CHF in Polish. This is exactly the
    // reason a price is a formatted VALUE and not a "{amount} CHF" catalog entry: no translator
    // should be asked to know where the symbol goes, and `Intl`/`FormatStyle` already do.
    for language in [Language.en, .de, .fr, .it] {
      #expect(Self.format(language).money(chf: 8).hasPrefix("CHF"), "\(language)")
    }
    #expect(Self.format(.pl).money(chf: 8).hasSuffix("CHF"))
    #expect(Self.format(.pl).money(chf: 8).contains("8,00"))
  }

  @Test("a duration is spelled out by the platform, never by a plural catalog entry")
  func durationsUseTheirOwnUnits() {
    // Polish is the reason: its `other` category is the FRACTION form and, for a feminine noun,
    // is spelled the same as `few` ("1,5 minuty" / "2 minuty"). A catalog entry would need two
    // identical forms, which the web's own parity test reads as a copy-paste. `Duration` knows
    // the rules and needs no entry at all.
    #expect(Self.format(.en).minutes(45).contains("45"))
    #expect(Self.format(.en).minutes(45).lowercased().contains("minute"))
    #expect(Self.format(.de).minutes(45).contains("Minuten"))
    #expect(Self.format(.pl).minutes(45).contains("minut"))
    // ...and the Polish forms really do differ with the count, which is the whole point.
    #expect(Self.format(.pl).minutes(45) != Self.format(.pl).minutes(2))
  }

  @Test("a month outside the year is shown as a number, never as an invented name")
  func monthNameDegradesHonestly() {
    #expect(Self.format(.en).monthName(1) == "January")
    #expect(Self.format(.en).monthName(12) == "December")
    #expect(Self.format(.en).monthName(13) == "13")
    #expect(Self.format(.en).monthName(0) == "0")
  }
}
