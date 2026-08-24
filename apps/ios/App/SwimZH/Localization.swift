// Localization.swift — the ONE place a `Message` becomes a `Text`.
//
// The rule this file exists to keep is the one every other file in the app target already
// keeps: nothing here decides anything. A view asks for `Text(row.verdict.head)` and gets the
// reader's language; it never picks a key, never formats a number, never joins two clauses.
//
// WHY NOT `Text("some.key")` DIRECTLY. SwiftUI resolves a `LocalizedStringKey` against
// `Bundle.main`, and the catalog lives in the PACKAGE's bundle (the plan puts it there so
// `swift test` can assert against it without `xcodebuild`). A literal key in a `Text` would
// therefore render as the raw key on every screen — silently, because a raw key is a
// perfectly valid string. Everything goes through `SwimZHKit.Localized`, which resolves the
// language sub-bundle itself, and `UILintTests` asserts there are no bare literals left in a
// `LocalizedStringKey` position.
//
// `Text(verbatim:)` is the initialiser that says "this string is NOT a key". It is right here,
// because the string has already been localised on the line above and letting SwiftUI look it
// up again would treat a rendered sentence as a key. It is right in a handful of other places
// too — a pool's name, a formatted distance, a time range — and wrong everywhere else, and the
// two cases look identical in a diff. So every site in the app target is named in
// `apps/ios/verbatim-allowlist.json` with the reason it is a value, and
// `UILintTests.verbatimTextIsAllowlisted` fails on any site that file does not list.

import SwiftUI
import SwimZHKit

extension EnvironmentValues {
  /// The reader's renderer. Injected once, at the root, so no view constructs its own — a
  /// second `Localized` would be a second chance to disagree about which language this is.
  @Entry var localized: Localized = .current
}

extension Text {
  /// A catalog message, in the reader's language.
  init(_ message: Message, _ localized: Localized) {
    self.init(verbatim: localized(message))
  }

  /// Our words or the source's, whichever this is.
  init(_ wording: Wording, _ localized: Localized) {
    self.init(verbatim: localized(wording))
  }
}

extension Label where Title == Text, Icon == Image {
  /// The `Label` shape the toolbar and section headers use.
  init(_ message: Message, systemImage: String, _ localized: Localized) {
    self.init {
      Text(message, localized)
    } icon: {
      Image(systemName: systemImage)
    }
  }
}
