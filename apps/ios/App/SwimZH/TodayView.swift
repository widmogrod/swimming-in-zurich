// TodayView.swift — the primary screen: "where can I swim?", end to end.
//
// The view decides nothing. `SwimZHKit` produces a `ListModel` — sections, rows, verdicts,
// banners, counts, the beyond-horizon flag — and this file lays it out. That split is the
// plan's governing constraint: the app target is outside the CRAP gate and a SwiftUI body
// cannot be unit-tested at all, so a rule placed here is a rule nothing measures.
//
// The iOS 26 adoptions, each with its reason:
//  * `.searchable` reached from the toolbar (`.searchToolbarBehavior(.minimize)`) — on iPhone
//    iOS 26 already draws the field at the bottom, so the control shares the system's bar with
//    the filter button instead of adding a surface. THE ALL-POOLS BROWSER NOW DOES THE SAME.
//    It used to pin its field open with `navigationBarDrawer(displayMode: .always)` — the very
//    form a lint bans on this screen for pinning the chrome — so the app searched two different
//    ways depending on which list you were looking at.
//  * the filter bar via `safeAreaBar(edge:)` — see `FilterBar.swift`.
//  * `List`, not `LazyVStack`: not for speed (both are lazy, and 57 rows is noise either way)
//    but for `.swipeActions` and system row and section styling.
//  * NO `.refreshable`: since S5 the store CAN be updated, but not by pulling on a list. The
//    published store changes weekly and the check runs at launch and on foreground; a
//    pull-to-refresh would spin for a second and, on all but one day in seven, change nothing.
//    A gesture that usually does nothing is a gesture that teaches the reader to distrust it.
//
// Every sentence on this screen is a `Message` from the package, rendered by the one
// `Localized` in the environment (see `Localization.swift`). There is not a single
// user-visible literal left here, and the two that look like one (`metadata.goldValidAsOf`,
// `metadata.horizonEnd`) are the store's own date KEYS put through `Format.storeDate` — they
// were shipped raw at first, which read as `2026-08-24` in all five languages.

import SwiftUI
import SwimZHKit

/// Everywhere this stack can go.
///
/// ONE route type, and every push is a value of it. The stack used to mix the two: rows pushed a
/// `String` into a `navigationDestination`, while the browse menu pushed destination VIEWS. That
/// is not a style difference — `BehaviourTests.testTheBrowserOpensAPoolToo` caught what it does.
/// Tapping a pool inside the all-pools browser pushed the sheet AND re-activated the menu's
/// view-based link, so the browser landed back on top of the sheet you had just opened. Mixing
/// the two forms in one stack is the bug; this enum is the fix.
enum Route: Hashable {
  case pool(String)
  case allPools
  case legend
}

/// The two ways of drawing ONE answer.
///
/// A MODE, not a destination: switching does not push, does not change the day, the radius, the
/// filters or the search, and cannot show a pool the other one hides — both are handed the same
/// finished `[ListSection]`. That is the whole reason it is a segmented control in the bar
/// rather than a third entry beside "All pools": a control that stays put and re-renders what is
/// already on screen is a different promise from one that takes you somewhere.
enum ViewMode: Hashable {
  case list
  case map
}

struct TodayView: View {
  @Environment(\.localized) private var localized
  @State private var model = TodayModel()
  /// The zoom transition's namespace. BOTH halves are required and neither works alone: the row
  /// carries `matchedTransitionSource(id:in:)`, the destination carries
  /// `navigationTransition(.zoom(sourceID:in:))`, and they meet on this namespace.
  @Namespace private var zoom

  /// Foregrounding is the only moment a refresh is worth attempting beyond launch: the store is
  /// republished weekly, so anything more eager would be a wakeup that learns nothing.
  @Environment(\.scenePhase) private var scenePhase

  /// Whether the day strip is on screen. View state rather than model state: nothing outside
  /// this screen has an opinion about it, and the DECISION it holds is the kit's.
  @State private var showsStrip = true

  /// List or map. View state: nothing outside this screen has an opinion about it, and it
  /// deliberately does NOT persist — an app that reopened on the map would be answering a
  /// different question from the one it is for.
  @State private var mode: ViewMode = .list

  /// The reader's text size, for one purpose only: how tall the strip is, which is what sets
  /// the gap between the two thresholds that hide and show it. Read the same way `DayStrip`
  /// reads it, through the same bridge.
  @Environment(\.dynamicTypeSize) private var dynamicTypeSize

  private var stripHeight: Double {
    stripLayout(for: TypeSize(dynamicTypeSize), width: 0).stripHeight
  }

