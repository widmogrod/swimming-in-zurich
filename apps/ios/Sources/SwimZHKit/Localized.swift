// Localized.swift — every sentence this app says, as a KEY rather than as English.
//
// The rule the whole package is built on ("a rule in a view is a rule nothing measures")
// applied to language: a `Text("Closed — no sessions")` in a `body` is an English string
// nothing can translate and nothing can check. So the rule layer stops producing prose and
// starts producing `Message` values — a catalog key plus its interpolation parameters — and
// exactly one place turns a `Message` into words.
//
// THE TWO HALVES OF A LOOKUP, and getting one right is not enough.
// Foundation splits the job across two inputs that are easy to confuse:
//
//   * the BUNDLE decides which LANGUAGE's strings are read. `String(localized:locale:)` does
//     NOT: Apple documents that parameter as "This doesn't change which locale the system uses
//     to look up the localized string", and a probe confirmed it — asking for `pl` while
//     reading the module bundle returns the English text.
//   * the `locale:` of `String(format:locale:)` decides which PLURAL RULE selects the form.
//     Measured on the same probe: with the Polish template and `locale: pl`, n = 1/2/5/22 give
//     one/few/many/few, which is correct Polish; with `locale: en` all four give `other`, and
//     `String.localizedStringWithFormat` (which uses the CURRENT locale) does the same.
//
// Set only the bundle and Polish is rendered with English grammar. Set only the locale and it
// is English rendered by Polish rules. `Localized` sets both, from one `AppLocale`, which is
// why no call site may reach for `String(localized:)` on its own.
//
// A THIRD trap, also probed: `String(localized:)` never expands a plural at all. A catalog
// entry with variations compiles to a `.stringsdict` whose value is the token `%#@value@`;
// `String(localized:)` hands that token back verbatim. Only `String(format:)` expands it, so
// every message — plural or not — goes through the same `String(format:)` path here.

import Foundation

// MARK: - What the reader gets

/// The five languages this product speaks, as a closed set.
///
/// Closed on purpose: `Locale.preferredLanguages` can name any language on earth, and the
/// honest answer for one we have no catalog for is the fallback, not a half-translated screen.
public enum Language: String, CaseIterable, Equatable, Hashable, Sendable {
  case en
  case de
  case fr
  case it
  case pl

  /// `en` is BOTH the source language and the fallback, exactly as `plurals.ts` has it.
  public static let fallback: Language = .en
}

/// The reader's language, and the REGIONAL locale their numbers and dates are formatted in.
///
/// The two are deliberately different values. The web pins the same split in `datefmt.ts` and
/// the reason is that bare `en` means en-US, which would flip every date to month-first for a
/// Zürich audience. So the formatting locales are regional: en-GB, de-CH, fr-CH, it-CH, and
/// plain `pl` (Poland is the only region Polish is spoken in here).
///
/// The consequences are counter-intuitive and are pinned by test rather than assumed, because
/// Apple ships its own ICU snapshot and CLDR is not a promise about a given OS build: de-CH,
/// it-CH AND fr-CH all use a DOT decimal separator here — unlike de-DE and it-IT, and unlike
/// node's ICU, which gives fr-CH a comma (see `Format.swift`'s header and CLAUDE.md) — `pl` is
/// the one locale here that uses a comma, and the Swiss GROUP separator is an ASCII apostrophe
/// (U+0027), not U+2019.
public struct AppLocale: Equatable, Hashable, Sendable {
  public let language: Language
  /// The locale every number, date, measurement and price is formatted in.
  public let formatting: Locale

  public init(_ language: Language) {
    self.language = language
    self.formatting = Locale(identifier: Self.formattingIdentifier(for: language))
  }

  static func formattingIdentifier(for language: Language) -> String {
    switch language {
    case .en: return "en_GB"
    case .de: return "de_CH"
    case .fr: return "fr_CH"
    case .it: return "it_CH"
    case .pl: return "pl"
    }
  }

