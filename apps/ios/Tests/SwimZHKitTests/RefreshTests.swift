// RefreshTests — the weekly store update, and every way it is allowed to fail.
//
// A refresh may never make the app worse. That is one sentence and about a dozen failure modes,
// so this suite is organised by what would break if each check were missing:
//
//   * a manifest for another schema        -> a bad upload bricks every installed app
//   * a truncated or tampered download     -> SQLITE_CORRUPT at some arbitrary later read
//   * a WAL-mode store from a bad build    -> opens fine here, fails on the device's first
//                                             prepare — AFTER the old file is gone
//   * a swap with the connection still open-> the app serves last week's data forever, silently
//   * a failure anywhere in between        -> a temp file left in Application Support
//
// Everything here runs against REAL SQLite files built from the committed store, because the
// interesting failures are file-level: a size check and a hash check over fixtures would prove
// arithmetic, not that a corrupted store is rejected before it replaces a good one.

import Foundation
import SQLite3
import Testing

@testable import SwimZHKit

/// Serves fixed bytes per URL, or fails. Two dictionaries rather than one so a manifest can
/// succeed while the store download fails — which is the mid-download case acceptance 4 is
/// about.
private struct StubFetcher: HTTPFetching {
  var bodies: [String: Data] = [:]
  var failing: Set<String> = []

  func data(from url: URL) async throws -> Data {
    if failing.contains(url.absoluteString) { throw URLError(.networkConnectionLost) }
    guard let body = bodies[url.absoluteString] else { throw URLError(.fileDoesNotExist) }
    return body
  }
}

@Suite("Store refresh")
struct RefreshTests {
  static let manifestURL = URL(string: "https://example.test/manifest.json")!
  static let storeURL = URL(string: "https://example.test/ios.sqlite")!