  var body: some View {
    NavigationStack {
      content
        // NO NAVIGATION BAR ON THIS SCREEN, and the two halves of that arrived together.
        //
        // First the TITLE went: it spelled the day out while the strip underneath drew the
        // same fact — one thing said twice, costing a row of a phone screen for the copy you
        // cannot tap. That left a full bar holding one overflow button, and a band of empty
        // glass above the strip is worse than the title was: it costs the same height and says
        // nothing at all. So the button went to the bottom bar with the other two controls,
        // and the bar it was keeping alive went with it. The strip now starts at the top of the
        // screen, and the rows get the ~50 points back.
        .toolbarVisibility(.hidden, for: .navigationBar)
        // No placement argument, and deliberately so. On iOS 26 the search field ALREADY lives
        // at the bottom on iPhone — that is the platform's own placement, not something to be
        // arranged. The two attempts that fought it both added a surface: `.minimize` UNDER a
        // custom bar of ours, and an `isPresented` binding that left the field resident anyway,
        // stacked below. What was wrong was the custom bar, not the modifier: with the filter
        // control moved into the system's own bottom bar, `.minimize` collapses the field into
        // the same bar. The all-pools browser says exactly this, in the same two modifiers.
        .searchable(
          text: $model.filters.search,
          prompt: Text(Message("nav.findAPool"), localized)
        )
        // Collapsed to a glyph rather than a resident field. Both were driven and screenshotted:
        // resident puts a full-width field in the bottom bar for a control most sessions never
        // use, and neither form changes what happens WHEN you open it — see the toolbar below.
        .searchToolbarBehavior(.minimize)
        .navigationDestination(for: Route.self, destination: screen)
    }
    .task {
      await model.load()
      // AFTER the screen has answered. The refresh is a background nicety; making the first
      // answer wait on a network round trip would trade the app's whole premise — an answer
      // with no network — for a store that is at most seven days fresher.
      await model.refreshStore()
    }
    .onChange(of: scenePhase) { _, phase in
      guard phase == .active else { return }
      Task { await model.refreshStore() }
    }
  }

  /// LIST OR MAP, and it is the one control on this screen that is neither a search nor a
  /// filter.
  ///
  /// A segmented picker rather than the single toggling button Maps uses, and the reason is the
  /// complaint it answers: a button whose glyph changes cannot say whether it shows where you
  /// are or where you would go. Two segments, one of them lit, says it without a word — and the
  /// words are there anyway for VoiceOver.
  private var modePicker: some View {
    Picker(selection: $mode) {
      Label(Message("nav.list"), systemImage: Icon.list, localized).tag(ViewMode.list)
      Label(Message("nav.map"), systemImage: Icon.map, localized).tag(ViewMode.map)
    } label: {
      Text(Message("nav.map"), localized)
    }
    .pickerStyle(.segmented)
    .accessibilityIdentifier("viewMode")
  }

  /// Every destination this stack has, in one place. A `switch` over VIEWS, not over sentences
  /// — `noStateToStringInTheApp` bans the second, and this is the first.
  @ViewBuilder
  private func screen(_ route: Route) -> some View {
    switch route {
    case .pool(let poolID):
      FacilitySheetLoader(
        poolID: poolID, day: model.filters.day, person: model.filters.person,
        // The row the user tapped, the pool's place, and whether the answer is for today —
        // the three things that turn a table of published facts into a screen about a pool.
        // See `PoolHeader`.
        row: model.row(poolID), point: model.geoByPool[poolID], isToday: model.isToday,
        load: { await model.facility($0) },
        live: { await model.liveTemperature(poiid: $0) }
      )
      .navigationTransition(.zoom(sourceID: poolID, in: zoom))
    case .allPools:
      PoolsBrowser(pools: model.pools)
    case .legend:
      AccessTypesView()
    }
  }

  @ViewBuilder
  private var content: some View {
    switch model.state {
    case .loading:
      ProgressView()
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
      screen(list, metadata)
        // Here, and nowhere earlier: this is the first moment REAL data is on screen. The
        // `.loading` spinner above is a frame the user cannot read, and closing the
        // measurement there would report an excellent launch and a false one.
        .onAppear { LaunchSignpost.shared.dataOnScreen() }
    }
  }

