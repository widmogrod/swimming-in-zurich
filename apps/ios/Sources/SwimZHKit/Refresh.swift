// Refresh.swift — the weekly store update, and the second (and last) file allowed to reach the
// network.
//
// THE RULE THIS FILE IS BUILT AROUND: a refresh may never make the app worse. Every failure
// mode — offline, a 404, a manifest for a schema this binary does not know, a truncated
// download, a corrupted file, a WAL-mode store from a mis-configured build — ends in the SAME
// place: nothing changes, and the store already installed goes on answering. There is no error
// banner, because there is nothing the reader could do about it and nothing they have lost.
// "Offline is a first-class state, never an error" is the plan's phrasing.
//
// FOUR THINGS ARE CHECKED BEFORE A DOWNLOADED FILE IS ALLOWED TO REPLACE ANYTHING, and each one
// exists because the alternative is a specific broken app:
//
//  1. `bytes` and `sha256` — a truncated or tampered download.
//  2. `schema_version`, from the store's own `meta` and not merely from the manifest — a bad
//     upload must not brick every installed app. This is the whole reason the version exists.
//  3. `PRAGMA integrity_check`, and `sqlite_stat1` carrying ROWS. `ANALYZE` always CREATES that
//     table, even on an empty database, so "the table exists" is not evidence it ran; the row
//     count is (learned in S1, carried here as the plan asks).
//  4. Header byte 18 — NOT WAL. A WAL-mode store opens fine and fails on the FIRST PREPARE in a
//     read-only container, so a mis-built upload would pass every check that only opened it and
//     then brick the app AFTER the swap, when the old file is gone.
//
// AND THE SWAP ITSELF HAS A TRAP THAT NO AMOUNT OF VALIDATION CATCHES. `FileManager.replaceItemAt`
// exchanges the FILE; an open SQLite connection holds an fd to the OLD INODE and keeps serving
// last week's data indefinitely, with no error anywhere to reveal it. So every connection is
// closed BEFORE the swap and a new one opened after it — `Store.close()` exists for this and for
// nothing else. `replaceItemAt` also requires both items on the same volume, which is why the
// temp file is created in Application Support beside the destination and not in `tmp`.
//
// WHERE THE STORE LIVES: Application Support, never `Caches` or `tmp`. Both are purgeable by the
// system at any moment, and a store that vanishes under a running app is a blank screen. It is
// also excluded from backup: it is a derived artifact that can always be downloaded again, and
// iCloud space is the user's, not ours.

import CryptoKit
import Foundation

// MARK: - The manifest

/// What the release publishes beside the store — written by `swimzh export-ios --manifest`,
/// every field read back out of the finished file so the two cannot disagree.
public struct StoreManifest: Equatable, Sendable, Codable {
  public let schemaVersion: Int
  public let builtAt: String
  public let horizonEnd: String
  public let url: String
  public let sha256: String
  public let bytes: Int

  public init(
    schemaVersion: Int, builtAt: String, horizonEnd: String, url: String, sha256: String,
    bytes: Int
  ) {
    self.schemaVersion = schemaVersion
    self.builtAt = builtAt
    self.horizonEnd = horizonEnd
    self.url = url
    self.sha256 = sha256
    self.bytes = bytes
  }

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case builtAt = "built_at"
    case horizonEnd = "horizon_end"
    case url
    case sha256
    case bytes
  }

  /// A manifest this app cannot read is a manifest it ignores — nil, never a throw that a
  /// caller might turn into a banner.
  public static func decode(_ data: Data) -> StoreManifest? {
    try? JSONDecoder().decode(StoreManifest.self, from: data)
  }
}

/// The schema version THIS BINARY was built against. A store declaring anything else is
/// rejected: a newer one may have columns this code does not read, and an older one is missing
/// columns it does.
public let appStoreSchemaVersion = 2

// MARK: - Deciding