  static func temporaryDirectory() throws -> URL {
    let directory = FileManager.default.temporaryDirectory
      .appending(path: "swimzh-refresh-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory
  }

  static func bundledURL() throws -> URL {
    try #require(Bundle.module.url(forResource: "ios", withExtension: "sqlite"))
  }

  /// A copy of the committed store, optionally with its `meta` rewritten.
  ///
  /// Rewriting goes through SQLite rather than through a byte patch: `built_at` and
  /// `schema_version` are rows, and a hex edit would produce a file that is corrupt for a
  /// second reason and would pass this suite's checks for the wrong one.
  static func store(
    at path: URL, builtAt: String? = nil, schemaVersion: Int? = nil,
    dropBaditickerColumn: Bool = false
  ) throws -> URL {
    try FileManager.default.copyItem(at: try bundledURL(), to: path)
    guard builtAt != nil || schemaVersion != nil || dropBaditickerColumn else { return path }
    var handle: OpaquePointer?
    #expect(sqlite3_open(path.path, &handle) == SQLITE_OK)
    defer { sqlite3_close_v2(handle) }
    if let builtAt {
      #expect(
        sqlite3_exec(
          handle, "UPDATE meta SET value='\(builtAt)' WHERE key='built_at';", nil, nil, nil)
          == SQLITE_OK)
    }
    if let schemaVersion {
      #expect(
        sqlite3_exec(
          handle, "UPDATE meta SET value='\(schemaVersion)' WHERE key='schema_version';", nil, nil,
          nil) == SQLITE_OK)
    }
    if dropBaditickerColumn {
      // What a version-1 store genuinely looks like: the column absent, not merely a different
      // number in `meta`. A detail read against this throws `no such column`.
      #expect(
        sqlite3_exec(handle, "ALTER TABLE pool DROP COLUMN baditicker_poiid;", nil, nil, nil)
          == SQLITE_OK)
    }
    // The rewrite journal must not be left behind: a `-wal`/`-shm` pair beside the file is
    // exactly what the export removes, and leaving one would make these fixtures unlike the
    // real article.
    #expect(sqlite3_exec(handle, "PRAGMA journal_mode=DELETE;", nil, nil, nil) == SQLITE_OK)
    return path
  }

  static func manifest(
    for path: URL, url: URL = storeURL, schemaVersion: Int = appStoreSchemaVersion,
    builtAt: String? = nil, bytes: Int? = nil, sha256: String? = nil
  ) throws -> StoreManifest {
    let size = try #require(path.resourceValues(forKeys: [.fileSizeKey]).fileSize)
    return StoreManifest(
      schemaVersion: schemaVersion,
      builtAt: builtAt ?? "2099-01-01T00:00:00+01:00",
      horizonEnd: "2099-12-31",
      url: url.absoluteString,
      sha256: try sha256 ?? DownloadedStore.digest(of: path),
      bytes: bytes ?? size
    )
  }

  static func encoded(_ manifest: StoreManifest) throws -> Data {
    let encoder = JSONEncoder()
    return try encoder.encode(manifest)
  }

  static let currentMetadata = StoreMetadata(
    schemaVersion: appStoreSchemaVersion, builtAt: "2026-08-24T10:00:00+02:00",
    horizonStart: "2026-08-23", horizonEnd: "2027-01-09", goldValidAsOf: "", contentHash: "abc")

  // MARK: - The version this binary speaks

  @Test("the app's schema version is the exporter's, and both are pinned")
  func schemaVersionIsPinned() {
    // Two numbers in two languages that MUST move together: `ios_export.SCHEMA_VERSION` and
    // this. A Python test greps this file so a bump on one side cannot ship alone; the literal
    // here is what makes that grep meaningful.
    #expect(appStoreSchemaVersion == 2)
  }

  // MARK: - Deciding whether to download at all

  @Test("a manifest for another schema is rejected, and the current store keeps serving")
  func aForeignSchemaIsRejected() {
    // S5 acceptance 2. The version exists precisely so a bad upload cannot brick installed
    // apps: an older binary must not read a store with columns it does not know, and a newer
    // one must not read a store missing columns it needs.
    for version in [appStoreSchemaVersion - 1, appStoreSchemaVersion + 1, 0] {
      let manifest = StoreManifest(
        schemaVersion: version, builtAt: "2099-01-01T00:00:00+01:00", horizonEnd: "2099-12-31",
        url: Self.storeURL.absoluteString, sha256: String(repeating: "a", count: 64), bytes: 10)
      #expect(
        refreshDecision(manifest: manifest, current: Self.currentMetadata)
          == .schemaMismatch(manifest: version, app: appStoreSchemaVersion))
    }
  }

  @Test("a store that is not newer is not downloaded, and one that is, is")
  func onlyNewerStoresAreFetched() {
    let older = StoreManifest(
      schemaVersion: appStoreSchemaVersion, builtAt: "2026-08-01T10:00:00+02:00",
      horizonEnd: "2027-01-09", url: Self.storeURL.absoluteString,
      sha256: String(repeating: "a", count: 64), bytes: 10)
    #expect(refreshDecision(manifest: older, current: Self.currentMetadata) == .notNewer)

    // The SAME stamp is not newer either: a re-publish of an unchanged store must not cost
    // every phone a 5 MB download every hour.
    let same = StoreManifest(
      schemaVersion: appStoreSchemaVersion, builtAt: Self.currentMetadata.builtAt,
      horizonEnd: "2027-01-09", url: Self.storeURL.absoluteString,
      sha256: String(repeating: "a", count: 64), bytes: 10)
    #expect(refreshDecision(manifest: same, current: Self.currentMetadata) == .notNewer)

    let newer = StoreManifest(
      schemaVersion: appStoreSchemaVersion, builtAt: "2026-08-31T10:00:00+02:00",
      horizonEnd: "2027-01-09", url: Self.storeURL.absoluteString,
      sha256: String(repeating: "a", count: 64), bytes: 10)
    #expect(refreshDecision(manifest: newer, current: Self.currentMetadata) == nil)
  }

  @Test("a manifest with a nonsense url, size or digest is refused before anything is fetched")
  func aNonsenseManifestIsRefused() {
    let base = StoreManifest(
      schemaVersion: appStoreSchemaVersion, builtAt: "2099-01-01T00:00:00+01:00",
      horizonEnd: "2099-12-31", url: Self.storeURL.absoluteString,
      sha256: String(repeating: "a", count: 64), bytes: 10)
    let broken = [
      StoreManifest(
        schemaVersion: base.schemaVersion, builtAt: base.builtAt, horizonEnd: base.horizonEnd,
        url: "", sha256: base.sha256, bytes: base.bytes),
      StoreManifest(
        schemaVersion: base.schemaVersion, builtAt: base.builtAt, horizonEnd: base.horizonEnd,
        url: base.url, sha256: "short", bytes: base.bytes),
      StoreManifest(
        schemaVersion: base.schemaVersion, builtAt: base.builtAt, horizonEnd: base.horizonEnd,
        url: base.url, sha256: base.sha256, bytes: 0),
    ]
    for manifest in broken {
      #expect(refreshDecision(manifest: manifest, current: Self.currentMetadata) == .badURL)
    }
  }

  @Test("a manifest that is not JSON, or is JSON of another shape, is ignored not thrown")
  func aMalformedManifestIsIgnored() {
    #expect(StoreManifest.decode(Data("not json".utf8)) == nil)
    #expect(StoreManifest.decode(Data("{\"schema_version\": 2}".utf8)) == nil)
    // ...and the real thing round-trips, so the nils above are about the input.
    let manifest = StoreManifest(
      schemaVersion: 2, builtAt: "x", horizonEnd: "y", url: "https://example.test/s",
      sha256: String(repeating: "a", count: 64), bytes: 1)
    #expect(StoreManifest.decode(try! Self.encoded(manifest)) == manifest)
  }

  // MARK: - Validating the bytes that arrived

  @Test("a good download passes every check")
  func aGoodDownloadIsAccepted() async throws {
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = try Self.store(at: directory.appending(path: "candidate.sqlite"))
    let manifest = try Self.manifest(for: path)
    try await DownloadedStore.validate(at: path, against: manifest)
  }

  @Test("a truncated or tampered download is discarded")
  func aBadDownloadIsRejected() async throws {
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = try Self.store(at: directory.appending(path: "candidate.sqlite"))
    let good = try Self.manifest(for: path)

    // Truncated: the size check catches it first, and cheaply.
    await #expect(throws: StoreRejection.self) {
      try await DownloadedStore.validate(
        at: path, against: try Self.manifest(for: path, bytes: good.bytes + 1))
    }
    // Right size, wrong bytes: only the digest can tell, which is why both checks exist.
    await #expect(throws: StoreRejection.hashMismatch) {
      try await DownloadedStore.validate(
        at: path,
        against: try Self.manifest(for: path, sha256: String(repeating: "0", count: 64)))
    }
  }

  @Test("a WAL-mode store is refused BEFORE the swap, not discovered after it")
  func aWALStoreIsRefused() async throws {
    // The failure this check exists for is silent and late: a WAL file opens fine on macOS and
    // in a writable directory, and fails on the device's FIRST PREPARE in a read-only
    // container — by which time `replaceItemAt` has already thrown away the good store.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = directory.appending(path: "wal.sqlite")
    try FileManager.default.copyItem(at: try Self.bundledURL(), to: path)
    var handle: OpaquePointer?
    #expect(sqlite3_open(path.path, &handle) == SQLITE_OK)
    #expect(sqlite3_exec(handle, "PRAGMA journal_mode=WAL;", nil, nil, nil) == SQLITE_OK)
    #expect(sqlite3_exec(handle, "VACUUM;", nil, nil, nil) == SQLITE_OK)
    sqlite3_close_v2(handle)
    #expect(DownloadedStore.isWAL(path), "the fixture is not actually in WAL mode")

    await #expect(throws: StoreRejection.walJournal) {
      try await DownloadedStore.validate(at: path, against: try Self.manifest(for: path))
    }
    // The control: the committed store is NOT WAL, so the guard is about the mode and not
    // about every SQLite file.
    let sound = try Self.store(at: directory.appending(path: "sound.sqlite"))
    #expect(!DownloadedStore.isWAL(sound))
  }

  @Test("a store whose own meta declares another schema is refused, manifest notwithstanding")
  func theStoresOwnVersionIsChecked() async throws {
    // The manifest is JSON somebody uploaded; the store's `meta` is what the exporter wrote.
    // Trusting only the manifest would let a mismatched pair through — the manifest saying 2
    // while the file says 1 is EXACTLY what a botched release looks like.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = try Self.store(
      at: directory.appending(path: "old.sqlite"), schemaVersion: appStoreSchemaVersion - 1)
    await #expect(
      throws: StoreRejection.schemaMismatch(
        store: appStoreSchemaVersion - 1, app: appStoreSchemaVersion)
    ) {
      try await DownloadedStore.validate(at: path, against: try Self.manifest(for: path))
    }
  }

  @Test("a store with no ANALYZE statistics is refused — rows, never the table's existence")
  func statisticsAreCountedNotAssumed() async throws {
    // `ANALYZE` always CREATES `sqlite_stat1`, even on an empty database (measured in S1), so
    // "the table exists" is not evidence it ran. This fixture has the table and no rows, which
    // is the exact shape a check on existence would wave through.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = directory.appending(path: "unanalyzed.sqlite")
    var handle: OpaquePointer?
    #expect(sqlite3_open(path.path, &handle) == SQLITE_OK)
    #expect(
      sqlite3_exec(
        handle,
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
        INSERT INTO meta VALUES ('schema_version', '\(appStoreSchemaVersion)');
        ANALYZE;
        DELETE FROM sqlite_stat1;
        """, nil, nil, nil) == SQLITE_OK)
    // `ANALYZE` then `DELETE`, deliberately: it produces the exact file shape a check on
    // EXISTENCE would wave through — the table is there, created by ANALYZE itself, and holds
    // nothing. Creating the table by hand would test a fixture; this tests the real shape.
    sqlite3_close_v2(handle)

    let store = try Store(path: path)
    #expect(try await store.statisticsRowCount() == 0, "the fixture must have the table, empty")
    await store.close()

    await #expect(throws: StoreRejection.noStatistics) {
      try await DownloadedStore.validate(at: path, against: try Self.manifest(for: path))
    }
    // The control: the real exported store HAS statistics, so the guard is about this file.
    let real = try Self.store(at: directory.appending(path: "real.sqlite"))
    let opened = try Store(path: real)
    #expect(try await opened.statisticsRowCount() > 0)
    await opened.close()
  }

  // MARK: - The swap

  @Test("a refresh installs the new store, closes the old connection, and answers from the new")
  func aRefreshSwapsTheStore() async throws {
    // S5 acceptance 4b, the whole of it. `replaceItemAt` exchanges the FILE; a connection open
    // across it keeps its fd on the OLD INODE and goes on answering from data that is no longer
    // on disk — with no error anywhere. So: the handle must be closed, and the query after the
    // swap must return the NEW `built_at`.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let published = try Self.store(
      at: directory.appending(path: "published.sqlite"), builtAt: "2099-06-01T00:00:00+02:00")
    let manifest = try Self.manifest(for: published, builtAt: "2099-06-01T00:00:00+02:00")

    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    let before = try await host.store()
    let beforeBuiltAt = try await before.metadata().builtAt
    #expect(beforeBuiltAt != manifest.builtAt)

    let fetcher = StubFetcher(bodies: [
      Self.manifestURL.absoluteString: try Self.encoded(manifest),
      Self.storeURL.absoluteString: try Data(contentsOf: published),
    ])
    let outcome = await host.refresh(manifestURL: Self.manifestURL, fetcher: fetcher)
    #expect(outcome == .installed(builtAt: manifest.builtAt))

    // The OLD connection is closed — asserted by asking it something, which is the only way to
    // observe a closed handle from outside.
    await #expect(throws: StoreError.closed) { _ = try await before.metadata() }
    // ...and the host's new connection answers from the new file.
    let after = try await host.store()
    #expect(try await after.metadata().builtAt == manifest.builtAt)
    #expect(await host.installedPath.lastPathComponent == "ios.sqlite")
    #expect(FileManager.default.fileExists(atPath: await host.installedPath.path))
  }

  @Test("a second refresh replaces an already-downloaded store, without going back to the bundle")
  func aSecondRefreshReplacesTheFirst() async throws {
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)

    for (index, stamp) in ["2099-06-01T00:00:00+02:00", "2099-07-01T00:00:00+02:00"].enumerated() {
      let published = try Self.store(
        at: directory.appending(path: "published-\(index).sqlite"), builtAt: stamp)
      let manifest = try Self.manifest(for: published, builtAt: stamp)
      let fetcher = StubFetcher(bodies: [
        Self.manifestURL.absoluteString: try Self.encoded(manifest),
        Self.storeURL.absoluteString: try Data(contentsOf: published),
      ])
      #expect(
        await host.refresh(manifestURL: Self.manifestURL, fetcher: fetcher)
          == .installed(builtAt: stamp))
      #expect(try await host.store().metadata().builtAt == stamp)
    }
  }

  @Test("a failure mid-download leaves the store readable and unchanged, and no temp file behind")
  func aFailedDownloadChangesNothing() async throws {
    // S5 acceptance 4a. Three failure shapes, because they leave the process at three different
    // points: the store body never arrives, it arrives truncated, and it arrives corrupt.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let published = try Self.store(
      at: directory.appending(path: "published.sqlite"), builtAt: "2099-06-01T00:00:00+02:00")
    let good = try Self.manifest(for: published, builtAt: "2099-06-01T00:00:00+02:00")
    let body = try Data(contentsOf: published)

    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    let baseline = try await host.store().metadata()

    let fetchers: [StubFetcher] = [
      // Never arrives.
      StubFetcher(
        bodies: [Self.manifestURL.absoluteString: try Self.encoded(good)],
        failing: [Self.storeURL.absoluteString]),
      // Arrives truncated — the shape of an interrupted transfer.
      StubFetcher(bodies: [
        Self.manifestURL.absoluteString: try Self.encoded(good),
        Self.storeURL.absoluteString: body.prefix(body.count / 2),
      ]),
      // Arrives whole, but corrupt: right length, wrong bytes.
      StubFetcher(bodies: [
        Self.manifestURL.absoluteString: try Self.encoded(good),
        Self.storeURL.absoluteString: Data(repeating: 0x7A, count: body.count),
      ]),
    ]
    for fetcher in fetchers {
      let outcome = await host.refresh(manifestURL: Self.manifestURL, fetcher: fetcher)
      guard case .skipped = outcome else {
        Issue.record("a failed download reported \(outcome)")
        continue
      }
      // (a) the store in use is still readable, and still the same store.
      #expect(try await host.store().metadata() == baseline)
      // (b) nothing is left behind in Application Support.
      let left = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        .filter { $0.hasPrefix("ios.download-") }
      #expect(left.isEmpty, "temp files left behind: \(left)")
    }
  }

  @Test("an unreachable manifest, and no manifest at all, are both quiet no-ops")
  func offlineIsANoOp() async throws {
    // S5 acceptance 1's other half: offline is a STATE, not an error. Nothing here produces a
    // banner, a throw, or a change to what the app is serving.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    let baseline = try await host.store().metadata()

    let offline = StubFetcher(failing: [Self.manifestURL.absoluteString])
    #expect(
      await host.refresh(manifestURL: Self.manifestURL, fetcher: offline) == .skipped(.unreachable))
    #expect(
      await host.refresh(manifestURL: nil, fetcher: offline) == .skipped(.noManifestConfigured))
    let junk = StubFetcher(bodies: [Self.manifestURL.absoluteString: Data("nope".utf8)])
    #expect(
      await host.refresh(manifestURL: Self.manifestURL, fetcher: junk)
        == .skipped(.malformedManifest))
    #expect(try await host.store().metadata() == baseline)
  }

  @Test("a store published for another schema is refused end to end, and the app keeps working")
  func aForeignSchemaNeverReachesTheDisk() async throws {
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let published = try Self.store(
      at: directory.appending(path: "published.sqlite"), builtAt: "2099-06-01T00:00:00+02:00",
      schemaVersion: appStoreSchemaVersion + 1)
    let manifest = try Self.manifest(
      for: published, schemaVersion: appStoreSchemaVersion + 1,
      builtAt: "2099-06-01T00:00:00+02:00")
    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    let baseline = try await host.store().metadata()

    let fetcher = StubFetcher(bodies: [
      Self.manifestURL.absoluteString: try Self.encoded(manifest),
      Self.storeURL.absoluteString: try Data(contentsOf: published),
    ])
    #expect(
      await host.refresh(manifestURL: Self.manifestURL, fetcher: fetcher)
        == .skipped(
          .schemaMismatch(manifest: appStoreSchemaVersion + 1, app: appStoreSchemaVersion)))
    #expect(try await host.store().metadata() == baseline)
    #expect(!FileManager.default.fileExists(atPath: await host.installedPath.path))
  }

  @Test("a corrupt installed store falls back to the bundled floor rather than bricking")
  func aCorruptInstalledStoreFallsBack() async throws {
    // Nothing in the refresh path can produce this — every downloaded file is validated — but a
    // disk can. The app that answers from the bundle is far better than the app that does not
    // start, and the bundle is always there.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    try Data("this is not a database".utf8).write(to: await host.installedPath)
    let metadata = try await host.store().metadata()
    #expect(metadata.schemaVersion == appStoreSchemaVersion)
    #expect(!metadata.horizonStart.isEmpty)
  }

  @Test("an installed store written for another schema is NOT adopted — the bundle answers")
  func aVersionMismatchedInstalledStoreIsNotAdopted() async throws {
    // THE BRICK THIS CONSTANT EXISTS TO PREVENT, on the path the download checks do not cover.
    // A store already on disk never went through THIS binary's download validation: a phone
    // carrying a downloaded v(n) store that updates to a v(n+1) binary would adopt it because
    // `meta` reads fine — and then throw `no such column` on every detail read, offline,
    // forever, with nothing on screen but a spinner that never resolves.
    //
    // Not reachable today (no released build has written an installed store); reachable at the
    // first schema bump after a release, which is one slice away by construction.
    let directory = try Self.temporaryDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let host = StoreHost(bundled: try Self.bundledURL(), directory: directory)
    let installed = await host.installedPath
    // A WELL-FORMED store of the previous version, with the column that version lacked
    // actually dropped — so an adopted one would fail exactly as it would in the field, rather
    // than merely carrying a different number in `meta`.
    _ = try Self.store(
      at: installed, builtAt: "2020-01-01T00:00:00+01:00",
      schemaVersion: appStoreSchemaVersion - 1, dropBaditickerColumn: true)

    let served = try await host.store()
    let metadata = try await served.metadata()
    #expect(metadata.schemaVersion == appStoreSchemaVersion, "the old store was adopted")
    #expect(metadata.builtAt != "2020-01-01T00:00:00+01:00")
    // The positive control: the bundled store's detail read WORKS, which is the read the
    // adopted store would have thrown on. Without it this test would pass against any store
    // that merely reported the right number in `meta`.
    let pools = try await served.pools()
    let first = try #require(pools.first)
    #expect(try await served.facility(poolID: first.id, on: metadata.horizonStart) != nil)

    // ...and the mismatched file is left alone rather than deleted: the next refresh replaces
    // it, and a rollback might be able to read it again.
    #expect(FileManager.default.fileExists(atPath: installed.path))
  }

  // MARK: - Where it lives, and how often it looks

  @Test("the store directory is in Application Support and excluded from backup")
  func theDirectoryIsTheRightOne() throws {
    // NEVER `Caches` or `tmp`: both are purgeable by the system at any moment, and this
    // directory can hold the only copy of a downloaded store.
    let directory = try StoreLocation.directory()
    #expect(directory.path.contains("Application Support"))
    #expect(!directory.path.contains("/Caches"))
    #expect(FileManager.default.fileExists(atPath: directory.path))
    #expect(StoreLocation.isExcludedFromBackup(directory))
  }

  @Test("a refresh is attempted at most hourly, and always on a first run")
  func refreshesAreHourly() {
    let now = Date(timeIntervalSince1970: 1_785_000_000)
    #expect(shouldRefreshStore(lastAttempt: nil, now: now))
    #expect(!shouldRefreshStore(lastAttempt: now.addingTimeInterval(-59 * 60), now: now))
    #expect(shouldRefreshStore(lastAttempt: now.addingTimeInterval(-60 * 60), now: now))
    // A clock that moved backwards must not block refreshes until it catches up.
    #expect(shouldRefreshStore(lastAttempt: now.addingTimeInterval(3600), now: now))
  }

  @Test("the manifest URL is configuration, https-only, and absent by default")
  func theManifestURLIsConfiguration() {
    // Hosting is out of scope for this repo, so an app built without the key never reaches the
    // network for a store at all — which is a complete, working app.
    #expect(RefreshConfiguration.manifestURL(nil) == nil)
    #expect(RefreshConfiguration.manifestURL([:]) == nil)
    #expect(RefreshConfiguration.manifestURL([RefreshConfiguration.infoKey: ""]) == nil)
    // Plaintext is refused: the manifest carries the URL AND the hash, so an intermediary that
    // can rewrite it can rewrite both and every check downstream is meaningless.
    #expect(
      RefreshConfiguration.manifestURL([RefreshConfiguration.infoKey: "http://example.test/m.json"])
        == nil)
    #expect(
      RefreshConfiguration.manifestURL([
        RefreshConfiguration.infoKey: "https://example.test/m.json"
      ])?.absoluteString == "https://example.test/m.json")
    // The SHIPPED app's own plist is asserted where `Bundle.main` is the app —
    // `AppCorrectnessTests.noManifestIsConfigured`. Doing it here would be a claim about the
    // test runner's plist, which is nobody's app.
  }
}