  private func screen(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    // Both bars attach to the SCROLLING view, never to a wrapper around it. A `VStack` here
    // was the whole defect: the navigation bar collapses its title, and the system paints its
    // scroll edge effect — the Liquid Glass — in response to the scroll view DIRECTLY under
    // it. Given a stack whose first child is a static strip, it has nothing to respond to, so
    // the title never shrank, neither bar got glass, and the screen opened with a third of
    // itself already spent.
    drawn(list, metadata)
      .safeAreaBar(edge: .top) {
        // Present only while it is wanted. Reading DOWN the list takes it away and gives the
        // rows its height; the smallest pull back up returns it, so changing day never costs a
        // scroll to the top of fifty rows. Whether it shows is `SwimZHKit.stripShouldShow` —
        // a rule, and a rule in a `body` is one nothing measures.
        stripIfShown
          .animation(.snappy(duration: 0.22), value: showsStrip)
      }
      // The strip is ALWAYS up on the map: there is no scroll there to yield it to, and a
      // strip left hidden by the last list scroll would take the day picker away from a screen
      // that cannot get it back.
      .onChange(of: mode) { _, _ in showsStrip = true }
      // ONE bottom bar, drawn by the system: the filter control shares its glass with the
      // search field rather than floating above it. A `safeAreaBar` of our own here is what
      // produced two stacked surfaces and left rows hidden behind them — the system insets
      // the scroll view for its own toolbar, and cannot for ours.
      .animation(.smooth(duration: 0.28), value: mode)
      .toolbar {
        // THE SEARCH FIELD, PLACED. `.searchToolbarBehavior(.minimize)` says the field is
        // collapsed; it does not say WHERE, and the answer was the NAVIGATION bar — the field
        // collapsed into the same top pill as the browse menu, so opening search took that bar
        // over and the menu went with it. That is the defect a reader reported after every
        // gate here was green. `DefaultToolbarItem` is what actually moves the system's own
        // search item down beside the filter, which this file's comments had claimed since S3b.
        DefaultToolbarItem(kind: .search, placement: .bottomBar)
        // Spacer BETWEEN them: search at the leading edge, the filter at the trailing one.
        ToolbarSpacer(.flexible, placement: .bottomBar)
        ToolbarItem(placement: .bottomBar) { modePicker }
        ToolbarSpacer(.flexible, placement: .bottomBar)
        ToolbarItem(placement: .bottomBar) {
          FilterButton(filters: $model.filters, kinds: model.kinds)
        }
      }
  }

  @ViewBuilder
  private var stripIfShown: some View {
    if showsStrip {
      DayStrip(chips: model.chips, selection: $model.filters.day)
        .transition(.move(edge: .top).combined(with: .opacity))
    }
  }

  /// Read the scroll, ask the kit, record the answer.
  ///
  /// It does NOT call `withAnimation`. This runs on every frame of a scroll, and starting an
  /// animation from in here is how the app stopped ever reporting itself idle; the animation is
  /// declared on the bar instead, against this one value.
  private func strip(scrolledTo scrolled: Double) {
    let shows = stripShouldShow(
      scrolled: scrolled, stripHeight: stripHeight, showing: showsStrip)
    guard shows != showsStrip else { return }
    showsStrip = shows
  }

  /// The answer, in whichever mode is selected.
  ///
  /// A `switch` over VIEWS — the same shape `screen(_ route:)` uses, and for the same reason:
  /// this file maps a state onto a rendering and never onto a sentence.
  @ViewBuilder
  private func drawn(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    switch mode {
    case .list:
      listOrEmpty(list, metadata)
        // Measured from the TOP OF THE CONTENT, not from the scroll view's own offset: hiding
        // the strip shrinks the top inset by its whole height and moves the raw offset by the
        // same amount, which is a jump in exactly the direction that would re-show it. See
        // `stripShouldShow`.
        .onScrollGeometryChange(for: Double.self) { geometry in
          geometry.contentOffset.y + geometry.contentInsets.top
        } action: { _, scrolled in
          strip(scrolledTo: scrolled)
        }
        .transition(.opacity)
    case .map:
      // The SAME sections the list is drawing, pinned by the roster's coordinates. See
      // `SwimZHKit.poolPins`.
      PoolMapView(pins: poolPins(list.sections, geo: model.geoByPool))
        .transition(.opacity)
    }
  }

  @ViewBuilder
  private func listOrEmpty(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    if list.beyondHorizon {
      beyondHorizon(metadata)
    } else if list.isEmpty {
      // "Nothing matched" is NOT "everything is closed", and the wording says so: an empty
      // result is about the filters, and the remedy is in the user's hands.
      ContentUnavailableView {
        Label {
          Text(Message("combo.noPoolsMatch"), localized)
        } icon: {
          // The SAME glyph the browser's empty state uses. One sentence, one picture: the
          // two screens shipped `magnifyingglass` and the filter icon for the same words.
          Image(systemName: Icon.noMatch)
        }
      } description: {
        Text(Message("state.none.body.phone"), localized)
      }
    } else {
      answerList(list, metadata)
    }
  }

