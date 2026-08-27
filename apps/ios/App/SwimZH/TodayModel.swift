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
import OSLog
import SwimZHKit

@MainActor
@Observable
final class TodayModel {
  enum State {
    case loading
    case ready(ListModel, StoreMetadata)
    /// The store could not be opened or read. Shown as ITS OWN screen — never as an empty
    /// list, which would read as "nothing is open today".
    ///
    /// The payload is a DIAGNOSTIC, not a sentence for the reader: a `StoreError`'s English
    /// detail names a table and a row. S3b put it on screen; S4 sends it to the log and shows
    /// `error.store.title` / `error.store.body` instead — one of the two strings in this app
    /// that could never have been translated, because it is generated at the failure site.
    case failed(String)
  }

  /// The renderer the model needs for the sentences it builds through `SwimZHKit` — the row
  /// verdicts' numbers, the day chips' weekdays. It is the SAME `AppLocale` the views resolve
  /// from the environment; both come from `AppLocale.current`, so there is one answer to
  /// "which language is this" rather than two that must agree.
  private let localized: Localized

  init(localized: Localized = .current) {
    self.localized = localized
  }

  private static let log = Logger(subsystem: "ch.swimzh.app", category: "store")

  /// Record why the store could not be read. The reader sees a sentence; whoever has to fix it
  /// sees the table and the row.
  func log(_ diagnostic: String) {
    Self.log.error("store unreadable: \(diagnostic, privacy: .public)")
  }

  private(set) var state: State = .loading
  private(set) var chips: [DayChip] = []
  private(set) var kinds: [String] = []

  private(set) var today: String = ""
  /// The whole roster, for the all-pools browser. 57 small value types — the pool cache the
  /// store actor already holds, handed over once rather than re-read per screen.
  private(set) var pools: [PoolRecord] = []
  /// The ONE row whose lane chart is open. A single id rather than a set, and that is what
  /// makes "one chart at a time" true rather than hoped for: opening a second row closes the
  /// first, so a `List` can never hold 57 live charts.
  private(set) var expandedPoolID: String?

  var filters: Filters = Filters(day: "") {
    didSet { reloadIfNeeded(oldValue) }
  }

  private var store: Store?
  private var metadata: StoreMetadata?
  /// Owns the connection and the swap. NOT a `Store` any more: the store in use may be the
  /// bundled one or a downloaded one, and only one type may decide which — see `StoreHost`.
  private var host: StoreHost?
  /// The live water-temperature client. One per app, because its 2-minute cache is only worth
  /// having if every sheet shares it.
  private let live = LiveClient()
  /// When a store refresh was last ATTEMPTED — not last succeeded. Offline, every attempt fails
  /// in milliseconds, and retrying on every foreground would be a pointless wakeup an hour's
  /// worth of times.
  private var lastRefreshAttempt: Date?
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
  /// Which choice of ORIGIN is current — the same shape as `generation`, for the same reason
  /// and a worse symptom.
  ///
  /// Taking a fix suspends, and the place list deliberately does not dismiss when the device
  /// row is tapped (both rows must stay reachable, so the reader can change their mind). So:
  /// tap "Use my location", tap "Zürich HB" while the fix is still coming, and the suspended
  /// `useMyLocation` used to resume and overwrite the station with the device — leaving
  /// `preferred` false, which is what the picker renders from, over a `.device` place, which is
  /// what the distances are measured from. Two controls disagreeing about one fact.
  ///
  /// Every entry point that settles the origin bumps this, so the newest choice wins and an
  /// older one that is still awaiting a satellite installs nothing at all.
  private var placeGeneration = 0

  /// Where the favourites live. Local only: there is no account and no sync, which is what
  /// lets the privacy manifest declare UserDefaults with reason `CA92.1` and nothing else.
  static let favouritesKey = "swimzh.favourites"

  /// The phone's own position, and whether the reader wants to be measured from it.
  ///
  /// Owned by the model rather than by a view, because the DECISION it feeds — what
  /// `filters.place` becomes — is the model's, and because a fix taken on the find screen must
  /// still be the origin when the map draws its distances.
  let location = LocationSource()

