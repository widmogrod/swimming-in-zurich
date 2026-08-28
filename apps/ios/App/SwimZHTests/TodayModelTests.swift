// TodayModelTests.swift — the two `TodayModel` decisions a background store refresh can break.
//
// App-hosted rather than in `SwimZHKitTests` for the usual reason (`BundledStoreTests`): the
// subject lives in the app target, and it is reachable only through `@testable import SwimZH`.
//
// Both claims below are about `load` being called MORE THAN ONCE. That is not a hypothetical
// path: `refreshStore` calls `load` again on every foreground that installs a newer store, and
// nothing on screen changes when it does — which is exactly why a defect here is silent.

import Foundation
import SwimZHKit
import Testing

@testable import SwimZH

@Suite("TodayModel across a store reload")
@MainActor
struct TodayModelReloadTests {
  /// Noon on the store's own first day. Derived from the horizon rather than hardcoded, so a
  /// fixture refresh does not turn every test in this file red for an unrelated reason.
  private func noonOnHorizonStart(_ meta: StoreMetadata) throws -> Date {
    try #require(ZurichClock.instant(day: meta.horizonStart, at: TimeOfDay(hour: 12, minute: 0)))
  }

  @Test("the first load establishes the filters")
  func firstLoadInstallsFilters() async throws {
    // The control case for the two tests below: the "keep what the reader chose" branch must not
    // have cost us the branch that puts something there in the first place. A model whose
    // `filters.day` stayed `""` would ask the store about no day at all.
    let meta = try await Store.bundled().metadata()
    let model = TodayModel()
    #expect(model.filters.day.isEmpty, "the never-loaded sentinel changed")

    await model.load(now: try noonOnHorizonStart(meta))

    // Noon on `horizonStart` IS a covered day, so the clamp opens on it.
    #expect(model.filters.day == meta.horizonStart)
    #expect(model.filters.place == Places.default)
    guard case .ready = model.state else {
      Issue.record("the model did not become ready: \(model.state)")
      return
    }
  }

  @Test("a second load keeps the place and the filters the reader chose")
  func reloadPreservesTheChosenFilters() async throws {
    // THE DEFECT. `load` used to end with an unconditional `filters = Filters(day: firstCovered)`.
    // A background store refresh therefore threw away gender, age, radius, kinds, search, both
    // toggles and the PLACE — while `LocationSource.preferred` and `LocationSource.state`, which
    // the place picker renders from, were untouched. So the picker went on ticking "My location"
    // and every distance was silently re-measured from Zürich Hauptbahnhof: `Located.swift`'s
    // invariant — a position we do not have must never render as a distance — broken through the
    // back door, with nothing on screen to say so.
    let meta = try await Store.bundled().metadata()
    let model = TodayModel()
    let now = try noonOnHorizonStart(meta)
    await model.load(now: now)

    // Everything a reader can set, including a day that is NOT the default, and a place that is
    // not the station. `Zürichhorn` stands in for the device place: a `.device` place cannot be
    // constructed here without a fix, and the field being preserved is the same one.
    let chosen = Places.presets[2]
    let otherDay = try #require(ZurichClock.day(meta.horizonStart, plus: 30))
    model.filters = Filters(
      day: otherDay,
      gender: .female,
      age: 34,
      eligibleOnly: true,
      kinds: ["indoor"],
      search: "letzi",
      place: chosen,
      radiusKm: 3,
      favouritesOnly: true
    )
    await model.pendingRefresh?.value
    let asked = model.filters

    // The foreground path: a newer store is installed and `load` runs again.
    await model.load(now: now)

    #expect(model.filters == asked, "the reload rebuilt the filters instead of keeping them")
    // Spelled out as well as compared, so a failure names the field rather than the struct.
    #expect(model.filters.place == chosen)
    #expect(model.filters.day == otherDay)
    #expect(model.filters.gender == .female)
    #expect(model.filters.age == 34)
    #expect(model.filters.radiusKm == 3)
    #expect(model.filters.kinds == ["indoor"])
    #expect(model.filters.search == "letzi")
    #expect(model.filters.eligibleOnly)
    #expect(model.filters.favouritesOnly)
  }

  @Test("a second load still re-clamps a day the new horizon no longer covers")
  func reloadStillClampsTheDay() async throws {
    // The ONE thing a reload may overrule, and the half of the fix that is easy to lose while
    // making the other half work: keeping the filters must not mean keeping a day the store
    // cannot answer about. A newly installed store publishes its own horizon, and a reader
    // standing on a day that fell off the end of it would be shown "beyond the published
    // horizon" forever, with no way back but a chip tap they have no reason to make.
    //
    // The store is the same object on both loads, so the shrunken horizon is simulated from the
    // other side — the day on screen is moved OUTSIDE it, which is the identical input to the
    // clamp (`!metadata.covers(day: filters.day)`).
    let meta = try await Store.bundled().metadata()
    let model = TodayModel()
    let now = try noonOnHorizonStart(meta)
    await model.load(now: now)

    let gone = try #require(ZurichClock.day(meta.horizonEnd, plus: 7))
    #expect(!meta.covers(day: gone))
    model.filters.day = gone
    model.filters.gender = .male
    await model.pendingRefresh?.value

    await model.load(now: now)

    #expect(model.filters.day == meta.horizonStart, "the uncovered day survived the reload")
    // ...and the clamp moved the DAY only. It is not the old wholesale rebuild wearing a
    // condition: everything else the reader chose is still there.
    #expect(model.filters.gender == .male)
  }