  /// The `AppLocale` for a list of BCP-47 preferences, as `Locale.preferredLanguages` gives it.
  ///
  /// Matched on the language subtag alone: a reader whose phone is set to `de-AT` or `de-DE`
  /// gets the German catalog and Swiss formatting, which is right — the app is about Zürich,
  /// so its prices are Swiss francs and its dates Swiss whoever is reading.
  public static func resolved(preferring preferences: [String]) -> AppLocale {
    for preference in preferences {
      let subtag = Locale(identifier: preference).language.languageCode?.identifier
      if let subtag, let language = Language(rawValue: subtag) { return AppLocale(language) }
    }
    return AppLocale(.fallback)
  }

  /// The reader's own preference, as the system reports it.
  public static var current: AppLocale { resolved(preferring: Locale.preferredLanguages) }
}

// MARK: - A sentence, before it is a sentence

/// One thing to say: a catalog key, its named parameters, and — for a plural entry — the
/// number the grammar selects on.
///
/// The parameters are NAMED rather than ordered because the compiled catalog is positional and
/// a translation reorders freely: "opens {hhmm}" and "um {hhmm} geöffnet" put the same value in
/// different places, and a two-argument message passed as an array would be a coin flip. The
/// name→position mapping lives in `Catalog.generated.swift`, written by the same converter
/// pass that numbered the specifiers.
///
/// Values are already-formatted STRINGS (a time, a place, a price), never raw numbers: how a
/// number reads is `Format`'s job and depends on the regional locale, which the catalog knows
/// nothing about. The one exception is `count`, which must reach Foundation as an integer or
/// no plural rule can select on it.
public struct Message: Equatable, Hashable, Sendable {
  public let key: String
  public let params: [String: String]
  /// The plural-selecting count. Nil for every non-plural message.
  public let count: Int?

  public init(_ key: String, _ params: [String: String] = [:], count: Int? = nil) {
    self.key = key
    self.params = params
    self.count = count
  }
}

/// Something to show: either OUR words (a catalog message) or SOMEBODY ELSE'S, passed through.
///
/// This union is the type-level form of a rule this project already had in prose and had
/// already broken once: a pool's own closure notice, a basin's name, an unclassified closure
/// text and a curated price line are the SOURCE's words, and translating them is how a client
/// invents a fact. Making it an enum means a surface that mixes the two (a facility sheet row
/// whose label is ours and whose value is the pool's) cannot lose track of which is which, and
/// a test can assert that a given field is never `.message`.
public indirect enum Wording: Equatable, Hashable, Sendable {
  case message(Message)
  case verbatim(String)
  /// Several independent clauses shown as a VISUAL LIST, joined by ", ".
  ///
  /// Not a sentence built from fragments — that is the thing this project forbids, because word
  /// order differs per language. Each part stands on its own ("CHF 2.00", "per day",
  /// "deposit CHF 5.00"); the comma is punctuation, and a translator may reorder inside a part
  /// freely. It is the same distinction the web's middot-joined `insight.*` clauses make.
  case joined([Wording])

  /// A message with no parameters, written as its key — the common case.
  public static func key(_ key: String) -> Wording { .message(Message(key)) }
}

extension Localized {
  /// `wording`, in words: the catalog for ours, verbatim for theirs.
  public func string(_ wording: Wording) -> String {
    switch wording {
    case .message(let message): return string(message)
    case .verbatim(let text): return text
    case .joined(let parts): return parts.map { string($0) }.joined(separator: ", ")
    }
  }

  public func callAsFunction(_ wording: Wording) -> String { string(wording) }
}

// MARK: - The catalog

/// The compiled message catalog. `entries` is generated; this is its home and its bundle.
public enum Catalog {
  /// The bundle the compiled `.xcstrings` lives in.
  ///
  /// `Bundle.module` is the answer in the app, where Xcode compiles the package's string
  /// catalog into `en.lproj`/`de.lproj`/… inside the resource bundle. It is NOT the answer
  /// under `swift test`: SwiftPM does not run `xcstringstool` (verified — the raw
  /// `.xcstrings` is copied through and `Bundle.module.localizations` reports only `en`), so
  /// the package tests compile the catalog themselves and inject the result. Hence the
  /// injectable `bundle` on `Localized` rather than a hard reference here.
  public static let bundle = Bundle.module

