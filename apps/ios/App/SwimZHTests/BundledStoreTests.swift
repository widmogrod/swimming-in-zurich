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

  @Test("no ghost state reaches the screen worded as a closure")
  @MainActor
  func ghostStatesAreNeverDrawnAsClosed() async throws {
    // CLAUDE.md's load-bearing rule, asserted where the APP can break it: the rows a real screen
    // would draw, built by the real model from the real bundled store.
    //
    // It used to drive `TodayView.statusLabel`, a pass-through kept alive only by this test —
    // and which had already drifted from the path the rows use. So the subject is now the model
    // output itself, which is the only thing a user ever sees.
    let horizonStart = try await Store.bundled().metadata().horizonStart
    let noon = try #require(
      ZurichClock.instant(day: horizonStart, at: TimeOfDay(hour: 12, minute: 0))
    )
    let model = TodayModel()
    await model.load(now: noon)
    guard case .ready(let list, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }

    let rows = list.sections.flatMap(\.rows)
    let ghosts = rows.filter { $0.state?.isUnknownHours == true }
    let closures = rows.filter { $0.state?.isClosureClaim == true }
    // The committed store carries both families on this day; without them the loop below would
    // be vacuously true.
    #expect(!ghosts.isEmpty, "no ghost rows on \(horizonStart) — the store changed")
    #expect(!closures.isEmpty, "no closed rows on \(horizonStart) — the store changed")

    // Rendered, and in EVERY language: the verdicts are catalog messages now, so "does this
    // say closed" is a question about what a reader sees rather than about a Swift literal —
    // and a German translation that said "geschlossen" on a ghost row would be invisible to an
    // English-only check. Same shape as `DayStateTests.ghostStatesAreNeverClosed`, run here
    // against the REAL store rather than against constructed states.
    let shutWords: [Language: [String]] = [
      .en: ["closed", "shut"], .de: ["geschlossen"], .fr: ["ferm"], .it: ["chius"],
      .pl: ["zamkni", "nieczynn"],
    ]
    for language in Language.allCases {
      let localized = Localized(locale: AppLocale(language))
      let closureVerdicts = Set(closures.map { localized($0.verdict.head) })
      for ghost in ghosts {
        let said = localized(ghost.verdict.head)
          .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        #expect(ghost.tier == .unknown, "\(ghost.poolName) is filed under \(ghost.tier)")
        for word in shutWords[language] ?? [] {
          #expect(!said.contains(word), "\(language)/\(ghost.poolName) reads: \(said)")
        }
        #expect(
          !closureVerdicts.contains(localized(ghost.verdict.head)),
          "\(language)/\(ghost.poolName) shares a closed sentence")
      }
    }
    for ghost in ghosts {
      // ...and never the ✕ mark either: nobody was excluded from anything.
      #expect(ghost.mark == .check)
    }
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
    guard case .ready(let list, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
    // The model publishes the DERIVED list, not the raw answer: holding both would mean the
    // whole 57-pool answer plus a copy of it, which is the one thing the 100 MB budget cannot
    // absorb. So the assertion is on the rows a screen would draw.
    #expect(!list.sections.isEmpty)
    #expect(!list.beyondHorizon)
    #expect(list.sections.flatMap(\.rows).count > 1)
    // ...and the day strip really was built from the store's own horizon.
    #expect(model.chips.count > 100)
    #expect(model.chips.first?.day == horizonStart)
    #expect(!model.kinds.isEmpty)
  }

  @Test("an app left open across midnight stops calling yesterday today")
  @MainActor
  func todayIsRereadNotCaptured() async throws {
    // `today` used to be captured once, in `load`. An app left open overnight therefore went on
    // treating yesterday as today: the clock tiers resumed on a stale day, and the "Today" chip
    // pointed at the day before. Both are re-read now, and the chips are re-marked with them.
    let meta = try await Store.bundled().metadata()
    let lateLastNight = try #require(
      ZurichClock.instant(day: meta.horizonStart, at: TimeOfDay(hour: 23, minute: 50))
    )
    let tomorrow = try #require(ZurichClock.day(meta.horizonStart, plus: 1))
    let earlyToday = try #require(
      ZurichClock.instant(day: tomorrow, at: TimeOfDay(hour: 0, minute: 20))
    )

    let model = TodayModel()
    await model.load(now: lateLastNight)
    #expect(model.today == meta.horizonStart)
    #expect(model.chips.first(where: \.isToday)?.day == meta.horizonStart)

    // Midnight passes. The user has touched nothing; the next refresh is all that happens.
    await model.refresh(now: earlyToday)
    #expect(model.today == tomorrow, "the model still thinks today is \(model.today)")
    #expect(model.chips.filter(\.isToday).count == 1)
    #expect(model.chips.first(where: \.isToday)?.day == tomorrow)

    // ...and the selected day — still yesterday, because nothing moved it — is now correctly
    // treated as another day, so no wall-clock claim is made about it.
    guard case .ready(let list, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
    #expect(list.day == meta.horizonStart)
    #expect(!list.isToday)
    for row in list.sections.flatMap(\.rows) {
      #expect(!row.tier.isWallClockClaim, "\(row.poolName) tiered as \(row.tier) on yesterday")
    }
  }

  @Test("selecting another day makes the model drop every wall-clock claim")
  @MainActor
  func pickingAnotherDayStopsTheClock() async throws {
    // The end-to-end half of the day-leak fix: `listModel` refuses to tier a non-today answer
    // by the clock, but only if `TodayModel` actually tells it which day is today AND asks the
    // store at the fixed off-today moment. This drives the real screen state at 07:30, the hour
    // that used to put an early-morning session months away into "Open now".
    let meta = try await Store.bundled().metadata()
    let morning = try #require(
      ZurichClock.instant(day: meta.horizonStart, at: TimeOfDay(hour: 7, minute: 30))
    )
    let model = TodayModel()
    await model.load(now: morning)
    guard case .ready(let today, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
    #expect(today.isToday)

    // Now select a day well inside the horizon but not today, exactly as tapping a chip does.
    let other = try #require(ZurichClock.day(meta.horizonStart, plus: 60))
    #expect(meta.covers(day: other))
    // Assigning the filter is what a chip tap does; awaiting the work it spawned is what makes
    // this a test of behaviour rather than of scheduling.
    model.filters.day = other
    await model.pendingRefresh?.value
    guard case .ready(let future, _) = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
    #expect(!future.isToday)
    #expect(future.openToYouCount == 0)
    // The KEY, not the sentence: which message the model chose is the claim under test, and
    // it holds in every language. The English wording is pinned in `ListModelTests`.
    #expect(future.headline.key == "headline.poolsWithSessions")
    for row in future.sections.flatMap(\.rows) {
      #expect(!row.tier.isWallClockClaim, "\(row.poolName) tiered as \(row.tier) on \(other)")
      #expect(row.verdict.head.key != "mobile.verdict.openNow")
      #expect(row.verdict.head.key != "mobile.verdict.doneForToday")
      #expect(!row.openToYou)
    }
    // ...and it really did read a day with sessions, so the loop is not vacuously true.
    #expect(future.sections.contains { $0.tier == .scheduled })
  }
}
