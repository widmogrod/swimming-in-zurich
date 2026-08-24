// CatalogFixture.swift — a REAL compiled catalog for the package's own tests.
//
// SwiftPM does not compile `.xcstrings`. Verified rather than assumed: with the catalog
// declared as a `.process` resource, `swift build` copies the raw JSON into the bundle and
// `Bundle.module.localizations` reports only `["en"]` — no `xcstringstool` invocation appears
// in `debug.yaml` and no `.lproj` is produced. Xcode DOES compile it (that is how the app gets
// its five languages), so without this file every rendering assertion here would have to move
// into the simulator, and `swift test` — the chain step that runs on every push, including on
// a runner with no simulator — would be able to say nothing about what the app says.
//
// So the suite compiles the catalog itself, with the same `xcstringstool` Xcode uses, into a
// temporary bundle it then reads. Two consequences worth stating plainly:
//
//   * this is ALSO the test that the committed `.xcstrings` compiles at all. `xcstringstool`
//     rejects real mistakes — a plural variation whose forms do not interpolate the number is
//     the one that has already been hit here — and a catalog that only ever compiled inside
//     `xcodebuild` would break the app build rather than the package tests.
//   * it needs Xcode's command-line tools, which the Swift chain requires anyway (`swift
//     format`, `xcodebuild`). If `xcstringstool` is missing the fixture FAILS rather than
//     skipping: a silently-skipped localisation suite is how five languages rot.

import Foundation
import Testing

@testable import SwimZHKit

enum CatalogFixture {
  static let source =
    RepoFixtures.root
    .appending(path: "apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings")

  /// The compiled catalog's directory, built ONCE per test process.
  ///
  /// `xcstringstool compile` costs a process spawn, and every suite that renders a message
  /// would otherwise pay it. `nonisolated(unsafe)` on a `let` initialised by a closure is the
  /// same lazy-once pattern `RepoFixtures.root` uses.
  static let compiled: URL = {
    let directory = FileManager.default.temporaryDirectory
      .appending(path: "swimzh-catalog-\(ProcessInfo.processInfo.processIdentifier)")
    try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
    process.arguments = [
      "xcstringstool", "compile", "--output-directory", directory.path, source.path,
    ]
    let errors = Pipe()
    process.standardError = errors
    try? process.run()
    process.waitUntilExit()
    if process.terminationStatus != 0 {
      let text =
        String(
          data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
      // Not a `#expect`: this runs outside a test, and a fixture that failed quietly would make
      // every message render as its own key — which reads like a missing translation rather
      // than like a broken build step.
      fatalError("xcstringstool compile failed: \(text)")
    }
    return directory
  }()

  /// A renderer for `language`, reading the freshly compiled catalog.
  static func localized(_ language: Language) -> Localized {
    guard let bundle = Bundle(url: compiled) else {
      fatalError("no compiled catalog bundle at \(compiled.path)")
    }
    return Localized(locale: AppLocale(language), bundle: bundle)
  }

  /// The English renderer — what the suites that were written against English sentences use,
  /// so their assertions still say what the app says rather than naming a key.
  static let english = localized(.en)

  /// Every language, for the tests that must hold in all five.
  static var all: [(Language, Localized)] {
    Language.allCases.map { ($0, localized($0)) }
  }

  /// The catalog's raw JSON — for the tests that are about the FILE (key parity, plural
  /// categories) rather than about what it renders.
  static func document() throws -> [String: Any] {
    try RepoFixtures.json(at: source)
  }

  static func strings() throws -> [String: Any] {
    guard let strings = try document()["strings"] as? [String: Any] else {
      throw StoreError.malformedRow(table: "Localizable.xcstrings", detail: "no `strings`")
    }
    return strings
  }
}
