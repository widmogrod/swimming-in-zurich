// LocalizedTests.swift — S4 acceptance 3c: the two halves of a lookup, made permanent.
//
// The plan required a PROBE before anything was built on `String(localized:locale:)`, because
// Apple documents that parameter as "This doesn't change which locale the system uses to look
// up the localized string" and says nothing about whether it drives plural SELECTION. The probe
// was run at n = 1, 2, 5, 22 and 1.5; this file is what it found, turned into assertions, so
// the findings cannot quietly stop being true under a later SDK.
//
// WHAT THE PROBE FOUND, in the order it matters:
//
//  1. `String(localized:)` does not expand a plural AT ALL. A catalog entry with variations
//     compiles to a `.stringsdict` whose value is the token `%#@value@`, and
//     `String(localized:)` hands that token straight back. Every message here therefore goes
//     through `String(format:)`, plural or not.
//  2. The BUNDLE chooses the language and the `locale:` chooses the plural rule, and they are
//     genuinely independent. Polish template + `locale: en` gives Polish words with English
//     grammar; English template + `locale: pl` gives English words selected by Polish rules.
//     Getting one right and not the other is worse than getting both wrong, because it looks
//     translated.
//  3. `%lld` and a fractional count do not mix: passing 1.5 to a `%lld` variable reinterprets
//     the double's bits and prints an astronomical integer. So Polish's `other` category — the
//     FRACTION form — is unreachable from this app, which is why `CatalogTests`'s runtime check
//     asserts a subset rather than an equality.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Rendering a message")
struct LocalizedTests {
  /// The numbers the probe used, and the Polish category each selects. 22 is the one a
  /// hand-rolled `n >= 5 ? many` rule gets wrong — Polish takes `few` for 22 — which is why
  /// `plurals.ts` delegates to the platform and why this app does too.
  static let polishCategories: [(Int, String)] = [
    (1, "one"), (2, "few"), (5, "many"), (22, "few"),
  ]

  @Test("the reader's language AND the reader's plural rules, both")
  func bundleAndLocaleAreBothHonoured() {
    let polish = CatalogFixture.localized(.pl)
    let rendered = Self.polishCategories.map { count, _ in
      polish(Message("basin.laneCount", count: count)).filter { !$0.isNumber }
    }
    // Polish words: the bundle chose the language.
    #expect(rendered.allSatisfy { $0.contains("tor") }, "\(rendered)")
    // Polish grammar: 1 and 22 take `few`-family forms distinct from 5's `many`.
    #expect(rendered[0] != rendered[1], "1 and 2 must not share a form")
    #expect(rendered[1] != rendered[2], "2 (few) and 5 (many) must not share a form")
    #expect(rendered[1] == rendered[3], "22 takes `few` in Polish, like 2 — not `many`")
  }

  @Test("every language selects its own forms for the same counts")
  func eachLanguageUsesItsOwnRules() {
    // The shape of the failure this catches: a renderer that passed `Locale.current` (as
    // `String.localizedStringWithFormat` does) would give every language ENGLISH plural
    // selection — two forms — and Polish would read as broken to a Pole and fine to everyone
    // else, including whoever wrote the code.
    var formsPerLanguage: [Language: Int] = [:]
    for (language, localized) in CatalogFixture.all {
      // The DIGITS are stripped: "1 lane" and "2 lanes" differ in their number as well as
      // their form, and counting whole strings would report four forms for English.
      let forms = Set(
        [1, 2, 5, 22].map { count in
          localized(Message("basin.laneCount", count: count)).filter { !$0.isNumber }
        })
      formsPerLanguage[language] = forms.count
    }
    #expect(formsPerLanguage[.en] == 2, "en: one/other")
    #expect(formsPerLanguage[.de] == 2, "de: one/other")
    // fr and it reach only one/other from these four integers — their `many` is the
    // large-number form (10^6 and up), which `CatalogTests` probes separately.
    #expect(formsPerLanguage[.fr] == 2)
    #expect(formsPerLanguage[.it] == 2)
    #expect(formsPerLanguage[.pl] == 3, "pl: one/few/many are all reachable from 1, 2, 5")
  }

