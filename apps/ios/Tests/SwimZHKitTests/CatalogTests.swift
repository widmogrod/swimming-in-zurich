// CatalogTests.swift — S4 acceptance 1, 3b, 3c and 4b: the catalog itself.
//
// Three different kinds of claim live here, and they are kept apart on purpose:
//
//   * the FILE is complete and well shaped (every key in all five languages, plural categories
//     exactly the CLDR set, no placeholder invented or dropped). These read the `.xcstrings`
//     JSON and never render anything.
//   * the RUNTIME resolves what the file promises — including the two-halves trap that makes
//     plural selection work only when the bundle AND the locale are both set.
//   * the WORDING obeys the rules iOS 26 and this product impose (no ALL-CAPS headers, no
//     English left in a non-English catalog).
//
// What is deliberately NOT here: "every key in `locales/en.ts` reaches the catalog". That is a
// claim about a TypeScript module, and re-parsing TypeScript from Swift would be a second,
// worse parser. It is asserted where the projection is made instead —
// `node scripts/locales_to_xcstrings.mjs --check` regenerates from `dist/locales/*.js` and
// diffs, and `tests/scripts/test_locales_to_xcstrings.py` runs it. The two halves together are
// acceptance 1: the converter proves the file MATCHES the web catalogs, and this file proves
// the catalog is complete in itself.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The message catalog")
struct CatalogTests {
  /// The CLDR categories each locale uses — the SAME table `plurals.ts:23-31` declares and
  /// `plurals.test.ts` asserts against `Intl.PluralRules`. Written out a third time here (the
  /// second copy is the build phase's `xcstrings_plural_gate.py`) because this test must run
  /// with no node and no Python, and `pluralCategoriesMatchTheRuntime` below pins it against
  /// Foundation's own ICU so all three cannot drift together.
  static let cldrCategories: [Language: Set<String>] = [
    .en: ["one", "other"],
    .de: ["one", "other"],
    .fr: ["one", "many", "other"],
    .it: ["one", "many", "other"],
    .pl: ["one", "few", "many", "other"],
  ]

  // MARK: - Acceptance 1: the file is complete