  /// The fifth day state, and it is the WHOLE SCREEN's state rather than any pool's: past the
  /// horizon there are no rows at all, so nothing here may read as a closure.
  private func beyondHorizon(_ metadata: StoreMetadata) -> some View {
    ContentUnavailableView {
      Label {
        Text(Message("state.beyondHorizon"), localized)
      } icon: {
        Image(systemName: Icon.beyondHorizon)
      }
    } description: {
      Text(
        Message(
          "state.beyondHorizon.body", ["date": localized.format.storeDate(metadata.horizonEnd)]),
        localized)
    }
  }

  private func answerList(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    // The list reserves a top margin for chrome that is no longer resident there — the search
    // field moved into the toolbar — which left a whole row of empty screen under the day
    // strip. Reclaimed deliberately, not by nudging paddings until it looked right.
    List {
      // The headline is a FACT, not a control, so it belongs in the content the eye reads
      // first — not riding in the chrome. It lived in the old filter bar, which is what made
      // that bar two lines tall and left it unable to share a row with anything.
      Text(list.headline, localized)
        .font(.screenHeadline)
        .listRowSeparator(.hidden)
        .listRowBackground(Color.clear)
        .listRowInsets(
          .init(
            top: 0, leading: Design.Space.gutter, bottom: 0, trailing: Design.Space.gutter)
        )
        .frame(maxWidth: .infinity, alignment: .leading)
      banners(list)
      ForEach(list.sections) { section in
        Section {
          // ONE view per element, always. A `ForEach` element that resolves to a VARIABLE
          // number of views forces `List` to build every row's body just to learn the
          // identifiers (WWDC23 10160) — the laziness this screen must not lose as S3b adds
          // the expandable Gantt. `PoolRowView` is that one view; the lint keeps it that way.
          ForEach(section.rows) { row in
            PoolRowView(
              row: row,
              isFavourite: model.isFavourite(row.poolID),
              isToday: list.isToday,
              isExpanded: model.isExpanded(row.poolID),
              namespace: zoom,
              onToggleFavourite: { model.toggleFavourite(row.poolID) },
              onToggleExpanded: { model.toggleExpanded(row.poolID) }
            )
          }
        } header: {
          Label(section.title, systemImage: section.tier.symbol, localized)
        }
      }
      provenance(metadata)
    }
    .listStyle(.insetGrouped)
    // Inset-grouped sections default to about forty points of air between them. On a screen
    // whose whole job is a ranked list of six tiers, that is a row of pools spent on gaps.
    .listSectionSpacing(.compact)
    .contentMargins(.top, Design.Space.row, for: .scrollContent)
  }

  @ViewBuilder
  private func banners(_ list: ListModel) -> some View {
    if !list.banners.isEmpty {
      Section {
        ForEach(list.banners) { banner in
          BannerView(banner: banner)
        }
      }
    }
  }

  private func provenance(_ metadata: StoreMetadata) -> some View {
    Section {
      // The VALUES are the store's own date KEYS (`2026-08-24`), so they go through
      // `Format.storeDate` before a reader sees them — the same fact the browser renders as
      // "24 August 2026". Shipping the key itself was a five-language regression hiding inside
      // a `Text(verbatim:)` that looked, correctly, like a value.
      // Each row is shown only when the store actually carries the stamp: the exporter writes
      // `gold_valid_as_of or ""`, and "Data from" followed by nothing is a blank where a fact
      // should be. An absent stamp means no row, not an empty one.
      stampRow(metadata.goldValidAsOf, label: "meta.dataFrom")
      stampRow(metadata.horizonEnd, label: "meta.answersThrough")
      // The ribbon's colour key, reachable from the screen the ribbons are on. It was two taps
      // deep inside an overflow menu — a legend nobody finds is a legend that is not there,
      // and without it the day tail's colours cannot be read at all.
      // THE WHOLE ROSTER, and the colour key, together at the end of the answer.
      //
      // "All pools" was a bottom-bar button until the map arrived and the bar ran out of room
      // for a fourth control. It belongs here rather than under an ellipsis: this screen
      // answers "where can I swim on this day", the map answers the same question spatially,
      // and the roster is the reference behind both — which is the same kind of thing the
      // legend is, in the same place, one tap away.
      NavigationLink(value: Route.allPools) {
        Label(Message("nav.allPools"), systemImage: Icon.allPools, localized)
      }
      .accessibilityIdentifier("allPoolsLink")
      NavigationLink(value: Route.legend) {
        Label(Message("nav.accessTypes"), systemImage: Icon.legend, localized)
      }
      .accessibilityIdentifier("legendLink")
    } footer: {
      Text(Message("meta.offlineNote"), localized)
    }
  }

  /// One dated row from `meta`, or nothing at all when the store carries no stamp.
  @ViewBuilder
  private func stampRow(_ key: String, label: String) -> some View {
    if !key.isEmpty {
      LabeledContent(
        content: { Text(verbatim: localized.format.storeDate(key)) },
        label: { Text(Message(label), localized) })
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