/// Why a refresh did nothing. Every arm is a normal outcome, not an error: the reader keeps the
/// store they have and is told nothing, because nothing about their app changed.
public enum RefreshSkip: Equatable, Sendable {
  case noManifestConfigured
  case unreachable
  case malformedManifest
  case schemaMismatch(manifest: Int, app: Int)
  case notNewer
  case badURL
  case rejected(StoreRejection)
}

public enum RefreshOutcome: Equatable, Sendable {
  case installed(builtAt: String)
  case skipped(RefreshSkip)
}

/// Whether a manifest describes a store worth downloading — a pure function, so every arm is
/// driven by a test rather than by a network.
///
/// `builtAt` is compared as a STRING. That is exact for stamps written in the same offset, and
/// it is deliberately not clever about the rest: a stamp that does not compare greater is simply
/// not newer.
///
/// KNOWN IMPRECISION, and it fails SAFE. Zurich's offset changes twice a year, so a store built
/// at `2026-10-25T02:30:00+01:00` sorts BELOW one built forty minutes earlier at
/// `2026-10-25T02:10:00+02:00` — string order is not instant order across that boundary. The
/// consequence is `.notNewer`: the phone keeps the store it has and tries again in an hour,
/// against a release cadence of a week. Parsing the stamps would remove the imprecision and add
/// a decoder whose failure mode is "never update again"; the trade is taken knowingly, and the
/// day the cadence gets tighter than a DST window is the day to revisit it.
public func refreshDecision(
  manifest: StoreManifest, current: StoreMetadata, appSchemaVersion: Int = appStoreSchemaVersion
) -> RefreshSkip? {
  guard manifest.schemaVersion == appSchemaVersion else {
    return .schemaMismatch(manifest: manifest.schemaVersion, app: appSchemaVersion)
  }
  guard manifest.builtAt > current.builtAt else { return .notNewer }
  guard URL(string: manifest.url) != nil, manifest.bytes > 0, manifest.sha256.count == 64 else {
    return .badURL
  }
  return nil
}

/// Whether a refresh attempt is due.
///
/// ATTEMPT, not success: offline every attempt fails in milliseconds, and an app foregrounded
/// twenty times an hour must not make twenty requests to learn the same thing. An hour is the
/// plan's figure and it is generous — the store is republished weekly.
///
/// A `nil` last attempt means "never tried", which is always due; a last attempt in the FUTURE
/// (a clock that moved backwards) is treated as due rather than blocking refreshes until the
/// clock catches up.
public func shouldRefreshStore(
  lastAttempt: Date?, now: Date, interval: TimeInterval = 60 * 60
) -> Bool {
  guard let lastAttempt else { return true }
  let elapsed = now.timeIntervalSince(lastAttempt)
  return elapsed >= interval || elapsed < 0
}

/// Where the manifest lives, if anywhere.
///
/// CONFIGURATION, not a constant: hosting is out of scope for this repo (the plan says so), so
/// the URL comes from the app's `Info.plist` and an app built without one simply never reaches
/// the network for a store — which is a perfectly good app, and the one this repo ships until
/// somebody uploads a manifest somewhere.
public enum RefreshConfiguration {
  public static let infoKey = "SWIMZHStoreManifestURL"

  /// `https` only. Not security theatre: the manifest names a URL and a hash, and a plaintext
  /// manifest is one an intermediary can rewrite wholesale — hash included — which would defeat
  /// every check downstream of it.
  public static func manifestURL(_ info: [String: Any]?) -> URL? {
    guard let raw = info?[infoKey] as? String, !raw.isEmpty else { return nil }
    guard let url = URL(string: raw), url.scheme?.lowercased() == "https" else { return nil }
    return url
  }
}

// MARK: - Validating a downloaded store

/// Why a downloaded file was refused. Each one is a file that would have broken the app in a
/// different way; none of them reaches the reader.
public enum StoreRejection: Error, Equatable, Sendable {
  case sizeMismatch(expected: Int, actual: Int)
  case hashMismatch
  case walJournal
  case unreadable(String)
  case corrupt(String)
  case noStatistics
  case schemaMismatch(store: Int, app: Int)
}