  /// Whether `bundle` actually carries compiled translations. False under `swift test`, true
  /// in the app — and a test asserts the app-side expectation rather than trusting it.
  public static func isCompiled(_ bundle: Bundle) -> Bool {
    bundle.localizations.count > 1
  }
}

// MARK: - Rendering

/// Turns a `Message` into words, in one language, with that language's plural rules.
///
/// `Bundle` is not `Sendable`, but `localizedString(forKey:value:table:)` is a read of an
/// immutable, already-loaded table; the box below states that rather than leaving the whole
/// type main-actor-bound, which would stop a model being built off the main thread.
public struct Localized: @unchecked Sendable {
  public let locale: AppLocale
  /// The value formatter for the same reader. It rides along because the two are always used
  /// together — a message's parameters are formatted values — and a call site that took only
  /// one of them would be free to format a number in a locale the words are not in.
  public let format: Format
  private let bundle: Bundle

  /// - Parameter bundle: the bundle holding the compiled catalog. The default is the package's
  ///   own, which is correct in the app; the tests pass a bundle they compiled themselves.
  public init(locale: AppLocale, bundle: Bundle = Catalog.bundle) {
    self.locale = locale
    self.format = Format(locale)
    // The LANGUAGE-specific sub-bundle, not the umbrella one. Reading the umbrella bundle
    // resolves through `Bundle.preferredLocalizations`, which follows the DEVICE's language
    // list — so a reader who has chosen French inside the app would still be served German
    // because their phone is German. Resolving the `.lproj` ourselves is what makes the
    // language an app-level choice rather than a device-level one.
    if let path = bundle.path(forResource: locale.language.rawValue, ofType: "lproj"),
      let localized = Bundle(path: path)
    {
      self.bundle = localized
    } else {
      self.bundle = bundle
    }
  }

  /// The reader's language, with the package's compiled catalog.
  public static var current: Localized { Localized(locale: .current) }

  /// `message`, in words.
  ///
  /// An unknown key renders as ITSELF rather than as a blank or a crash. That is the same
  /// stance `DayWarning` and `dayStateLabel` take for an unrecognised code: a store built by a
  /// newer export can name a message this binary's catalog does not carry, and a key on screen
  /// is ugly but true, where a blank is a silent lie. `UILintTests` and `CatalogTests` are what
  /// stop that path being reached in practice.
  public func callAsFunction(_ message: Message) -> String {
    string(message)
  }

  /// Render a key the generated table does NOT describe, with one integer argument.
  ///
  /// Internal, and there is exactly one caller: `CatalogTests`' plural probe, which compiles a
  /// throwaway catalog of its own to ask ICU which category it selects for a number. That
  /// catalog cannot be in `Catalog.entries` — it is not part of the app — so the ordinary path
  /// would (correctly) return the key. The probe is the reason this exists; nothing in the app
  /// may use it, because a key outside the table is a key the converter never wrote.
  func renderUntabulated(_ key: String, count: Int) -> String {
    String(
      format: bundle.localizedString(forKey: key, value: key, table: nil),
      locale: locale.formatting, arguments: [count])
  }

  public func string(_ message: Message) -> String {
    guard let entry = Catalog.entries[message.key] else { return message.key }
    let template = bundle.localizedString(forKey: message.key, value: message.key, table: nil)
    var arguments: [any CVarArg] = []
    for parameter in entry.parameters {
      switch parameter.kind {
      case .integer:
        // Only ever the plural count: it is the one argument Foundation must see as a number,
        // because the category is selected from it.
        arguments.append(message.count ?? 0)
      case .text:
        arguments.append(message.params[parameter.name] ?? "")
      }
    }
    // ALWAYS through `String(format:)`, even with no arguments: a plural entry's compiled
    // value is the token `%#@value@` and only this call expands it, and a message containing a
    // literal percent sign was escaped to `%%` by the converter and is unescaped here.
    return String(format: template, locale: locale.formatting, arguments: arguments)
  }
}
