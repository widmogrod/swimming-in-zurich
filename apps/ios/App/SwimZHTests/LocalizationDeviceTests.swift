// LocalizationDeviceTests.swift — S4 acceptance 4, on the device's own ICU.
//
// `FormatTests` in the package asserts the same facts, and that is not a duplicate: it runs on
// the HOST's ICU under `swift test`, and this runs inside the simulator, on the ICU the phone
// ships. The plan named the distinction explicitly ("Apple ships its own ICU snapshot, so a
// simulator test re-checks them rather than assuming parity"), and it was right to: the two
// platforms this project already builds on — node and macOS Foundation — turned out to
// disagree about the decimal separator for French Switzerland.
//
// The other thing this file proves, and only an app bundle can: that the PACKAGE's string
// catalog was actually compiled into the app. SwiftPM does not run `xcstringstool`; Xcode
// does. If that ever stopped being true the package tests would still pass — they compile the
// catalog themselves — and every screen would render raw keys.

import Foundation
import Testing

@testable import SwimZH
@testable import SwimZHKit

@Suite("Localisation, in the simulator")
struct LocalizationDeviceTests {
  @Test("the package's catalog reached the app bundle, in all five languages")
  func theCatalogIsCompiledIntoTheApp() {
    // The claim `CatalogFixture` cannot make. It compiles the `.xcstrings` itself, so a build
    // that never compiled the catalog into the shipped bundle would leave every package test
    // green and every screen showing keys.
    let bundle = Catalog.bundle
    #expect(Catalog.isCompiled(bundle), "Bundle.module carries \(bundle.localizations)")
    for language in Language.allCases {
      #expect(
        bundle.localizations.contains(language.rawValue),
        "the app bundle has no \(language.rawValue) — found \(bundle.localizations.sorted())")
    }
  }

  @Test("a message renders in each language, from the app's own bundle")
  func messagesRenderOnDevice() {
    for language in Language.allCases {
      let localized = Localized(locale: AppLocale(language))
      let rendered = localized(Message("state.closed.noSessions"))
      #expect(rendered != "state.closed.noSessions", "\(language) fell back to the key")
      #expect(!rendered.isEmpty)
    }
    // ...and they are genuinely different sentences, so this cannot pass with one language
    // installed and four aliases of it.
    let all = Set(
      Language.allCases.map { Localized(locale: AppLocale($0))(Message("state.closed.noSessions")) }
    )
    #expect(all.count == Language.allCases.count, "languages collapsed to \(all)")
  }

  @Test("Polish plural rules select on device, at 1, 2, 5 and 22")
  func polishPluralsSelectOnDevice() {
    // 22 is the number a hand-rolled `n >= 5 ? many` rule gets wrong: Polish takes `few` there,
    // like 2. If the device's ICU ever disagreed with the host's about this, the app would ship
    // grammar no test on a Mac could see.
    let polish = Localized(locale: AppLocale(.pl))
    let forms = [1, 2, 5, 22].map { count in
      polish(Message("basin.laneCount", count: count)).filter { !$0.isNumber }
    }
    #expect(forms[0] != forms[1], "1 and 2 share a form")
    #expect(forms[1] != forms[2], "2 (few) and 5 (many) share a form")
    #expect(forms[1] == forms[3], "22 must take `few`, like 2")
  }

  @Test("the decimal separator and the Swiss group separator, on the device's ICU")
  func separatorsOnDevice() {
    // The two facts acceptance 4 names, re-measured here. `FormatTests` records that Apple's
    // ICU gives fr-CH a DOT where node gives a comma; if the simulator ever disagreed with the
    // host, THIS is where it would show up, and the message says which side moved.
    for language in [Language.en, .de, .fr, .it] {
      #expect(
        Format(AppLocale(language)).number(2.5, fractionDigits: 1) == "2.5",
        "\(language) on device: \(Format(AppLocale(language)).number(2.5, fractionDigits: 1))")
    }
    #expect(Format(AppLocale(.pl)).number(2.5, fractionDigits: 1) == "2,5")
    // U+0027, not U+2019.
    for language in [Language.de, .fr, .it] {
      #expect(Format(AppLocale(language)).integer(1_234_567) == "1'234'567", "\(language)")
    }
  }

  @Test("Polish takes a genitive lower-case month on device too")
  func polishGenitiveMonthOnDevice() {
    var components = DateComponents()
    components.year = 2026
    components.month = 7
    components.day = 23
    components.hour = 12
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = ZurichClock.timeZone
    let july23 = calendar.date(from: components)!
    let full = Format(AppLocale(.pl)).dayParts(july23).full
    #expect(full.contains("lipca"), "genitive month lost on device: \(full)")
    #expect(!full.contains("Lipca"), "the device capitalised the month: \(full)")
  }
}