  @Test("every key carries all five languages")
  func everyKeyIsFullyLocalised() throws {
    let strings = try CatalogFixture.strings()
    #expect(strings.count > 200, "the catalog looks truncated: \(strings.count) keys")
    let expected = Set(Language.allCases.map(\.rawValue))
    for (key, value) in strings {
      let entry = try #require(value as? [String: Any], "\(key) is not an object")
      let localizations = try #require(
        entry["localizations"] as? [String: Any], "\(key) has no localizations")
      let missing = expected.subtracting(Set(localizations.keys))
      #expect(missing.isEmpty, "\(key) is missing \(missing.sorted())")
    }
  }

  @Test("the generated Swift table describes exactly the keys the catalog carries")
  func generatedTableMatchesTheCatalog() throws {
    // `Catalog.entries` and `Localizable.xcstrings` are two outputs of ONE converter pass, so
    // a difference between them means somebody edited one by hand — and the failure that
    // causes is silent: an argument numbered against a table that no longer describes the
    // format string puts the wrong value in the wrong slot.
    let fileKeys = Set(try CatalogFixture.strings().keys)
    let tableKeys = Set(Catalog.entries.keys)
    #expect(
      tableKeys == fileKeys,
      "table only: \(tableKeys.subtracting(fileKeys).sorted()), catalog only: \(fileKeys.subtracting(tableKeys).sorted())"
    )
  }

  @Test("no message renders as its own key in any language")
  func nothingFallsBackToItsKey() throws {
    // The quiet failure mode: a key the catalog does not carry comes back as ITSELF, which on
    // screen looks like a design choice rather than a missing string. Every key, every
    // language, no exceptions — this is the broadest net in the suite.
    for (language, localized) in CatalogFixture.all {
      for (key, entry) in Catalog.entries {
        let message = Message(
          key,
          Dictionary(uniqueKeysWithValues: entry.parameters.map { ($0.name, "X") }),
          count: entry.isPlural ? 2 : nil)
        let rendered = localized(message)
        #expect(rendered != key, "\(language) has no translation for \(key)")
        #expect(!rendered.isEmpty, "\(language)/\(key) renders empty")
      }
    }
  }

  @Test("every parameter the English uses survives into every language")
  func noTranslationDropsAValue() throws {
    // The web's `parity.test.ts` makes this claim about `{name}` placeholders; this is the
    // same claim about what they COMPILED to. A dropped `%1$@` type-checks nowhere and fails
    // nothing — it simply prints a sentence with a hole where the time was.
    let strings = try CatalogFixture.strings()
    for (key, entry) in Catalog.entries where !entry.parameters.isEmpty {
      let value = try #require(strings[key] as? [String: Any])
      let localizations = try #require(value["localizations"] as? [String: Any])
      for language in Language.allCases {
        let unit = try #require(localizations[language.rawValue] as? [String: Any])
        for form in Self.forms(of: unit) {
          for (index, parameter) in entry.parameters.enumerated() {
            let specifier = "%\(index + 1)$\(parameter.kind == .integer ? "lld" : "@")"
            #expect(
              form.contains(specifier),
              "\(language)/\(key) dropped \(parameter.name) (\(specifier)): \(form)")
          }
        }
      }
    }
  }

  // MARK: - Acceptance 3b: the plural categories conform

  @Test("plural entries carry EXACTLY the categories their locale uses")
  func pluralCategoriesConform() throws {
    // Equality, not containment. A missing category falls back to `other` — which in Polish is
    // the DECIMAL form, so "5 basenu" where "5 basenów" belongs. An EXTRA one is a form the
    // language never selects: a translation written and never shown.
    let strings = try CatalogFixture.strings()
    var pluralKeys = 0
    for (key, value) in strings {
      let entry = try #require(value as? [String: Any])
      let localizations = try #require(entry["localizations"] as? [String: Any])
      for language in Language.allCases {
        let unit = try #require(localizations[language.rawValue] as? [String: Any])
        guard let variations = unit["variations"] as? [String: Any] else { continue }
        let plural = try #require(
          variations["plural"] as? [String: Any], "\(key)/\(language): variations with no plural")
        pluralKeys += 1
        #expect(
          Set(plural.keys) == Self.cldrCategories[language],
          "\(key)/\(language) carries \(Set(plural.keys).sorted())")
      }
    }
    // ...and the loop really found plurals, so it cannot pass by scanning none.
    #expect(pluralKeys >= 5 * Language.allCases.count, "only \(pluralKeys) plural localizations")
  }

  @Test("the CLDR table is the platform's, not a guess")
  func pluralCategoriesMatchTheRuntime() throws {
    // `plurals.ts` asserts its table against `Intl.PluralRules`; this asserts the Swift-side
    // copy against Foundation's own ICU. Without it the three copies of this table (here,
    // `plurals.ts`, `scripts/xcstrings_plural_gate.py`) could drift TOGETHER and stay
    // self-consistent while all three were wrong — which is exactly what happened to fr and it
    // when CLDR 42 gave them a `many` category.
    //
    // Foundation exposes no plural-rule API, so the platform is asked the only way it answers:
    // a throwaway catalog carrying ALL SIX CLDR categories per language is compiled with the
    // same `xcstringstool` the real one uses, and the form that comes back for `n` names the
    // category ICU selected.
    //
    // THE ASSERTION IS NOT EQUALITY, and the reason is a real limitation rather than a
    // hedge: `other` in Polish is the FRACTION form ("1,5 basenu"), and an integer count can
    // never select it — `%lld` has no fractional value to offer. So the two halves are: no
    // integer ever selects a category the table does not declare (which would mean a form the
    // app never wrote), and nothing the table declares is unreachable EXCEPT that fraction
    // form.
    // ZERO IS NOT PROBED, and finding out why was worth the detour: Foundation's
    // `.stringsdict` treats a `zero` key as a LITERAL "if the number is 0" special case, not as
    // the CLDR category. Measured here — a probe catalog carrying `zero` returns it for n = 0 in
    // all five languages, including English and Polish, neither of which has a CLDR `zero`
    // category at all. So a `zero` form would be an Apple extension this catalog deliberately
    // does not use (the web has no equivalent, and a phone that said "no lanes" where the
    // browser said "0 lanes" would be a second vocabulary).
    let probes = [1, 2, 3, 5, 11, 21, 22, 101, 1_000_000]
    for (language, declared) in Self.cldrCategories {
      let localized = try Self.probeRenderer(language)
      var observed: Set<String> = []
      for probe in probes {
        let rendered = localized.renderUntabulated(Self.probeKey, count: probe)
        let category = String(rendered.prefix { $0 != " " })
        observed.insert(category)
      }
      #expect(
        observed.isSubset(of: declared),
        "\(language): ICU selects \(observed.subtracting(declared).sorted()), undeclared")
      #expect(
        declared.subtracting(observed).isSubset(of: ["other"]),
        "\(language): declares \(declared.subtracting(observed).sorted()), unreachable")
    }
  }

  static let probeKey = "probe.category"

  /// Every CLDR category a language here could use. `zero` is deliberately absent — see the
  /// probe above: in a `.stringsdict` it is Apple's literal-zero special case rather than a
  /// CLDR category, so including it would make the probe report a category that does not exist.
  static let allCldrCategories = ["one", "two", "few", "many", "other"]

  /// A renderer over a THROWAWAY catalog whose every form is its own category's name.
  ///
  /// Built and compiled once per process, like `CatalogFixture.compiled`, because it costs an
  /// `xcstringstool` spawn. It is deliberately not part of the shipped catalog: it exists only
  /// to make ICU state which category it picked.
  static func probeRenderer(_ language: Language) throws -> Localized {
    guard let bundle = Bundle(url: probeBundle) else {
      throw StoreError.malformedRow(table: "probe", detail: "no bundle at \(probeBundle.path)")
    }
    return Localized(locale: AppLocale(language), bundle: bundle)
  }

  static let probeBundle: URL = {
    var localizations: [String: Any] = [:]
    for language in Language.allCases {
      var plural: [String: Any] = [:]
      for category in allCldrCategories {
        plural[category] = [
          "stringUnit": ["state": "translated", "value": "\(category) %lld"]
        ]
      }
      localizations[language.rawValue] = ["variations": ["plural": plural]]
    }
    let document: [String: Any] = [
      "sourceLanguage": "en",
      "version": "1.0",
      "strings": [probeKey: ["extractionState": "manual", "localizations": localizations]],
    ]
    let directory = FileManager.default.temporaryDirectory
      .appending(path: "swimzh-plural-probe-\(ProcessInfo.processInfo.processIdentifier)")
    // Named `Localizable`, not `Probe`: `xcstringstool` names the compiled table after the
    // FILE, and `localizedString(forKey:value:table: nil)` looks only in `Localizable`. A
    // `Probe.stringsdict` compiles perfectly and is never read.
    let source = directory.appending(path: "Localizable.xcstrings")
    let output = directory.appending(path: "compiled")
    do {
      try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
      try JSONSerialization.data(withJSONObject: document, options: [.sortedKeys])
        .write(to: source)
    } catch {
      fatalError("could not write the plural probe: \(error)")
    }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
    process.arguments = [
      "xcstringstool", "compile", "--output-directory", output.path, source.path,
    ]
    let errors = Pipe()
    process.standardError = errors
    try? process.run()
    process.waitUntilExit()
    if process.terminationStatus != 0 {
      let text =
        String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
      fatalError("the plural probe would not compile: \(text)")
    }
    return output
  }()

  // MARK: - Acceptance 4b: iOS 26 no longer shouts

  @Test("no catalog value is written in ALL CAPS")
  func nothingReliesOnTheSystemShouting() throws {
    // iOS 26 renders a section header EXACTLY as it is written; it no longer upper-cases them.
    // A heading authored as "WHERE" because the system used to shout it now shouts on its own,
    // in one language, on one screen — which is the kind of defect nobody files and everybody
    // notices. Audited across ALL five catalogs, and across every value rather than only the
    // headers: a heading is only a heading by where it is used, and this file cannot see that.
    let strings = try CatalogFixture.strings()
    for (key, value) in strings {
      let entry = try #require(value as? [String: Any])
      let localizations = try #require(entry["localizations"] as? [String: Any])
      for (language, unit) in localizations {
        for form in Self.forms(of: try #require(unit as? [String: Any])) {
          let letters = form.filter { $0.isLetter }
          // Six letters, not two: "PDF" and "CHF" are acronyms and are correctly capitalised,
          // and a rule that flagged them would be turned off rather than obeyed.
          guard letters.count >= 6, letters != letters.lowercased() else { continue }
          #expect(
            letters != letters.uppercased(),
            "\(language)/\(key) is written in capitals: \"\(form)\"")
        }
      }
    }
  }

  @Test("no non-English catalog is left as English")
  func everyLanguageIsActuallyTranslated() throws {
    // A weak check, deliberately: a translation MAY legitimately equal the English (a proper
    // noun, a passthrough key whose whole value is a placeholder, "Sauna"). So the assertion is
    // statistical — if most of a language matches English word for word, that catalog was not
    // translated, and the parity gates above would all still be green.
    let strings = try CatalogFixture.strings()
    for language in Language.allCases where language != .en {
      var same = 0
      var total = 0
      for (_, value) in strings {
        guard let entry = value as? [String: Any],
          let localizations = entry["localizations"] as? [String: Any],
          let english = localizations["en"] as? [String: Any],
          let other = localizations[language.rawValue] as? [String: Any]
        else { continue }
        total += 1
        if Self.forms(of: english) == Self.forms(of: other) { same += 1 }
      }
      #expect(total > 0)
      #expect(
        Double(same) / Double(total) < 0.25,
        "\(language) matches English for \(same) of \(total) keys — is it translated?")
    }
  }

  /// Every string form of one localization: one for a plain entry, one per plural category.
  static func forms(of unit: [String: Any]) -> [String] {
    if let stringUnit = unit["stringUnit"] as? [String: Any],
      let value = stringUnit["value"] as? String
    {
      return [value]
    }
    guard let variations = unit["variations"] as? [String: Any],
      let plural = variations["plural"] as? [String: Any]
    else { return [] }
    return plural.values.compactMap { form in
      (form as? [String: Any])?["stringUnit"] as? [String: Any]
    }
    .compactMap { $0["value"] as? String }
    .sorted()
  }
}
