// DataStatus.swift — what the reader is told about the DATA after a check for a newer store.
//
// `Refresh.swift` decides whether a published store is worth downloading and whether a download
// may be trusted; it says nothing to anyone, by design — an automatic check that fails has taken
// nothing away. A PULL is different: the reader asked a question ("is this current?"), and a
// gesture that answers with a spinner and silence is a gesture they learn to distrust. So every
// `RefreshOutcome` is folded here into ONE of four sentences, plus the two facts a reader can act
// on — when the store they are looking at was built, and which of its sources the build could not
// refresh (the lake kept the last silver and marked it stale; see `docs/concepts/lake-silver-layer.md`).
//
// This is the kit and not the view for the usual reason: the mapping from an outcome to a sentence
// is a RULE, and a rule in a SwiftUI body is a rule nothing measures.

import Foundation

// MARK: - Per-source provenance

/// One entry of the store's `meta.source_freshness` — the same list the release manifest carries
/// as `freshness[]`, written by the export from the lake's silver headers.
public struct SourceFreshness: Equatable, Sendable, Codable {
  public enum Status: String, Sendable, Codable {
    /// Fetched by the build that produced this store.
    case fresh
    /// The build could not reach the source and kept the previous fetch.
    case stale
  }

  /// The pipeline's source name: `roster`, `prices`, `schedules`, `lane_plans`.
  public let source: String
  /// ISO 8601 instant, as Python wrote it (`2026-09-06T11:46:10.369170+02:00`).
  public let fetchedAt: String
  public let status: Status

  public init(source: String, fetchedAt: String, status: Status) {
    self.source = source
    self.fetchedAt = fetchedAt
    self.status = status
  }

  enum CodingKeys: String, CodingKey {
    case source
    case fetchedAt = "fetched_at"
    case status
  }

  /// The `meta.source_freshness` JSON, decoded. A pre-lake store writes no such row and an
  /// unreadable one is treated the same way: no provenance, never a failed store.
  public static func decodeList(_ json: String) -> [SourceFreshness] {
    guard !json.isEmpty, let data = json.data(using: .utf8) else { return [] }
    return (try? JSONDecoder().decode([SourceFreshness].self, from: data)) ?? []
  }

  /// The source's name in the reader's language. The catalog names the ones the pipeline has;
  /// a source this binary has never heard of is shown by its token rather than dropped, because
  /// a stale source the reader cannot see is a stale source they cannot allow for.
  public var name: Wording {
    switch source {
    case "roster": return .message(Message("sources.roster"))
    case "prices": return .message(Message("sources.prices"))
    case "schedules": return .message(Message("sources.schedules"))
    case "lane_plans": return .message(Message("sources.lanePlans"))
    default: return .verbatim(source)
    }
  }
}

// MARK: - The answer to a pull

/// What a check for a newer store concluded — one sentence's worth.
public enum DataCheck: Equatable, Sendable {
  /// The published store is the one already installed (or older).
  case upToDate
  /// A newer store was downloaded, validated and installed during this check.
  case updated
  /// The manifest or the store could not be fetched, read, or trusted. Offline is the common
  /// case; it is a state, not an error, and it is worded as one.
  case couldNotCheck
  /// The published store is for a schema this binary does not read: the data can only get
  /// newer through the App Store.
  case appUpdateNeeded

  /// The sentence for the row under the answer.
  public var message: Message {
    switch self {
    case .upToDate: return Message("meta.check.upToDate")
    case .updated: return Message("meta.check.updated")
    case .couldNotCheck: return Message("meta.check.couldNotCheck")
    case .appUpdateNeeded: return Message("meta.check.appUpdateNeeded")
    }
  }
}

/// The reader-facing state of the data: what the last check found and when it ran.
///
/// `check` is nil until a check has run at all, so the screen shows nothing rather than a
/// claim ("up to date") that nothing has established yet.
public struct DataStatus: Equatable, Sendable {
  public let check: DataCheck?
  public let checkedAt: Date?

  public init(check: DataCheck? = nil, checkedAt: Date? = nil) {
    self.check = check
    self.checkedAt = checkedAt
  }

  public static let unchecked = DataStatus()
}

/// Fold a refresh outcome into the sentence the reader gets. Total over the outcome, so a new
/// skip reason is a compile error here rather than a pull that says nothing.
public func dataCheck(after outcome: RefreshOutcome) -> DataCheck {
  switch outcome {
  case .installed:
    return .updated
  case .skipped(let skip):
    switch skip {
    case .notNewer:
      return .upToDate
    case .schemaMismatch:
      return .appUpdateNeeded
    case .noManifestConfigured, .unreachable, .malformedManifest, .badURL, .rejected:
      return .couldNotCheck
    }
  }
}

/// The sources the build of `metadata`'s store could not refresh, in the export's order.
public func staleSources(_ metadata: StoreMetadata) -> [SourceFreshness] {
  metadata.sourceFreshness.filter { $0.status == .stale }
}