public enum DownloadedStore {
  /// The sha256 of a file, read in blocks so a 5 MB store is never held twice in memory.
  public static func digest(of path: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: path)
    defer { try? handle.close() }
    var hasher = SHA256()
    while let block = try handle.read(upToCount: 1 << 20), !block.isEmpty {
      hasher.update(data: block)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
  }

  /// Header bytes 18-19: `0101` for delete/truncate/memory/off, `0202` only for WAL. Measured
  /// across all five journal modes in S1; the export asserts the same byte on the way out.
  public static func isWAL(_ path: URL) -> Bool {
    guard let handle = try? FileHandle(forReadingFrom: path) else { return false }
    defer { try? handle.close() }
    guard (try? handle.seek(toOffset: 18)) != nil,
      let marker = try? handle.read(upToCount: 2), marker.count == 2
    else { return false }
    return marker[marker.startIndex] == 0x02
  }

  /// Everything checked before a byte of this file is allowed to replace the store in use.
  ///
  /// Ordered cheapest-first, but the order is not the point: NOTHING may be skipped. The WAL
  /// check in particular has to happen before the swap, because a WAL store opens fine here on
  /// macOS and fails on the device's first prepare — after the old file is gone.
  public static func validate(
    at path: URL, against manifest: StoreManifest,
    appSchemaVersion: Int = appStoreSchemaVersion
  ) async throws(StoreRejection) {
    // `resourceValues(forKeys: [.fileSizeKey])` rather than `attributesOfItem`: the latter
    // returns the file's TIMESTAMPS along with its size, which puts it in reach of Apple's
    // required-reason file-timestamp category (ITMS-91053). The size alone is not a
    // required-reason API, and the size alone is all this needs — so the privacy manifest
    // keeps declaring exactly one API, the `UserDefaults` one S2b verified.
    let size = try? path.resourceValues(forKeys: [.fileSizeKey]).fileSize
    guard let size, size == manifest.bytes else {
      throw .sizeMismatch(expected: manifest.bytes, actual: size ?? -1)
    }
    guard let digest = try? digest(of: path), digest.lowercased() == manifest.sha256.lowercased()
    else { throw .hashMismatch }
    guard !isWAL(path) else { throw .walJournal }

    guard let store = try? Store(path: path) else { throw .unreadable(path.lastPathComponent) }
    // CLOSED BEFORE RETURNING, on every path. `defer` cannot await, and a `Task { await
    // store.close() }` would leave the connection open past the caller's swap — which is the
    // very fd-on-the-old-inode problem this file is arranged to avoid. So the checks return a
    // rejection instead of throwing, the handle is closed, and only then does it throw.
    let rejection = await inspect(store, appSchemaVersion: appSchemaVersion)
    await store.close()
    if let rejection { throw rejection }
  }

  /// The checks that need an open connection, as a value rather than as a throw.
  private static func inspect(_ store: Store, appSchemaVersion: Int) async -> StoreRejection? {
    guard let metadata = try? await store.metadata() else { return .corrupt("no meta table") }
    guard metadata.schemaVersion == appSchemaVersion else {
      return .schemaMismatch(store: metadata.schemaVersion, app: appSchemaVersion)
    }
    guard let integrity = try? await store.integrityCheck() else { return .corrupt("no answer") }
    guard integrity == "ok" else { return .corrupt(integrity) }
    // `ANALYZE` always CREATES `sqlite_stat1`, even on an empty database, so the table's
    // existence proves nothing. The ROW COUNT is what says the planner has real statistics —
    // and, incidentally, that this file went through the export rather than being hand-made.
    guard let statistics = try? await store.statisticsRowCount(), statistics > 0 else {
      return .noStatistics
    }
    return nil
  }
}

// MARK: - Where the store lives

