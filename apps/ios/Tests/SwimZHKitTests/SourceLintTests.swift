// Source lints — the rules that are decidable from the text and cannot be a runtime test.
//
// Two of this slice's acceptance criteria are about what the code may NOT contain:
// `SQLITE_STATIC` anywhere (a use-after-free waiting for a bind), and a statement pointer
// escaping the actor. The second is a compile-time fact — the public API returns only value
// types — but "compile-time fact" is a claim a future edit can quietly break, so it is
// asserted the same way `apps/web` asserts its own no-`data/`-at-runtime rule: by grepping.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Source lints")
struct SourceLintTests {
  static let sources = RepoFixtures.root.appending(path: "apps/ios/Sources/SwimZHKit")

  /// Every `.swift` file under `directory`, RECURSIVELY.
  ///
  /// Recursion is load-bearing, not tidiness: `contentsOfDirectory` is one level deep, so
  /// the day someone adds `Sources/SwimZHKit/Store/Cursor.swift` it would escape all four
  /// lints below while the "can the lint see the sources" guard still passed on the files
  /// left at the top level.
  static func swiftFiles(under directory: URL) throws -> [(name: String, text: String)] {
    guard
      let walker = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: nil)
    else { return [] }
    var found: [(name: String, text: String)] = []
    for case let url as URL in walker where url.pathExtension == "swift" {
      let relative = url.path.replacingOccurrences(of: directory.path + "/", with: "")
      found.append((relative, try String(contentsOf: url, encoding: .utf8)))
    }
    return found.sorted { $0.name < $1.name }
  }

  static func swiftFiles() throws -> [(name: String, text: String)] {
    try swiftFiles(under: Self.sources)
  }

  /// The app target's own sources. It is not part of the package, so `swift test` never
  /// compiles it — but its text is right there on disk, and the no-network rule has to hold
  /// for it too.
  static func appSwiftFiles() throws -> [(name: String, text: String)] {
    try swiftFiles(under: RepoFixtures.root.appending(path: "apps/ios/App/SwimZH"))
  }

  @Test("the lint can see the sources it is meant to police")
  func sourcesAreVisible() throws {
    let files = try Self.swiftFiles()
    #expect(files.count >= 6, "found \(files.map(\.name))")
    #expect(files.contains { $0.name == "Store.swift" })
    let app = try Self.appSwiftFiles()
    #expect(app.contains { $0.name == "SwimZHApp.swift" }, "found \(app.map(\.name))")
  }

  /// `text` with `//` comments stripped. The headers in this package explain at length why
  /// SQLITE_STATIC is banned, so a lint that matched prose would fire on its own rationale —
  /// and the natural "fix" for that would be to delete the explanation.
  static func code(_ text: String) -> String {
    text.split(separator: "\n", omittingEmptySubsequences: false)
      .map { line -> Substring in
        guard let comment = line.range(of: "//") else { return line }
        return line[line.startIndex..<comment.lowerBound]
      }
      .joined(separator: "\n")
  }

  @Test("SQLITE_STATIC appears in no CODE — every bind is SQLITE_TRANSIENT")
  func noStaticBinds() throws {
    for file in try Self.swiftFiles() {
      #expect(
        !Self.code(file.text).contains("SQLITE_STATIC"),
        "\(file.name) binds with SQLITE_STATIC — a bridged Swift String's buffer is freed before sqlite3_step reads it"
      )
    }
    // ...and the safe destructor is genuinely in use, so the lint above cannot pass simply
    // because nothing binds any more.
    let store = try #require(try Self.swiftFiles().first { $0.name == "Store.swift" })
    #expect(Self.code(store.text).contains("sqliteTransient"))
  }

  @Test("the failed-open path closes the handle sqlite3_open_v2 hands back anyway")
  func failedOpenClosesItsHandle() throws {
    // THIS IS THE WHOLE GUARANTEE for that footgun — there is deliberately no runtime
    // counterpart, because neither metric available on Apple's libsqlite3 can observe the
    // leak (`StoreTests`'s header records the measurements). A grep is a weak proof, so it
    // is made as specific as it can be: the close must be on the error path, there must be
    // a second one for the deinit, and there must be exactly ONE `sqlite3_open_v2` call so
    // a future second open cannot slip past this rule unnoticed.
    let store = try #require(try Self.swiftFiles().first { $0.name == "Store.swift" })
    let code = Self.code(store.text)
    #expect(code.contains("sqlite3_close_v2(candidate)"), "the error path must close the handle")
    // Twice: once on the error path, once in the actor's isolated deinit.
    #expect(code.components(separatedBy: "sqlite3_close_v2").count - 1 >= 2)
    #expect(
      code.components(separatedBy: "sqlite3_open_v2(").count - 1 == 1,
      "a second open path would need its own close, and this lint would not see it"
    )
  }

  @Test("no sqlite3 pointer escapes: the public API returns only value types")
  func noPointerEscapes() throws {
    for file in try Self.swiftFiles() {
      for line in file.text.split(separator: "\n", omittingEmptySubsequences: false) {
        let text = line.trimmingCharacters(in: .whitespaces)
        guard text.hasPrefix("public ") || text.hasPrefix("open ") else { continue }
        for banned in ["OpaquePointer", "sqlite3_", "UnsafeMutablePointer", "UnsafePointer"] {
          if text.contains(banned) {
            Issue.record("\(file.name): public API exposes \(banned) — `\(text)`")
          }
        }
      }
    }
  }

  @Test("the SQLite handle lives in exactly one file, inside the actor")
  func oneFileTouchesSQLite() throws {
    let touching = try Self.swiftFiles().filter { $0.text.contains("import SQLite3") }
    #expect(touching.map(\.name) == ["Store.swift"])
    let store = try #require(try Self.swiftFiles().first { $0.name == "Store.swift" })
    #expect(store.text.contains("public actor Store"), "the handle must live in an actor")
    // The open flags are load-bearing, not decoration: READONLY because the bundle is,
    // NOMUTEX because the actor is the mutex, URI because `immutable=1` needs a URI.
    for flag in ["SQLITE_OPEN_READONLY", "SQLITE_OPEN_NOMUTEX", "SQLITE_OPEN_URI", "immutable=1"] {
      #expect(store.text.contains(flag), "Store.swift no longer opens with \(flag)")
    }
    // The page cache is set explicitly: Apple's build defaults to 2000 PAGES (~8 MB), four
    // times upstream's 2 MB, and inheriting it is the difference between a 30 MB and a
    // 100 MB footprint.
    #expect(store.text.contains("PRAGMA cache_size"))
    #expect(store.text.contains("PRAGMA mmap_size"))
  }

  @Test("the rule layer imports no UI framework")
  func noUIInTheKit() throws {
    for file in try Self.swiftFiles() {
      for banned in ["import SwiftUI", "import UIKit", "import AppKit"] {
        #expect(!file.text.contains(banned), "\(file.name) imports \(banned)")
      }
    }
  }

  @Test("the launch measurement is actually wired into the app, at both ends")
  func launchSignpostIsWired() throws {
    // An instrument nothing calls measures nothing, and this is the exact shape of that
    // failure: `LaunchSignpost` can be green in its own suite while the app never starts
    // it. Both ends are required — a `start()` with no `dataOnScreen()` leaves Apple's
    // extended launch measurement open forever, and a `dataOnScreen()` with no `start()`
    // reports the plain first-frame number, which is the false-excellent one.
    let app = try Self.appSwiftFiles()
    let code = app.map { Self.code($0.text) }.joined(separator: "\n")
    #expect(code.contains("LaunchSignpost.shared.start()"), "no app-start signpost")
    #expect(code.contains("LaunchSignpost.shared.dataOnScreen()"), "no data-on-screen signpost")

    // ...and the end is on the view that shows DATA, never on the loading shell: closing
    // the interval when a spinner appears would make the launch number excellent and false.
    // BOTH halves are needed. "it appears after `case .ready`" alone still passes if the
    // spinner ALSO closes it, which is the very mistake this lint exists to catch — so the
    // `.loading` arm is checked negatively, on its own.
    let view = try #require(app.first { $0.name == "TodayView.swift" })
    let body = Self.code(view.text)
    let ready = try #require(body.range(of: "case .ready"))
    #expect(
      body[ready.lowerBound...].contains("dataOnScreen()"),
      "the interval must close in the `.ready` branch"
    )

    let loading = try #require(body.range(of: "case .loading"))
    // The `.loading` arm runs to the next `case` — the `.failed` arm, which closes the
    // interval legitimately (a launch that ended in an error is still a launch that ended).
    let afterLoading = body[loading.upperBound...]
    let nextCase = try #require(afterLoading.range(of: "case ."))
    #expect(
      !afterLoading[..<nextCase.lowerBound].contains("dataOnScreen()"),
      "the loading shell closes the launch interval — that is the false-excellent number"
    )
  }

  // MARK: - S4 acceptance 5: never re-parse a formatted date

  @Test("`Format.swift` never takes a formatted string apart")
  func formatResultsAreNeverSplit() throws {
    // The web learned this one the hard way: `formatLabel(...).split(' ')` assumed three
    // space-separated tokens and produced silent nonsense in every locale that uses none.
    //
    // "Do not apply a separator to a FormatStyle result" is not decidable from source — a grep
    // cannot tell what a variable holds. This is its decidable form: `Format.swift` is the one
    // module in the package allowed to hold a format result, so banning the two operators
    // THERE bans the mistake. A future need for them is a reviewed exception, not a quiet edit.
    let format = try #require(try Self.swiftFiles().first { $0.name == "Format.swift" })
    let code = Self.code(format.text)
    for banned in [".split(", ".components(separatedBy:"] {
      #expect(
        !code.contains(banned),
        "Format.swift uses \(banned) — a formatted string must never be taken apart")
    }
    // ...and the RIGHT tool is genuinely in use, so the ban above cannot pass because the
    // module stopped formatting dates at all. `.attributed` + a `dateField` run is the
    // platform telling us which characters are the weekday.
    #expect(code.contains(".attributed"), "Format.swift no longer formats attributed dates")
    #expect(code.contains("run.dateField"), "Format.swift no longer reads DateFieldAttribute")
  }

  @Test("the split ban is not vacuous — the operators really are absent, not just unused")
  func formatSplitBanIsNotVacuous() throws {
    // A lint that scanned an empty file would pass forever. Both halves: the file is real and
    // substantial, and the banned tokens are ones this codebase does use elsewhere — so their
    // absence here is a property of THIS file rather than of the project's style.
    let format = try #require(try Self.swiftFiles().first { $0.name == "Format.swift" })
    #expect(format.text.count > 2000, "Format.swift looks truncated")
    let elsewhere = try Self.swiftFiles()
      .filter { $0.name != "Format.swift" && Self.code($0.text).contains(".split(") }
    #expect(!elsewhere.isEmpty, "nothing in the package splits a string — the ban proves nothing")
  }

  @Test("NOTHING in either target reaches the network — the offline floor is structural")
  func noNetwork() throws {
    // The app's premise is that it answers with no network at all, and the plan's S2
    // acceptance 5 (the simulator in Airplane Mode) is a human eyeball the user waived. This
    // is the assertable half of the same claim, and a stronger one in one respect: an
    // eyeball proves the app worked offline once, whereas this proves there is no network
    // code to work with — the app CANNOT be reaching anything. It covers the app target as
    // well as the kit, because a fetch added to a view would be just as fatal.
    var scanned = 0
    for file in try Self.swiftFiles() + Self.appSwiftFiles() {
      scanned += 1
      for banned in ["URLSession", "import Network", "NWConnection", "CFSocket", "CFStream"] {
        #expect(!file.text.contains(banned), "\(file.name) references \(banned)")
      }
    }
    #expect(scanned >= 9, "the lint must actually have read both targets, saw \(scanned) files")
  }
}