  @Test("a message with no parameters still comes back as a sentence")
  func plainMessagesRender() {
    let english = CatalogFixture.english
    #expect(english(Message("state.closed.noSessions")) == "Closed — no sessions")
    #expect(english(.key("state.closed.noSessions")) == "Closed — no sessions")
  }

  @Test("parameters land in the right slots, whatever order the translation puts them in")
  func parametersArePositional() {
    // The whole reason the converter emits `%1$@`/`%2$@` rather than a bare `%@` stream: a
    // translation may reorder its placeholders, and a positional stream that did not would put
    // the end time where the start time belongs — in one language, silently.
    let message = Message(
      "a11y.blockLabel", ["start": "07:00", "end": "09:00", "access": "Public swim"])
    for (language, localized) in CatalogFixture.all {
      let rendered = localized(message)
      #expect(rendered.contains("07:00"), "\(language): \(rendered)")
      #expect(rendered.contains("09:00"), "\(language): \(rendered)")
      #expect(rendered.contains("Public swim"), "\(language): \(rendered)")
      // ...and in the right ORDER, which is the half a "contains" check alone would miss.
      let start = try? #require(rendered.range(of: "07:00"))
      let end = try? #require(rendered.range(of: "09:00"))
      if let start, let end { #expect(start.lowerBound < end.lowerBound, "\(language)") }
    }
  }

  @Test("an unknown key renders as ITSELF, never as a blank")
  func unknownKeysAreVisible() {
    // A store S5 downloads can be built by a newer export and name a message this binary's
    // catalog does not carry. A key on screen is ugly and true; a blank line is a silent lie,
    // and on this app's screens a blank line reads as "closed".
    #expect(CatalogFixture.english(Message("no.such.key")) == "no.such.key")
  }

  @Test("a verbatim wording is never looked up")
  func verbatimIsPassedThrough() {
    // The pool's own words. If this were ever routed through the catalog, a closure notice
    // that happened to match a key would be replaced by our sentence — a client inventing a
    // fact, which is the failure `Wording` exists to make impossible.
    #expect(CatalogFixture.localized(.de)(.verbatim("status.closed")) == "status.closed")
    #expect(
      CatalogFixture.english(.verbatim("Geschlossen bis 23. August"))
        == "Geschlossen bis 23. August")
  }

  @Test("a joined wording is a LIST, with each part localised before the join")
  func joinedWordingsLocaliseEachPart() {
    let german = CatalogFixture.localized(.de)
    let joined = Wording.joined([.key("admission.free"), .verbatim("Hallenbad City")])
    let rendered = german(joined)
    #expect(rendered.hasSuffix("Hallenbad City"))
    #expect(rendered.contains(", "))
    #expect(rendered != german(.key("admission.free")))
    // Each part is a whole clause; nothing here depends grammatically on anything else.
    #expect(rendered.hasPrefix(german(.key("admission.free"))))
  }

  // MARK: - The locale seam

  @Test("the language comes from the reader's preferences, and falls back to English")
  func localeResolution() {
    #expect(AppLocale.resolved(preferring: ["pl-PL", "en"]).language == .pl)
    // A regional variant we have no catalog for still gets the right LANGUAGE: a de-AT reader
    // reads German and, because this app is about Zürich, sees Swiss prices and Swiss dates.
    #expect(AppLocale.resolved(preferring: ["de-AT"]).language == .de)
    #expect(AppLocale.resolved(preferring: ["de-AT"]).formatting.identifier == "de_CH")
    // A language with no catalog falls back rather than half-translating a screen.
    #expect(AppLocale.resolved(preferring: ["ja-JP", "ko"]).language == .en)
    #expect(AppLocale.resolved(preferring: []).language == .en)
    // ...and the fallback is English by construction, as `plurals.ts` has it.
    #expect(Language.fallback == .en)
  }
}
