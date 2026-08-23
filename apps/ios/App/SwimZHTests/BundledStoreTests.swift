// App-hosted tests — the ones `swift test` structurally cannot run.
//
// `swift test` is SwiftPM-only: it cannot import the app target, and it runs on the macOS
// host rather than in a simulator. So this target exists for the two claims that are only
// true INSIDE the app: that the package's bundled store really is present in the built
// `.app` (a resource-bundle wiring mistake is invisible to `swift test`, which reads the
// package's own build directory), and that it answers there.
//
// S2b adds `XCTMemoryMetric` here. It stays an app-hosted UNIT test, never a UI test: an
// `XCUIApplication` measurement measures the test runner, not the app.

import Foundation
import SwimZHKit
import Testing

@testable import SwimZH

@Suite("Bundled store, inside the app")
struct BundledStoreTests {
  @Test("the store ships in the app bundle and answers there")
  func storeIsInTheAppBundle() async throws {
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    #expect(metadata.schemaVersion == 1)
    #expect(metadata.horizonStart < metadata.horizonEnd)

    let answer = try await store.answer(
      onDay: metadata.horizonStart,
      at: TimeOfDay(hour: 12, minute: 0),
      for: Person()
    )
    // The invariant that makes the app honest: every pool in the roster is accounted for on
    // every day, either by its sessions or by a stated reason. A silent gap would read on
    // screen as a pool that does not exist.
    #expect(!answer.options.isEmpty)
    #expect(!answer.statuses.isEmpty)
  }

  @Test("no ghost state is ever rendered as 'closed'")
  func ghostStatesAreNeverDrawnAsClosed() {
    // CLAUDE.md's load-bearing rule, at the last place it can be broken: the label. A pool
    // whose schedule is UNKNOWN must not be told to the user as shut.
    let ghosts = ["awaiting_scrape", "no_source", "open_unscheduled"]
    let closedLabels = Set(
      [nil, "out_of_season", "no_sessions", "unmapped"].map {
        TodayView.statusLabel(status: "closed", closureCode: $0)
      }
    )
    var ghostLabels: Set<String> = []
    for ghost in ghosts {
      let label = TodayView.statusLabel(status: ghost, closureCode: nil)
      #expect(!closedLabels.contains(label), "\(ghost) reads as a closure: \(label)")
      #expect(!label.lowercased().contains("closed"), "\(ghost) reads as closed: \(label)")
      #expect(label != ghost, "\(ghost) is shown as its raw code")
      ghostLabels.insert(label)
    }
    // Distinct from each other, too: three states collapsed into one sentence would be the
    // same loss of honesty one step later.
    #expect(ghostLabels.count == ghosts.count)
    // And the four closure reasons stay distinguishable rather than all reading "Closed".
    #expect(closedLabels.count == 4, "saw \(closedLabels.sorted())")
  }

  @Test("the today screen reaches `ready` with no network available to it")
  @MainActor
  func modelLoadsFromTheBundle() async throws {
    // The app has no networking code at all (a SwimZHKit source lint asserts the rule layer
    // has none, and this target has none), so reaching `.ready` here IS the offline path —
    // there is no other one to fall back to.
    // The day is derived from the store's own horizon, exactly as the package suites do.
    // A hardcoded date would turn every fixture refresh into an unrelated red here.
    let horizonStart = try await Store.bundled().metadata().horizonStart
    let model = TodayModel()
    let day = try #require(
      ZurichClock.instant(day: horizonStart, at: TimeOfDay(hour: 12, minute: 0))
    )
    await model.load(now: day)
    guard case .ready(let answer, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
    #expect(!answer.options.isEmpty)
  }
}