  /// Measure from the phone.
  ///
  /// The whole state machine, in the order that keeps the screen honest. `preferred` is set
  /// FIRST so the choice survives a launch even if this particular fix fails; the place is
  /// installed LAST and only if `devicePlace` returns one — every refusal, and the wait itself,
  /// leaves `filters.place` exactly where it was. That is what stops the app measuring from
  /// Hauptbahnhof while the reader believes it is measuring from their phone.
  func useMyLocation() async {
    location.preferred = true
    let mine = beginPlaceChoice()
    await location.locate()
    guard mine == placeGeneration, let place = devicePlace(location.state) else { return }
    filters.place = place
  }

  /// Go back to a named place. It stops the preference too, or the next launch would silently
  /// take a fix for a reader who has just said they want the station.
  func useNamedPlace(_ place: Place?) {
    _ = beginPlaceChoice()
    location.stopUsing()
    filters.place = place
  }

  func isFavourite(_ poolID: String) -> Bool { favourites.contains(poolID) }

  /// Where every pool in the roster is, keyed by id.
  ///
  /// The ROSTER's coordinates, because that is the only place they live: neither a `PoolRow`
  /// nor a `FacilityDetail` carries a point. Built on demand from `pools`, which is already in
  /// memory and is 57 entries.
  var geoByPool: [String: GeoPoint] {
    var byPool: [String: GeoPoint] = [:]
    for pool in pools {
      guard let geo = pool.geo else { continue }
      byPool[pool.id] = geo
    }
    return byPool
  }

  /// This pool's row inside the answer on screen, or nil when the answer does not contain it —
  /// which is the ordinary case from the all-pools browser. The search is `SwimZHKit.findRow`,
  /// so a rule the pool screen depends on is one a test drives.
  func row(_ poolID: String) -> PoolRow? {
    guard case .ready(let list, _) = state else { return nil }
    return findRow(list.sections, poolID: poolID)
  }

  /// Whether the answer on screen is for the day the user is standing in. Read off the model
  /// rather than recomputed, so the pool screen and the row it was pushed from cannot disagree.
  var isToday: Bool {
    guard case .ready(let list, _) = state else { return false }
    return list.isToday
  }

  func isExpanded(_ poolID: String) -> Bool { expandedPoolID == poolID }

  /// Open this row's lane chart, closing whichever was open. A toggle rather than a set: see
  /// `expandedPoolID`.
  func toggleExpanded(_ poolID: String) {
    expandedPoolID = expandedPoolID == poolID ? nil : poolID
  }

  /// One pool's detail sheet, read when it is opened.
  ///
  /// NOT cached. A `FacilityDetail` carries the store's largest documents (every basin, every
  /// locker, every feature's resolved days), and one 57-pool answer already peaks at about half
  /// the app's memory ceiling — so holding sheets for pools nobody is looking at is exactly the
  /// spend the budget cannot absorb. Six indexed reads, off the scrolling path, is the cheaper
  /// side of that trade.
  func facility(_ poolID: String) async -> FacilityDetail? {
    guard let store else { return nil }
    return try? await store.facility(poolID: poolID, on: filters.day)
  }

  func toggleFavourite(_ poolID: String) {
    favourites.toggle(poolID)
    UserDefaults.standard.set(favourites.encoded, forKey: Self.favouritesKey)
    startRefresh()
  }

  /// One pool's live water temperature, asked for when its sheet opens.
  ///
  /// Returns a STATE, never throws and never nil: offline, unkeyed and provider-error all render
  /// as their own sentence. A `nil` here would become an absent row, which reads as "this pool
  /// has no water temperature" — a different and false statement.
  func liveTemperature(poiid: String?) async -> LiveTemp {
    await live.temperature(poiid: poiid)
  }

  /// A fix at launch, for a reader who already chose one — and NEVER a permission prompt. The
  /// rule is `SwimZHKit.shouldLocateOnLaunch`; both halves matter and its doc says why.
  func locateIfChosenBefore() async {
    guard
      shouldLocateOnLaunch(
        preferred: location.preferred, alreadyAuthorised: location.isAuthorised)
    else { return }
    await useMyLocation()
  }

  /// Coming back to the foreground is when a position taken before a tram ride is most likely
  /// to be wrong. It refreshes only a fix we already have — see `LocationSource.refreshIfUsing`.
  func refreshLocation() async {
    let mine = beginPlaceChoice()
    await location.refreshIfUsing()
    guard mine == placeGeneration, let place = devicePlace(location.state) else { return }
    filters.place = place
  }

