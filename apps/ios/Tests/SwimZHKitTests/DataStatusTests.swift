// DataStatusTests.swift — the sentence a pull gets, and the provenance it is built from.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Data status after a check")
struct DataStatusTests {
  @Test("every refresh outcome folds into one of the four sentences")
  func everyOutcomeHasASentence() {
    #expect(dataCheck(after: .installed(builtAt: "2026-09-06T12:00:00+02:00")) == .updated)
    #expect(dataCheck(after: .skipped(.notNewer)) == .upToDate)
    #expect(dataCheck(after: .skipped(.schemaMismatch(manifest: 3, app: 2))) == .appUpdateNeeded)
    for skip: RefreshSkip in [
      .noManifestConfigured, .unreachable, .malformedManifest, .badURL, .rejected(.hashMismatch),
    ] {
      #expect(dataCheck(after: .skipped(skip)) == .couldNotCheck, "\(skip)")
    }
  }

  @Test("each sentence is a catalog key the catalog actually has")
  func everySentenceResolves() {
    for check: DataCheck in [.upToDate, .updated, .couldNotCheck, .appUpdateNeeded] {
      #expect(Catalog.entries[check.message.key] != nil, "\(check) names a missing key")
    }
  }

  @Test("the store's own source_freshness decodes, and only the stale rows are surfaced")
  func staleSourcesAreReadFromMeta() {
    let json = """
      [{"fetched_at": "2026-09-06T11:46:10.369170+02:00", "source": "roster", "status": "fresh"},
       {"fetched_at": "2026-08-30T03:00:00+02:00", "source": "prices", "status": "stale"},
       {"fetched_at": "2026-09-06T11:46:10.369170+02:00", "source": "schedules", "status": "fresh"}]
      """
    let rows = SourceFreshness.decodeList(json)
    #expect(rows.count == 3)
    let metadata = StoreMetadata(
      schemaVersion: appStoreSchemaVersion, builtAt: "", horizonStart: "", horizonEnd: "",
      goldValidAsOf: "", contentHash: "", sourceFreshness: rows)
    #expect(
      staleSources(metadata)
        == [
          SourceFreshness(source: "prices", fetchedAt: "2026-08-30T03:00:00+02:00", status: .stale)
        ]
    )
    // A pre-lake store writes no row at all; a garbled one is not a broken store either.
    #expect(SourceFreshness.decodeList("").isEmpty)
    #expect(SourceFreshness.decodeList("not json").isEmpty)
    #expect(SourceFreshness.decodeList(#"[{"source": "x"}]"#).isEmpty)
  }

  @Test("the bundled store's provenance is readable, and all of it is fresh")
  func theBundledStoreCarriesProvenance() async throws {
    let metadata = try await Store.bundled().metadata()
    #expect(
      metadata.sourceFreshness.map(\.source) == ["roster", "prices", "schedules", "lane_plans"])
    #expect(staleSources(metadata).isEmpty)
  }

  @Test("a known source is named from the catalog; an unknown one is shown as its token")
  func sourcesAreNamed() {
    let named = SourceFreshness(source: "lane_plans", fetchedAt: "", status: .stale).name
    #expect(named == .message(Message("sources.lanePlans")))
    if case .message(let message) = named {
      #expect(Catalog.entries[message.key] != nil)
    }
    let unknown = SourceFreshness(source: "weather", fetchedAt: "", status: .stale).name
    #expect(unknown == .verbatim("weather"))
  }

  @Test("the store's ISO instants parse — with Python's microseconds and without")
  func storeInstantsParse() throws {
    let precise = try #require(Format.instant("2026-09-06T11:46:11.464339+02:00"))
    let plain = try #require(Format.instant("2026-09-06T11:46:11+02:00"))
    #expect(abs(precise.timeIntervalSince(plain)) < 1)
    #expect(Format.instant("2026-09-06") == nil)
    #expect(Format.instant("") == nil)
  }

  @Test("an instant renders as a date and a time in the reader's language, in Zurich time")
  func storeInstantsAreFormatted() {
    let iso = "2026-07-23T14:32:00+02:00"
    let english = Format(AppLocale(.en)).storeInstant(iso)
    #expect(english.contains("23 July 2026"), Comment(rawValue: english))
    #expect(english.contains("14:32"), Comment(rawValue: english))
    let polish = Format(AppLocale(.pl)).storeInstant(iso)
    #expect(polish.contains("23 lipca 2026"), Comment(rawValue: polish))
    #expect(Format(AppLocale(.en)).storeInstantDay(iso) == "23 July 2026")
    // An unparseable stamp is shown as itself, never blanked — the same rule as `storeDate`.
    #expect(Format(AppLocale(.en)).storeInstant("soon") == "soon")
  }
}