public enum StoreLocation {
  public static let directoryName = "SwimZH"
  public static let storeName = "ios.sqlite"

  /// `…/Library/Application Support/SwimZH`, created if absent and excluded from backup.
  ///
  /// NOT `Caches` and NOT `tmp`: both are purged by the system whenever it likes, and this
  /// directory holds the only copy of a downloaded store. Excluded from backup because the
  /// store is derived — it can always be downloaded again — and the user's iCloud allowance is
  /// theirs.
  public static func directory(
    in base: FileManager.SearchPathDirectory = .applicationSupportDirectory
  ) throws -> URL {
    let root = try FileManager.default.url(
      for: base, in: .userDomainMask, appropriateFor: nil, create: true)
    let directory = root.appending(path: directoryName, directoryHint: .isDirectory)
    if !FileManager.default.fileExists(atPath: directory.path) {
      try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
    try excludeFromBackup(directory)
    return directory
  }

  public static func excludeFromBackup(_ path: URL) throws {
    var mutable = path
    var values = URLResourceValues()
    values.isExcludedFromBackup = true
    try mutable.setResourceValues(values)
  }

  public static func isExcludedFromBackup(_ path: URL) -> Bool {
    (try? path.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup) == true
  }
}

// MARK: - The host

/// Owns the ONE open connection and performs the swap.
///
/// A refresh is four steps in a fixed order — validate, close, replace, reopen — and three of
/// them are wrong on their own. This type exists so there is exactly one place that gets the
/// order right, rather than a view model that remembers to close first.
public actor StoreHost {
  private let bundled: URL
  private let directory: URL
  private var opened: Store?

  /// - Parameters:
  ///   - bundled: the store shipped in the app — the offline floor, always present.
  ///   - directory: where a downloaded store is installed (Application Support).
  public init(bundled: URL, directory: URL) {
    self.bundled = bundled
    self.directory = directory
  }

  /// The app's wiring: the package's bundled store, installed into Application Support.
  public static func standard() throws -> StoreHost {
    guard let bundled = Bundle.module.url(forResource: "ios", withExtension: "sqlite") else {
      throw StoreError.missingBundledStore
    }
    return StoreHost(bundled: bundled, directory: try StoreLocation.directory())
  }

  public var installedPath: URL {
    directory.appending(path: StoreLocation.storeName, directoryHint: .notDirectory)
  }

  /// The store to answer from: the downloaded one when there is one and this binary can read
  /// it, the bundled one otherwise.
  ///
  /// The fallback is not defensive noise. A downloaded store is a file this app did not write,
  /// on a disk it does not control; if it will not open, or if it was written for a different
  /// schema, the bundled floor is still there and the app still works. Bricking on a bad
  /// download is the one outcome the whole refresh design exists to prevent.
  public func store() async throws -> Store {
    if let opened { return opened }
    if let installed = try? await adoptable(installedPath) {
      opened = installed
      return installed
    }
    let store = try Store(path: bundled)
    opened = store
    return store
  }

  /// The installed store, if there is one this binary may answer from.
  ///
  /// TWO CHECKS, and the version one is the reason this is a function rather than a `try?`.
  ///
  ///  1. OPENING IS NOT READING. `sqlite3_open_v2` is lazy: a junk file, and a WAL-mode file in
  ///     a read-only container, both open cleanly and fail on the first PREPARE.
  ///  2. READING `meta` IS NOT READING THE STORE. `metadata()` touches one table that every
  ///     version has, so it succeeds against a store written for ANY schema. The download path
  ///     rejects a foreign version (`refreshDecision`, `DownloadedStore.inspect`), but a store
  ///     already on disk never went through it in THIS binary: a phone carrying a downloaded
  ///     v(n) store and updating to a v(n+1) binary would adopt it, answer `pools()` happily,
  ///     and throw `no such column` on every detail read — offline, forever, with no error the
  ///     reader can see. That is exactly the brick `appStoreSchemaVersion` exists to prevent,
  ///     and it becomes reachable at the FIRST schema bump after a release, not later.
  private func adoptable(_ path: URL) async throws -> Store {
    guard FileManager.default.fileExists(atPath: path.path) else {
      throw StoreError.missingBundledStore
    }
    let store = try Store(path: path)
    guard let metadata = try? await store.metadata() else {
      // It opened and cannot answer: a junk file, a truncated one, or WAL in a read-only
      // container. Close it before falling back, or the fd is held for a store nobody reads.
      await store.close()
      throw StoreRejection.corrupt(path.lastPathComponent)
    }
    guard metadata.schemaVersion == appStoreSchemaVersion else {
      // Left on disk rather than deleted: the next refresh replaces it, and a newer binary
      // (or a rollback) may be able to read it. Closing it is what matters — a connection to a
      // store nobody is answering from is an fd held for nothing.
      await store.close()
      throw StoreRejection.schemaMismatch(
        store: metadata.schemaVersion, app: appStoreSchemaVersion)
    }
    return store
  }

  /// Close the open connection, if any. Public because the swap is not the only reason to: the
  /// app closes on background so the fd is not held across a long suspension.
  public func close() async {
    await opened?.close()
    opened = nil
  }

  /// Fetch the manifest and, if it describes a newer store this binary can read, install it.
  ///
  /// Never throws. Every failure is a `.skipped` outcome and the store in use is untouched.
  /// - Parameter fetcher: defaulted so the APP never names a transport. The app target contains
  ///   no networking at all (`SourceLintTests`), and a `URLSessionFetcher()` at a call site in a
  ///   view model would be exactly that — so the default lives here, in the seam.
  public func refresh(
    manifestURL: URL?, fetcher: HTTPFetching = URLSessionFetcher(), now: Date = Date()
  ) async -> RefreshOutcome {
    guard let manifestURL else { return .skipped(.noManifestConfigured) }
    guard let data = try? await fetcher.data(from: manifestURL) else {
      return .skipped(.unreachable)
    }
    guard let manifest = StoreManifest.decode(data) else { return .skipped(.malformedManifest) }
    guard let current = try? await store().metadata() else { return .skipped(.unreachable) }
    if let skip = refreshDecision(manifest: manifest, current: current) {
      return .skipped(skip)
    }
    guard let source = URL(string: manifest.url) else { return .skipped(.badURL) }
    return await install(manifest: manifest, from: source, fetcher: fetcher)
  }

  private func install(
    manifest: StoreManifest, from source: URL, fetcher: HTTPFetching
  ) async -> RefreshOutcome {
    // IN THE DESTINATION DIRECTORY, not `tmp`: `replaceItemAt` requires the same volume, and a
    // cross-volume temp file turns the atomic swap into a copy that can be interrupted.
    let staging = directory.appending(
      path: "ios.download-\(UUID().uuidString).sqlite", directoryHint: .notDirectory)
    defer { try? FileManager.default.removeItem(at: staging) }
    guard let payload = try? await fetcher.data(from: source),
      (try? payload.write(to: staging, options: .atomic)) != nil
    else {
      return .skipped(.unreachable)
    }
    do {
      try await DownloadedStore.validate(at: staging, against: manifest)
    } catch {
      return .skipped(.rejected(error))
    }
    // ONLY NOW. Everything above this line can fail without the reader losing anything.
    await close()
    let destination = installedPath
    do {
      if FileManager.default.fileExists(atPath: destination.path) {
        _ = try FileManager.default.replaceItemAt(destination, withItemAt: staging)
      } else {
        try FileManager.default.moveItem(at: staging, to: destination)
      }
      try StoreLocation.excludeFromBackup(destination)
    } catch {
      // The old file is still where it was: the next `store()` reopens it, or falls back to
      // the bundled floor.
      return .skipped(.unreachable)
    }
    return .installed(builtAt: manifest.builtAt)
  }
}
