// The store actor's correctness — including the two footguns that would ship silently.
//
// 1. `sqlite3_open_v2` returns a handle EVEN ON FAILURE. Not closing it leaks a connection
//    per failed open. This slice covers that footgun STRUCTURALLY ONLY — see
//    `SourceLintTests.failedOpenClosesItsHandle` — and the reason is recorded here rather
//    than papered over with a green test:
//      * a file-descriptor count cannot see it. A MISSING file is the case at issue, and
//        `sqlite3_open_v2` allocates a connection for it while opening no descriptor at all.
//      * SQLite's own heap accounting cannot see it either. Apple's system libsqlite3 is
//        built with SQLITE_CONFIG_MEMSTATUS OFF, so `sqlite3_memory_used()` returns a
//        constant 0 — MEASURED, by deliberately leaking 2,000 failed opens and reading
//        baseline 0, after 0, highwater 0, with 2,000 non-nil handles retained. A canary
//        written on that metric passes whether or not the close is there, which is worse
//        than no canary at all.
//      * `malloc_zone_statistics` does see allocations, but Swift Testing runs suites in
//        PARALLEL, so a process-wide allocation delta is mostly other tests' noise.
//    What IS asserted at runtime is the observable behaviour: a failed open throws with
//    SQLite's real code and yields no `Store`, on every one of many repetitions.
// 2. `sqlite3_bind_text` with SQLITE_STATIC and a bridged Swift String is a use-after-free.
//    It is untestable as a negative (undefined behaviour may happen to work), so it is
//    covered two ways: a functional test that binds strings whose buffers are definitely
//    gone by `step`, and a source lint that SQLITE_STATIC appears nowhere in Sources.
//
// Plus the property the whole design turns on: the file is readable from a READ-ONLY
// DIRECTORY with no sidecars, proved by PREPARING AND STEPPING a query, not by opening.
// A WAL-mode file opens fine there and fails on the first prepare — a test that only opened
// it would pass against a database no device could read.

import Foundation
import SQLite3
import Testing

@testable import SwimZHKit

@Suite("Store")
struct StoreTests {
  static func bundledURL() throws -> URL {
    try #require(Bundle.module.url(forResource: "ios", withExtension: "sqlite"))
  }