  /// Claim the origin for this caller, and hand back the ticket it must still hold after any
  /// await before it may install a place. See `placeGeneration`.
  private func beginPlaceChoice() -> Int {
    placeGeneration += 1
    return placeGeneration
  }

  func load(now: Date = Date()) async {
    do {
      let host = try self.host ?? StoreHost.standard()
      self.host = host
      let store = try await host.store()
      self.store = store
      let metadata = try await store.metadata()
      self.metadata = metadata
      favourites = Favourites.decode(
        UserDefaults.standard.string(forKey: Self.favouritesKey) ?? "")
      updateToday(now)
      // From the ROSTER, not from one day's answer: an answer is already narrowed by the
      // radius, so a kind filter built from it would silently lose the kinds that happen to be
      // far away today.
      pools = try await store.pools()
      kinds = poolKinds(pools)
      // THE FIRST LOAD BUILDS THE FILTERS; A RELOAD KEEPS THEM. `load` is not only the launch
      // path — `refreshStore` calls it on every foreground that installs a newer store — and an
      // unconditional `Filters(day:)` there threw away gender, age, radius, kinds, search, both
      // toggles, and the PLACE.
      //
      // The place is the half that made it a lie rather than an annoyance. `location.preferred`
      // and `location.state` live on `LocationSource` and are untouched by this, so the place
      // picker went on showing the device row ticked and the reader went on believing they were
      // being measured from their phone, while every distance was silently re-measured from
      // Hauptbahnhof. That is `Located.swift`'s invariant — a position we do not have must never
      // render as a distance — arriving through the back door, and the worst version of it:
      // nothing on screen changed to say so.
      //
      // `filters` is initialised as `Filters(day: "")`, so an empty day is already the "never
      // loaded" sentinel and needs no second flag. The one thing a reload MAY overrule is the
      // day, because a new store can publish a horizon that no longer covers the day being
      // shown; the clamp is the same rule as the first load's.
      installingFilters = true
      let firstCovered = metadata.covers(day: today) ? today : metadata.horizonStart
      if filters.day.isEmpty {
        // Open on today when the horizon contains it, and on the horizon's first day when it
        // does not — a store whose horizon has run out must still show something real.
        filters = Filters(day: firstCovered)
      } else if !metadata.covers(day: filters.day) {
        filters.day = firstCovered
      }
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
          at: time,
          format: localized.format
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
    chips = dayChips(
      from: metadata.horizonStart, through: metadata.horizonEnd, today: today,
      format: localized.format)
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

  /// Look for a newer published store, and install it if there is one.
  ///
  /// SILENT IN EVERY DIRECTION. No spinner while it runs, no banner when it fails, no message
  /// when it succeeds: the app already answered the question with the store it had, and a
  /// refresh that failed has taken nothing away from the reader. The only visible consequence
  /// of success is that the answers change — which is what a data update IS.
  ///
  /// Every decision inside it belongs to `SwimZHKit`: whether an attempt is due, whether a
  /// manifest is worth acting on, whether a downloaded file may be trusted, and the order of
  /// the swap. This method sequences; it decides nothing.
  func refreshStore(now: Date = Date()) async {
    guard let host, shouldRefreshStore(lastAttempt: lastRefreshAttempt, now: now) else { return }
    lastRefreshAttempt = now
    let outcome = await host.refresh(
      manifestURL: RefreshConfiguration.manifestURL(Bundle.main.infoDictionary), now: now)
    switch outcome {
    case .skipped(let reason):
      // Logged, not shown. An operator debugging a botched upload needs the reason; a swimmer
      // looking for a pool does not, and telling them would be an error state for something
      // that did not go wrong for them.
      Self.log.info("store refresh skipped: \(String(describing: reason), privacy: .public)")
    case .installed(let builtAt):
      Self.log.info("store refreshed to \(builtAt, privacy: .public)")
      // The connection was closed and reopened under us, so everything derived from the old
      // store — the horizon, the day chips, the roster, the current answer — is re-read.
      store = nil
      await load(now: now)
    }
  }
}