  @Test("a place chosen while a fix is in flight is not overwritten when the fix lands")
  func aLaterNamedPlaceBeatsAnEarlierFix() async throws {
    // THE SECOND DEFECT, and the `placeGeneration` counter that fixes it. Taking a fix suspends,
    // and the place list deliberately does not dismiss when the device row is tapped — so: tap
    // "Use my location", tap a station while the fix is still coming, and the suspended
    // `useMyLocation` used to resume and install the device place over the station the reader
    // had just chosen. `preferred` was false (the named choice called `stopUsing`) over a
    // `.device` place — the picker's tick and the distances disagreeing about one fact.
    //
    // IT RESUMES WITH A REAL FIX, and that is the whole point of the double. Against a live
    // `LocationSource` in a simulator the fix comes back REFUSED in milliseconds, so this test
    // passed because `devicePlace(.refused)` is nil — the neighbouring invariant — and never
    // because the counter held: deleting `placeGeneration` left it green. A test that cannot
    // fail for its stated reason is the exact shape this suite exists to catch elsewhere.
    //
    // `HeldFix` suspends inside `locate()` until this test resumes it, so a genuine `.fixed`
    // lands on the far side of the reader's second tap. Now only the counter can save it.
    let meta = try await Store.bundled().metadata()
    let location = HeldFix()
    let model = TodayModel(location: location)
    await model.load(now: try noonOnHorizonStart(meta))
    let wasPreferred = model.location.preferred

    let fix = Task { await model.useMyLocation() }
    // Let the task reach its first suspension point — inside `LocationSource.locate`, which
    // publishes `.locating` before it waits. Without this the race under test never starts, so
    // the wait is BOUNDED and reported: a silent fall-through would make the test vacuous.
    var spins = 0
    while model.location.state != .locating, spins < 1000 {
      spins += 1
      await Task.yield()
    }
    #expect(model.location.state == .locating, "no fix was ever in flight to race")

    let station = Places.presets[1]
    model.useNamedPlace(station)
    #expect(model.filters.place == station)
    #expect(!model.location.preferred, "the named choice did not stop the preference")

    // NOW let the fix land — a real one, at a real coordinate, after the reader chose.
    location.deliver(.fixed(GeoPoint(lat: 47.3450, lon: 8.5340)))
    await fix.value
    #expect(
      model.location.state == .fixed(GeoPoint(lat: 47.3450, lon: 8.5340)),
      "the double did not deliver a fix, so the counter was never the thing under test")
    #expect(
      model.filters.place == station,
      "an in-flight FIX overwrote the reader's later choice — `placeGeneration` is not holding")
    #expect(!model.location.preferred, "the resumed fix re-armed a preference the reader dropped")
    _ = wasPreferred
  }

  @Test("a fix that lands with nobody having chosen anything else is still installed")
  func anUncontestedFixIsInstalled() async throws {
    // The other half, and without it the test above is satisfied by a `useMyLocation` that
    // installs NOTHING, ever. The counter must block only the superseded fix.
    let meta = try await Store.bundled().metadata()
    let location = HeldFix()
    let model = TodayModel(location: location)
    await model.load(now: try noonOnHorizonStart(meta))

    let here = GeoPoint(lat: 47.3450, lon: 8.5340)
    let fix = Task { await model.useMyLocation() }
    var spins = 0
    while model.location.state != .locating, spins < 1000 {
      spins += 1
      await Task.yield()
    }
    location.deliver(.fixed(here))
    await fix.value
    #expect(model.filters.place?.point == here, "an uncontested fix was not installed")
    #expect(model.filters.place?.source == .device)
  }
}

/// A location source whose fix lands exactly when the test says so.
///
/// The seam `LocationFixing` exists for. A real `LocationSource` in a simulator answers in
/// milliseconds — usually with a refusal — which is too fast and the wrong outcome to put a
/// genuine fix on the far side of a suspension the test needs to interleave with.
@MainActor
final class HeldFix: LocationFixing {
  private(set) var state: LocationState = .idle
  private(set) var fixedAt: Date?
  var preferred = false
  var isAuthorised = true

  private var waiting: CheckedContinuation<Void, Never>?

  func locate() async {
    state = .locating
    await withCheckedContinuation { waiting = $0 }
  }

  /// Settle the held `locate()` with this outcome and let it resume.
  func deliver(_ outcome: LocationState) {
    state = outcome
    if case .fixed = outcome { fixedAt = Date() }
    waiting?.resume()
    waiting = nil
  }

  func refreshIfUsing() async {}

  func stopUsing() {
    preferred = false
    state = .idle
    fixedAt = nil
  }
}