  @Test("the bundled store is the one the fixtures beside it were generated from")
  func bundledStoreIsTheFixtureStore() async throws {
    // The failure this exists to name. `make ios-export` once projected the LIVE 400-day gold
    // store over this committed offline 140-day one; every golden and lane fixture then
    // described a store that was no longer there, and the suite reported ten issues as
    // per-field diffs of lane strips and session times — which reads as a code defect, not as
    // "you replaced the store". One assertion, one sentence, one fix.
    let identity = try RepoFixtures.json(at: RepoFixtures.storeIdentity)
    let expected = try #require(identity["content_hash"] as? String)
    let meta = try await Store.bundled().metadata()
    #expect(
      meta.contentHash == expected,
      """
      The bundled store is not the one these fixtures describe.
        bundled:  \(meta.contentHash) (\(meta.horizonStart) … \(meta.horizonEnd))
        fixtures: \(expected)
      Regenerate the store AND its fixtures together: `make ios-fixtures`.
      `make ios-export` builds a RELEASE store into dist/ios/ and must not touch this one.
      """)
  }

  @Test("the bundled store opens and answers")
  func bundledStoreAnswers() async throws {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    #expect(meta.schemaVersion == 2)
    #expect(meta.horizonStart < meta.horizonEnd)
    #expect(!meta.contentHash.isEmpty)
    let answer = try await store.answer(
      onDay: meta.horizonStart,
      at: TimeOfDay(hour: 12, minute: 0),
      for: Person()
    )
    #expect(!answer.options.isEmpty || !answer.statuses.isEmpty)
  }

  @Test("the horizon is a stated fact the client can check a date against")
  func horizonCoverage() async throws {
    let meta = try await Store.bundled().metadata()
    #expect(meta.covers(day: meta.horizonStart))
    #expect(meta.covers(day: meta.horizonEnd))
    #expect(!meta.covers(day: "2000-01-01"))
    #expect(!meta.covers(day: "2999-01-01"))
  }

  @Test("every pool in the roster is readable, with its admission state")
  func poolsAreReadable() async throws {
    let pools = try await Store.bundled().pools()
    #expect(pools.count > 50, "the WFS roster is ~57 pools")
    #expect(pools.contains { $0.id == "hallenbad-city" })
    #expect(pools.contains { if case .tariff = $0.admission { return true } else { return false } })
    #expect(pools.contains { $0.geo != nil })
    // Sorted by name, so the browser screen has a stable order without re-sorting.
    #expect(pools.map(\.name) == pools.map(\.name).sorted())
  }

  @Test("the ghost states reach the caller — a schedule-less pool is never 'closed'")
  func ghostStatusesSurvive() async throws {
    // The project's load-bearing honesty rule (CLAUDE.md): `awaiting_scrape`, `no_source`
    // and `open_unscheduled` are first-class states for a pool whose schedule is UNKNOWN,
    // and rendering any of them as "closed" is the one thing the data model forbids. The
    // golden fixture's three pools only ever yield `closed`, so without this nothing proves
    // a ghost survives `Store.statuses` at all.
    let store = try Store.bundled()
    let meta = try await store.metadata()
    var seen: Set<String> = []
    var ghosts: [PoolDayStatus] = []
    for offset in 0..<14 {
      guard
        let day = ZurichClock.instant(day: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0))?
          .addingTimeInterval(Double(offset) * 86_400)
      else { continue }
      let answer = try await store.answer(on: day, at: day, for: Person())
      for status in answer.statuses {
        seen.insert(status.status)
        if status.status != "closed" { ghosts.append(status) }
      }
    }
    #expect(seen.contains("no_source"), "saw only \(seen.sorted())")
    #expect(seen.contains("open_unscheduled"), "saw only \(seen.sorted())")
    // A ghost is NOT a closure, and carries no closure reason that a view could mistake for
    // one. `closureCode` is the field that says "closed, and here is why".
    #expect(ghosts.allSatisfy { $0.closureCode == nil })
    #expect(ghosts.allSatisfy { $0.detailCode == $0.status })
  }

  // MARK: - Footgun 1: the handle returned on failure

  @Test("a failed open throws, and reports SQLite's own code")
  func failedOpenThrows() throws {
    let missing = URL(fileURLWithPath: "/nonexistent/swimzh/definitely-not-here.sqlite")
    do {
      _ = try Store(path: missing)
      Issue.record("a missing store must not open")
    } catch StoreError.cannotOpen(_, let code, _) {
      #expect(code != SQLITE_OK, "the error must carry the real code, not a placeholder")
    }
  }

  @Test("repeated failed opens stay well-behaved, and none of them yields a store")
  func repeatedFailedOpens() throws {
    // NOT a leak canary — the header records why no metric available on Apple's build can
    // be one. What this asserts is that the error path is stable under repetition and never,
    // on any iteration, hands back a usable store.
    let missing = URL(fileURLWithPath: "/nonexistent/swimzh/definitely-not-here.sqlite")
    for _ in 0..<200 {
      #expect(throws: StoreError.self) { _ = try Store(path: missing) }
    }
  }

  @Test("a file that is not a database opens and fails on the QUERY, not on the open")
  func notADatabase() async throws {
    // The nastier shape of footgun 1, and exactly the sequence a WAL file in a bundle
    // produces: `open` SUCCEEDS (SQLite is lazy) and the first PREPARE fails. It is why the
    // read-only-directory test below steps a query instead of merely opening the file.
    let path = FileManager.default.temporaryDirectory
      .appending(path: "swimzh-not-a-db-\(UUID().uuidString).sqlite")
    try Data("this is not a database".utf8).write(to: path)
    defer { try? FileManager.default.removeItem(at: path) }
    let store = try Store(path: path)
    do {
      _ = try await store.metadata()
      Issue.record("a non-database must not answer")
    } catch StoreError.query(_, let code, _) {
      #expect(code == SQLITE_NOTADB, "expected SQLITE_NOTADB, got \(code)")
    }
  }

  // MARK: - Footgun 2: the bind lifetime

  @Test("binds survive the string that produced them")
  func bindsAreTransient() async throws {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    // Each key is built fresh, from parts, inside the loop: with SQLITE_STATIC the C buffer
    // Swift lends for the bind call is already gone by `sqlite3_step`, and the query reads
    // freed memory. Scribbling a large allocation between the calls makes reuse of that
    // memory likely rather than theoretical.
    var totals: [Int] = []
    for _ in 0..<20 {
      let parts = meta.horizonStart.split(separator: "-").map(String.init)
      let rebuilt = parts.joined(separator: "-")
      let answer = try await store.answer(
        onDay: rebuilt,
        at: TimeOfDay(hour: 12, minute: 0),
        for: Person()
      )
      _ = [UInt8](repeating: 0xAA, count: 1 << 20)
      totals.append(answer.options.count + answer.statuses.count)
    }
    #expect(Set(totals).count == 1, "the same query gave different answers: \(Set(totals))")
    #expect(totals.first ?? 0 > 0)
  }

  // MARK: - The property the design turns on

  @Test("the store is readable from a READ-ONLY directory, prepared and stepped")
  func readableFromAReadOnlyDirectory() async throws {
    let manager = FileManager.default
    let directory = manager.temporaryDirectory.appending(path: "swimzh-ro-\(UUID().uuidString)")
    try manager.createDirectory(at: directory, withIntermediateDirectories: true)
    let copy = directory.appending(path: "ios.sqlite")
    try manager.copyItem(at: try Self.bundledURL(), to: copy)
    // 0444 in a 0555 directory: exactly an app bundle. Restored before removal, or the
    // temporary directory cannot be cleaned up.
    try manager.setAttributes([.posixPermissions: 0o444], ofItemAtPath: copy.path)
    try manager.setAttributes([.posixPermissions: 0o555], ofItemAtPath: directory.path)
    defer {
      try? manager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
      try? manager.removeItem(at: directory)
    }

    let store = try Store(path: copy)
    // metadata() PREPARES AND STEPS. Opening proves nothing: a WAL-mode file opens fine
    // here and fails right at this point with SQLITE_CANTOPEN.
    let meta = try await store.metadata()
    #expect(meta.schemaVersion == 2)
    #expect(!manager.fileExists(atPath: copy.path + "-wal"))
    #expect(!manager.fileExists(atPath: copy.path + "-shm"))
  }

  @Test("the URI percent-encodes a path with spaces and a query character")
  func uriEncoding() {
    // An iOS container path carries a UUID and can carry spaces; a `?` in a path would
    // otherwise be read as the start of the URI's own parameters.
    let uri = Store.uri(for: URL(fileURLWithPath: "/tmp/My App Data/what?.sqlite"))
    #expect(uri == "file:/tmp/My%20App%20Data/what%3F.sqlite?immutable=1")
    #expect(uri.hasSuffix("?immutable=1"))
    let plain = Store.uri(for: URL(fileURLWithPath: "/tmp/ios.sqlite"))
    #expect(plain == "file:/tmp/ios.sqlite?immutable=1")
  }

  // MARK: - The radius filter

  @Test("a radius filter keeps what is inside it and reports the distance")
  func radiusFilter() async throws {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    let city = GeoPoint(lat: 47.3739, lon: 8.5310)
    let wide = try await store.answer(
      onDay: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person(),
      near: city, radiusKm: 50
    )
    let narrow = try await store.answer(
      onDay: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person(),
      near: city, radiusKm: 1
    )
    #expect(narrow.options.count + narrow.statuses.count < wide.options.count + wide.statuses.count)
    #expect(wide.options.allSatisfy { ($0.distanceKm ?? .infinity) <= 50 })
    #expect(narrow.options.allSatisfy { ($0.distanceKm ?? .infinity) <= 1 })
    // With no origin there is no distance — nil, which is not the same as zero.
    let unfiltered = try await store.answer(
      onDay: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person()
    )
    #expect(unfiltered.options.allSatisfy { $0.distanceKm == nil })
  }

  @Test("the answer's order is total and reproducible")
  func canonicalOrder() async throws {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    let first = try await store.answer(
      onDay: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person()
    )
    let second = try await store.answer(
      onDay: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person()
    )
    #expect(first == second)
    #expect(first.options.map(\.id) == first.options.map(\.id).sorted() || first.options.count < 2)
  }

  @Test("a date outside the horizon answers empty rather than wrongly")
  func beyondTheHorizon() async throws {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    let answer = try await store.answer(
      onDay: "2999-01-01", at: TimeOfDay(hour: 12, minute: 0), for: Person()
    )
    #expect(answer.options.isEmpty)
    #expect(answer.statuses.isEmpty)
    // An empty answer is NOT "everything is closed": the caller must distinguish the two,
    // which is what `covers` is for.
    #expect(!meta.covers(day: "2999-01-01"))
  }

  @Test("concurrent readers of one store all get the same answer")
  func concurrentReaders() async throws {
    // The actor is the mutex (the connection is opened NOMUTEX because Apple's SQLite is
    // built THREADSAFE=2, i.e. not internally serialized). Hammering it from many tasks is
    // what makes that claim more than a comment.
    let store = try Store.bundled()
    let meta = try await store.metadata()
    let day = meta.horizonStart
    let counts = try await withThrowingTaskGroup(of: Int.self) { group in
      for _ in 0..<32 {
        group.addTask {
          let answer = try await store.answer(
            onDay: day, at: TimeOfDay(hour: 12, minute: 0), for: Person(gender: .female, age: 30)
          )
          return answer.options.count
        }
      }
      return try await group.reduce(into: Set<Int>()) { $0.insert($1) }
    }
    #expect(counts.count == 1, "readers disagreed: \(counts)")
  }
}
