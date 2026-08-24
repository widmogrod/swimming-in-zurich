// TodayModel.swift — sequence the store call, publish the model, persist the favourites.
//
// It holds NO rules. Which sessions exist, whether one is running at this minute, what a
// schedule-less pool's honest state is, how the list is tiered and ordered, which chips the day
// strip shows — all of it is decided in `SwimZHKit` and tested there. This type only decides
// WHEN to ask, which is not a rule anyone can get subtly wrong.
//
// MEMORY. The `Answer` is consumed into the `ListModel` and dropped: one full 57-pool answer
// already peaks around half the app's 100 MB budget before any UI exists, so holding the answer
// AND a derived copy of it is exactly the mistake the budget cannot absorb. The store's own
// pool cache stays, because it is per-store rather than per-day.

import Foundation
import SwimZHKit

@MainActor
@Observable
final class TodayModel {
  enum State {
    case loading
    case ready(ListModel, StoreMetadata)
    /// The store could not be opened or read. Shown as itself — never as an empty list, which
    /// would read as "nothing is open today".
    case failed(String)
  }

  private(set) var state: State = .loading
  private(set) var chips: [DayChip] = []
  private(set) var kinds: [String] = []
  private(set) var today: String = ""

  var filters: Filters = Filters(day: "") {
    didSet { reloadIfNeeded(oldValue) }
  }

  private var store: Store?
  private var metadata: StoreMetadata?
  private var favourites: Favourites = Favourites()
  /// Set only while `load` installs the initial filters, so that assignment's `didSet` does not
  /// race the first `refresh`. It deliberately does NOT cover a refresh in flight: a keystroke
  /// arriving mid-query must not be swallowed.
  private var installingFilters = false
  /// Which request is current. A refresh publishes only if no newer one started while it was
  /// awaiting, so a slow answer for an old filter cannot overwrite a fast answer for the
  /// current one.
  private var generation = 0
  /// The work a filter change spawned. Held so a caller can await it — a test that changed a
  /// filter and read `state` on the next line would otherwise be reading the PREVIOUS answer,
  /// and would pass or fail on scheduling rather than on behaviour.
  private(set) var pendingRefresh: Task<Void, Never>?

  /// Where the favourites live. Local only: there is no account and no sync, which is what
  /// lets the privacy manifest declare UserDefaults with reason `CA92.1` and nothing else.
  static let favouritesKey = "swimzh.favourites"

  func isFavourite(_ poolID: String) -> Bool { favourites.contains(poolID) }

  func toggleFavourite(_ poolID: String) {
    favourites.toggle(poolID)
    UserDefaults.standard.set(favourites.encoded, forKey: Self.favouritesKey)
    startRefresh()
  }

  func load(now: Date = Date()) async {
    do {
      let store = try self.store ?? Store.bundled()
      self.store = store
      let metadata = try await store.metadata()
      self.metadata = metadata
      favourites = Favourites.decode(
        UserDefaults.standard.string(forKey: Self.favouritesKey) ?? "")
      updateToday(now)
      // From the ROSTER, not from one day's answer: an answer is already narrowed by the
      // radius, so a kind filter built from it would silently lose the kinds that happen to be
      // far away today.
      kinds = Set(try await store.pools().map(\.kind)).sorted()
      // Open on today when the horizon contains it, and on the horizon's first day when it
      // does not — a store whose horizon has run out must still show something real.
      installingFilters = true
      filters = Filters(day: metadata.covers(day: today) ? today : metadata.horizonStart)
      installingFilters = false
      await refresh(now: now)
    } catch {
      state = .failed(String(describing: error))
    }
  }

  /// Re-ask the store for the current filters. `now` supplies only the wall-clock time of day —
  /// the one clock input the client may reason about (invariant E1).
  func refresh(now: Date = Date()) async {
    guard let store, let metadata else { return }
    // BEFORE anything else. `today` was captured once at launch, so an app left open across
    // midnight went on treating yesterday as today: the clock tiers resumed on a stale day and
    // the "Today" chip pointed at the day before. It is a wall-clock fact, so it is re-read
    // every time the wall clock is consulted.
    updateToday(now)
    generation += 1
    let mine = generation
    let asked = filters
    // THE WALL CLOCK MAY ONLY BE ASKED ABOUT TODAY. The day strip spans the store's whole
    // horizon, so the selected day is usually not the one the user is standing in; asking the
    // store "is this open now" for a date four months out would put a 06:00–09:00 session into
    // "Open now" at 07:30. On any other day the reference moment is the fixed one the web pins
    // (`api.ts`'s `DAY_MOMENT = "T12:00"`), and `listModel` — told which day is today — makes no
    // wall-clock claim at all.
    let time = asked.day == today ? ZurichClock.timeOfDay(of: now) : dayMoment
    // A task cancelled before it ever ran does no query at all. Cancellation cannot interrupt
    // the read itself — it is one synchronous actor call — so the `generation` guard below stays
    // the thing that keeps a late answer from overwriting a current one.
    guard !Task.isCancelled else { return }
    do {
      let answer = try await store.answer(
        onDay: asked.day,
        at: time,
        for: asked.person,
        near: asked.origin,
        radiusKm: asked.radiusKm
      )
      guard mine == generation else { return }
      state = .ready(
        listModel(
          answer: answer,
          filters: asked,
          favourites: favourites,
          horizon: metadata,
          today: today,
          at: time
        ),
        metadata
      )
    } catch {
      guard mine == generation else { return }
      state = .failed(String(describing: error))
    }
  }

  /// Every filter change re-asks the store, including the ones that only re-derive (search,
  /// kind, eligible-only). That is deliberate at this size: the query is one indexed read of
  /// roughly fifty rows, and caching the `Answer` to avoid it would mean holding the answer AND
  /// the model derived from it — the one thing the 100 MB budget cannot absorb. If a
  /// measurement ever says the round trip costs something, the fix is to cache, not to guess.
  /// Re-read the Zurich day, and re-mark the strip when it has moved.
  ///
  /// The chips are rebuilt only on a real change: it is ~400 formatted labels, which is cheap
  /// once a day and wasteful on every keystroke.
  private func updateToday(_ now: Date) {
    let current = ZurichClock.day(of: now)
    guard current != today, let metadata else { return }
    today = current
    chips = dayChips(from: metadata.horizonStart, through: metadata.horizonEnd, today: today)
  }

  private func reloadIfNeeded(_ old: Filters) {
    guard !installingFilters, old != filters else { return }
    startRefresh()
  }

  /// Replace the in-flight refresh, CANCELLING the one it supersedes.
  ///
  /// `generation` already makes a late answer harmless, but a superseded query still ran to
  /// completion against the store — one full day's read per keystroke, all but the last thrown
  /// away. Cancelling makes the re-ask-on-every-change choice cheap without caching anything.
  private func startRefresh() {
    pendingRefresh?.cancel()
    pendingRefresh = Task { await refresh() }
  }
}
