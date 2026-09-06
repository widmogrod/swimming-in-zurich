// TodayView.swift — the primary screen: "where can I swim?", end to end.
//
// The view decides nothing. `SwimZHKit` produces a `ListModel` — sections, rows, verdicts,
// banners, counts, the beyond-horizon flag — and the app lays it out. That split is the
// plan's governing constraint: the app target is outside the CRAP gate and a SwiftUI body
// cannot be unit-tested at all, so a rule placed here is a rule nothing measures.
//
// THIS FILE IS THE FORK, and the fork has one input: the horizontal SIZE CLASS.
//  * compact — a phone, a folded phone, a Split View slice: `CompactShell`, a system tab bar
//    (List, Map, Filters, Search), each tab its own stack.
//  * regular — an unfolded phone, an iPad, a landscape Max: `WideShell`, the map as the whole
//    screen with the list floating over it in a glass column. No tab bar: the regular-width
//    `TabView` floats at the top centre, exactly where the column is, and cannot be moved.
// Never the device idiom, never a screen size. Apple ships no fold API in the iOS 27 SDK
// (checked: nothing in the SwiftUI or UIKit interfaces names a hinge, a fold or a posture);
// what an unfolded phone will report is what every wide window reports today, so the size
// class is the whole test. Decided 2026-09-06 against two alternatives (a stretched phone
// layout, and the tab bar kept in a wide window), both built, felt on the iPad mini, and
// deleted — see `docs/plan/2026-09-05-ios27-liquid-glass-review.md`.
//
// Both shells share: the model, the `Route` enum and its one `RouteScreen`, `StoreStates` (the
// three states of the store), and `AnswerList` (the rows under the day strip). The content
// stack's PATH is one `@State` here, bound to the compact list page and to the wide column, so
// a pool open when the phone unfolds is still open after — the screen changes shape, not place.
//
// Every sentence on this screen is a `Message` from the package, rendered by the one
// `Localized` in the environment (see `Localization.swift`). There is not a single
// user-visible literal in any of these files.

import SwiftUI
import SwimZHKit

/// Everywhere a stack can go.
///
/// ONE route type, and every push is a value of it. The stack used to mix the two: rows pushed a
/// `String` into a `navigationDestination`, while the browse menu pushed destination VIEWS. That
/// is not a style difference — a pool tapped inside the old all-pools browser pushed the sheet
/// AND re-activated the menu's view-based link, so the browser landed back on top of the sheet
/// you had just opened. Mixing the two forms in one stack is the bug; this enum is the fix.
enum Route: Hashable {
  case pool(String)
  case legend
  case about
}

struct TodayView: View {
  @State private var model = TodayModel()

  /// Foregrounding is the only moment a refresh is worth attempting beyond launch: the store is
  /// republished weekly, so anything more eager would be a wakeup that learns nothing.
  @Environment(\.scenePhase) private var scenePhase

  /// THE size-class, not the device — see the header.
  @Environment(\.horizontalSizeClass) private var sizeClass
  private var isWide: Bool { sizeClass == .regular }

  /// The content stack: the list page's pushes in a compact window, the column's in a wide
  /// one. ONE path for both, which is what carries an open pool across a fold or unfold.
  @State private var contentPath: [Route] = []
  /// The map tab's own stack, compact only. Held HERE rather than in `CompactShell` because the
  /// fold reads it after the shell is gone — see `onChange(of: isWide)`.
  @State private var mapPath: [Route] = []

  var body: some View {
    shell
      .task {
        await model.load()
        // A fix for a reader who already chose one, and never a prompt — see
        // `TodayModel.locateIfChosenBefore`. After the answer, for the same reason the store
        // refresh is: the app's promise is an answer the moment it opens.
        await model.locateIfChosenBefore()
        // MapKit's first map in a process costs a few hundred milliseconds of framework and GPU
        // set-up, and the first pool tapped used to pay it as a frozen push. Paid here instead,
        // off the answer's critical path — see `MapWarmup`.
        await MapWarmup.warm()
        // The keyboard's first show is the same kind of bill, paid by the first tap on search.
        // See `KeyboardWarmup`.
        await KeyboardWarmup.warm()
        // AFTER the screen has answered. The refresh is a background nicety; making the first
        // answer wait on a network round trip would trade the app's whole premise — an answer
        // with no network — for a store that is at most seven days fresher.
        await model.refreshStore()
      }
      .onChange(of: scenePhase) { _, phase in
        guard phase == .active else { return }
        Task { await model.refreshStore() }
        Task { await model.refreshLocation() }
      }
      // THE FOLD. Going wide takes the map tab away (the map is on screen anyway), so a reader
      // on it lands on the list — with whatever they had pushed from the map carried over, so
      // unfolding over a pool keeps that pool. Going compact brings the tab back and the path
      // is already the list's.
      .onChange(of: isWide) { _, wide in
        guard wide else { return }
        if contentPath.isEmpty { contentPath = mapPath }
        mapPath = []
      }
  }

  @ViewBuilder
  private var shell: some View {
    if isWide {
      WideShell(model: model, path: $contentPath)
    } else {
      CompactShell(model: model, contentPath: $contentPath, mapPath: $mapPath)
    }
  }
}

// MARK: - What both shells share

/// Every destination a stack has, in one place. A `switch` over VIEWS, not over sentences —
/// `noStateToStringInTheApp` bans the second, and this is the first.
struct RouteScreen: View {
  let route: Route
  let model: TodayModel

  var body: some View {
    destination
      // A pushed screen is its own place: the pool screen is a full map with a drawer at the
      // bottom, and a tab bar drawn over that drawer is two bars fighting for the thumb. Photos
      // does the same on a photo. The edge swipe and the back button are the ways home. (A
      // wide window has no tab bar for this to hide.)
      .toolbarVisibility(.hidden, for: .tabBar)
  }

  @ViewBuilder
  private var destination: some View {
    switch route {
    case .pool(let poolID):
      FacilitySheetLoader(
        poolID: poolID,
        // The name from the answer's row when there is one, else from the roster — both are
        // already in memory, which is what lets the screen say the name before its facts load.
        name: model.row(poolID)?.poolName ?? model.pools.first { $0.id == poolID }?.name ?? "",
        day: model.filters.day, person: model.filters.person,
        // The row the user tapped, the pool's place, and whether the answer is for today —
        // the three things that turn a table of published facts into a screen about a pool.
        // See `PoolHeader`.
        row: model.row(poolID), point: model.geoByPool[poolID], isToday: model.isToday,
        load: { await model.facility($0) },
        live: { await model.liveTemperature(poiid: $0) }
      )
      // IDENTITY FOLLOWS THE POOL. In a wide window a pin REPLACES the open pool in the column's
      // path — same depth, different value — and without this SwiftUI kept the screen's state
      // (its loaded facts, its live reading) and showed the OLD pool under the new route:
      // "clicking on pins does not work". A new pool is a new screen.
      .id(poolID)
    // A PLAIN push, deliberately: the zoom transition this route had gives the pushed screen
    // a drag-to-dismiss on every downward pan, which hijacked the drawer's own drag and hid
    // the bar while it did (see `PoolPanel`). The plain push keeps the edge swipe.
    case .legend:
      AccessTypesView()
    case .about:
      AboutView(
        poolCount: model.pools.count, metadata: model.metadata, status: model.dataStatus,
        canCheck: model.canCheckForUpdates, isChecking: model.isChecking,
        check: { await model.checkForUpdates() })
    }
  }
}

extension View {
  /// The one `navigationDestination` every stack has. Attached by the STACK's root, so a page
  /// knows nothing about which stack it is in.
  func routed(_ model: TodayModel) -> some View {
    navigationDestination(for: Route.self) { RouteScreen(route: $0, model: model) }
  }

  /// A page with NO navigation bar. The TITLE went first: it spelled the day out while the
  /// strip underneath drew the same fact — one thing said twice, costing a row of a phone
  /// screen for the copy you cannot tap. That left a full bar holding one overflow button, and
  /// a band of empty glass above the strip is worse than the title was. The strip starts at
  /// the top of the screen, and the rows get the ~50 points back.
  func bare() -> some View {
    toolbarVisibility(.hidden, for: .navigationBar)
  }
}

extension FilterPage {
  /// The filters over the model. Both shells present the same page — as a tab on the phone,
  /// as a popover in a wide window — and this is the one place its six arguments are spelled.
  init(model: TodayModel) {
    self.init(
      filters: Bindable(model).filters, kinds: model.kinds, location: model.location,
      onUseMyLocation: { await model.useMyLocation() },
      onUseNamedPlace: { model.useNamedPlace($0) })
  }
}

/// The three states of the store, with the READY one drawn by the caller — each surface draws
/// a ready store differently, and the other two states the same.
struct StoreStates<Drawn: View>: View {
  @Environment(\.localized) private var localized
  let model: TodayModel
  @ViewBuilder let draw: (ListModel, StoreMetadata) -> Drawn

  var body: some View {
    switch model.state {
    case .loading:
      // THE SAME COLOUR THE LAUNCH SCREEN IS, AND NOTHING ON IT — no spinner, and no bar.
      // Launch runs through three surfaces — the launch screen, this, then the list — and
      // until now they were three different colours: the launch screen was BLANK WHITE (an
      // empty `UILaunchScreen` dict, so white even on a phone in dark mode), this view took
      // the default `systemBackground`, and the list draws on `systemGroupedBackground`. On a
      // dark phone that is a white flash between two dark screens.
      //
      // Measured, because the fix is worth less than it looks if the timing is wrong: from
      // `App.init()` to the list being on screen is 0.19 s, of which this state holds about
      // 0.05. What the reader actually waits through is the 1.3 s BEFORE any of our code runs
      // — dyld, the Swift runtime, SwiftUI — and the launch screen owns all of it. So the one
      // thing worth doing is making that screen look like the app rather than like nothing.
      //
      // The spinner went with the performance review: the store answers in a few
      // milliseconds (every read measured under 3 ms), so the wheel showed for a frame or
      // two and read as "the app is loading something" about an app that was not. The HIG
      // reserves progress indication for waits a reader can feel.
      Color("LaunchBackground")
        .ignoresSafeArea()
    case .failed(let diagnostic):
      // The DIAGNOSTIC is not shown. It is a `StoreError`'s own English detail — an SQL table
      // name and a row id — which is a developer's sentence, not a reader's, and S3b shipped
      // it straight into a `ContentUnavailableView`. The reader gets a sentence that says what
      // happened and what to do; the diagnostic goes to the log, where it is useful.
      // The ViewBuilder form, not `init(_:systemImage:description:)`: that one takes a
      // `LocalizedStringKey` title, and this title has already been localised — handing it
      // back to SwiftUI would be a second lookup of a finished sentence.
      ContentUnavailableView {
        Label {
          Text(Message("error.store.title"), localized)
        } icon: {
          Image(systemName: Icon.storeError)
        }
      } description: {
        Text(Message("error.store.body"), localized)
      }
      .onAppear { model.log(diagnostic) }
      // The launch is over even though there is no data: leaving the extended measurement open
      // would never end it, and every failed launch would silently poison the field numbers
      // rather than showing up as a slow one.
      .onAppear { LaunchSignpost.shared.dataOnScreen() }
    case .ready(let list, let metadata):
      draw(list, metadata)
        // Here, and nowhere earlier: this is the first moment REAL data is on screen. The
        // `.loading` ground above is a frame the user cannot read, and closing the
        // measurement there would report an excellent launch and a false one.
        .onAppear { LaunchSignpost.shared.dataOnScreen() }
    }
  }
}

// S2's `TodayView.statusLabel` is GONE, deliberately.
//
// It survived S3a's refactor as a two-argument pass-through kept alive only by the test that
// called it — and that is exactly how it drifted: the list rows had begun passing
// `detail_params` so an unmapped closure quotes the pool's own words, while `statusLabel` still
// called the two-argument `dayState` and rendered "Closed — reason not classified" for the same
// row. A pass-through nothing renders is not a safeguard; it is a second implementation with a
// test attached. The mapping lives once, in `SwimZHKit.dayState` / `dayStateLabel`, and the app
// target now reads it through `PoolRow.verdict` and nowhere else.

#Preview {
  TodayView()
}
