// TodayView.swift — the primary screen: "where can I swim?", end to end.
//
// The view decides nothing. `SwimZHKit` produces a `ListModel` — sections, rows, verdicts,
// banners, counts, the beyond-horizon flag — and this file lays it out. That split is the
// plan's governing constraint: the app target is outside the CRAP gate and a SwiftUI body
// cannot be unit-tested at all, so a rule placed here is a rule nothing measures.
//
// THE BOTTOM OF THE SCREEN IS A SYSTEM TAB BAR — List, Map, Search — decided 2026-09-06 after
// three bars were felt side by side. The bar it replaced was a bottom toolbar holding a
// segmented list/map picker, and the picker drew a flat thumb inside the bar's own glass: glass
// over glass, and the one control on the screen that did not press or drag like Apple's. A tab
// bar's selection is the system's own glass lens — it slides, it can be dragged across the
// tabs, and it minimises as the list scrolls down — and `Tab(role: .search)` turns the bar
// itself into the search field. The all-pools browser went in the same decision: the list
// already holds every pool for the day, nearest first.
//
// Each tab holds its OWN `NavigationStack`, so a push on one page never moves another, and
// every stack has the same one `navigationDestination` over `Route`.
//
// The iOS 26 adoptions the tab bar did not change, each with its reason:
//  * the day strip via `safeAreaBar(edge: .top)` on the scrolling view — see `DayStrip.swift`.
//  * `List`, not `LazyVStack`: not for speed (both are lazy, and 57 rows is noise either way)
//    but for `.swipeActions` and system row and section styling.
//  * `.refreshable` ONLY when a manifest URL is configured, and it ALWAYS answers. The first
//    S5 cut refused the gesture outright: the store changes weekly, so a pull would spin and,
//    on six days in seven, change nothing — and a gesture that usually does nothing teaches
//    the reader to distrust it. Decided 2026-09-06: the pull is worth having when it SAYS
//    something every time. It fetches the manifest and then the data section reports one of
//    four sentences (up to date / updated / could not check / update the app), the time of the
//    check, when the store was built, and any source the build could not refresh. An app with
//    no manifest URL gets no pull at all, because that pull could only ever say "could not
//    check". The automatic launch/foreground check fills the same rows, silently.
//
// Every sentence on this screen is a `Message` from the package, rendered by the one
// `Localized` in the environment (see `Localization.swift`). There is not a single
// user-visible literal left here, and the two that look like one (`metadata.goldValidAsOf`,
// `metadata.horizonEnd`) are the store's own date KEYS put through `Format.storeDate` — they
// were shipped raw at first, which read as `2026-08-24` in all five languages.

import SwiftUI
import SwimZHKit

/// Everywhere a tab's stack can go.
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
  @Environment(\.localized) private var localized
  @State private var model = TodayModel()

  /// Foregrounding is the only moment a refresh is worth attempting beyond launch: the store is
  /// republished weekly, so anything more eager would be a wakeup that learns nothing.
  @Environment(\.scenePhase) private var scenePhase

  /// Whether the day strip is on screen. View state rather than model state: nothing outside
  /// this screen has an opinion about it, and the DECISION it holds is the kit's.
  @State private var showsStrip = true

  /// Whether the list was at its top on the last scroll report — so the NEXT report can tell
  /// an arrival from a rest. See `listReachedTop`.
  @State private var listAtTop = true

  /// The tab bar's pages.
  enum TabPage: Hashable {
    case list, map, filters, search
  }
  /// Which tab. View state: nothing outside this screen has an opinion about it, and it
  /// deliberately does NOT persist — an app that reopened on the map would be answering a
  /// different question from the one it is for.
  @State private var tab: TabPage = .list

  /// The content tab the reader was on last — list or map — so that the SEARCH tab searches
  /// that page rather than always the list. Tapping search from the map used to land on the
  /// list: the reader wanted to search the map they were looking at, with the field over it.
  @State private var searchedContent: TabPage = .list

  /// The reader's text size, for one purpose only: how tall the strip is, which is what sets
  /// the gap between the two thresholds that hide and show it. Read the same way `DayStrip`
  /// reads it, through the same bridge.
  @Environment(\.dynamicTypeSize) private var dynamicTypeSize

  private var stripHeight: Double {
    stripLayout(for: TypeSize(dynamicTypeSize), width: 0).stripHeight
  }

  var body: some View {
    tabShell
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
  }

  /// The tab bar. The selection is the bar's own glass lens; the search tab turns the bar into
  /// the field; the bar minimises as the list scrolls down, which is the same instinct the day
  /// strip's yielding follows. The filters are a TAB — a page, not a sheet — chosen over a pill
  /// above the bar (`tabViewBottomAccessory`, the Music mini-player's slot) on 2026-09-06: the
  /// bar is pure, every control in it is a tab, and the glyph fills when something is narrowed.
  private var tabShell: some View {
    TabView(selection: $tab) {
      Tab(value: TabPage.list) {
        NavigationStack { findPage(searchable: false) }
      } label: {
        Label(Message("nav.list"), systemImage: Icon.list, localized)
      }
      Tab(value: TabPage.map) {
        NavigationStack { mapPage(searchable: false) }
      } label: {
        Label(Message("nav.map"), systemImage: Icon.map, localized)
      }
      Tab(value: TabPage.filters) {
        FilterPage(
          filters: $model.filters, kinds: model.kinds, location: model.location,
          onUseMyLocation: { await model.useMyLocation() },
          onUseNamedPlace: { model.useNamedPlace($0) })
      } label: {
        // The glyph fills when something is narrowed.
        Label(
          Message("mobile.filters"),
          systemImage: model.filters.isNarrowed ? Icon.filterActive : Icon.filter, localized)
      }
      Tab(value: TabPage.search, role: .search) {
        // The page the reader came from, with the field over it — see `searchedContent`.
        NavigationStack {
          if searchedContent == .map {
            mapPage(searchable: true)
          } else {
            findPage(searchable: true)
          }
        }
      }
    }
    .onChange(of: tab) { _, tab in
      if tab == .list || tab == .map { searchedContent = tab }
    }
    .tabBarMinimizeBehavior(.onScrollDown)
    // Selecting the search tab IS the request to search: the bar becomes the field at once,
    // rather than showing an empty page with a second control to press.
    .tabViewSearchActivation(.searchTabSelection)
    // The same feedback the day strip gives for the same kind of act: a selection moved.
    .sensoryFeedback(.selection, trigger: tab)
  }

  /// The find page: the list under the day strip. The search tab is the same page made
  /// searchable — with `Tab(role: .search)` the tab bar itself becomes the field, at the
  /// bottom, under the thumb.
  ///
  /// NO NAVIGATION BAR ON THIS PAGE, and the two halves of that arrived together. First the
  /// TITLE went: it spelled the day out while the strip underneath drew the same fact — one
  /// thing said twice, costing a row of a phone screen for the copy you cannot tap. That left a
  /// full bar holding one overflow button, and a band of empty glass above the strip is worse
  /// than the title was: it costs the same height and says nothing at all. The strip starts at
  /// the top of the screen, and the rows get the ~50 points back.
  @ViewBuilder
  private func findPage(searchable: Bool) -> some View {
    let page =
      ready { list, metadata in
        // The strip attaches to the SCROLLING view, never to a wrapper around it: the system
        // paints its scroll edge effect in response to the scroll view DIRECTLY under the
        // bar, and a `VStack` whose first child is a static strip gives it nothing to answer.
        listDrawn(list, metadata)
          .safeAreaBar(edge: .top) {
            // Present only while it is wanted. Reading DOWN the list takes it away and gives
            // the rows its height; the smallest pull back up returns it, so changing day never
            // costs a scroll to the top of fifty rows. Whether it shows is
            // `SwimZHKit.stripShouldShow` — a rule, and a rule in a `body` is one nothing
            // measures.
            stripIfShown
              .animation(.snappy(duration: 0.22), value: showsStrip)
          }
      }
      .toolbarVisibility(.hidden, for: .navigationBar)
      .navigationDestination(for: Route.self, destination: screen)
    if searchable {
      // ON THE READY PAGE, not on the stack: attached one level up it drew the search field
      // over the loading state — a field for a list that was not there yet.
      searching(page)
    } else {
      page
    }
  }

  /// The map page: the same answer as the list, pinned by the roster's coordinates
  /// (`SwimZHKit.poolPins`), under the day strip.
  @ViewBuilder
  private func mapPage(searchable: Bool) -> some View {
    let page =
      ready { list, _ in
        PoolMapView(pins: poolPins(list.sections, geo: model.geoByPool))
          // ALWAYS up on the map: there is no scroll there to yield it to, and a strip left
          // hidden by the last list scroll would take the day picker away from a screen that
          // cannot get it back.
          .safeAreaBar(edge: .top) {
            DayStrip(chips: model.chips, selection: $model.filters.day)
          }
      }
      .toolbarVisibility(.hidden, for: .navigationBar)
      .navigationDestination(for: Route.self, destination: screen)
    if searchable {
      searching(page)
    } else {
      page
    }
  }

  /// The search field over a page, with pool names as suggestions — the autocomplete the
  /// reader expects over a map. The suggestions are the roster's names through the kit's own
  /// search rule (`browsePools`, the same predicate the list uses), so a name that would match
  /// is a name that will; picking one completes the field and the page shows that pool.
  /// A query that IS a name gets no suggestions, so the list of them makes way for the result.
  private func searching(_ page: some View) -> some View {
    page
      .searchable(
        text: $model.filters.search,
        prompt: Text(Message("nav.findAPool"), localized)
      )
      .searchSuggestions {
        ForEach(suggestions) { pool in
          // A pool's NAME is a proper noun and is never translated.
          Text(verbatim: pool.name)
            .searchCompletion(pool.name)
            .accessibilityIdentifier("searchSuggestion")
        }
      }
  }

  private var suggestions: [PoolRecord] {
    let query = model.filters.search
    guard !query.isEmpty else { return [] }
    return Array(
      browsePools(model.pools, kind: nil, search: query)
        .filter { $0.name != query }
        .prefix(8))
  }

  /// Every destination a stack has, in one place. A `switch` over VIEWS, not over sentences
  /// — `noStateToStringInTheApp` bans the second, and this is the first.
  private func screen(_ route: Route) -> some View {
    destination(route)
      // A pushed screen is its own place: the pool screen is a full map with a drawer at the
      // bottom, and a tab bar (and the filter pill above it) drawn over that drawer is two
      // bars fighting for the thumb. Photos does the same on a photo. The edge swipe and the
      // back button are the ways home.
      .toolbarVisibility(.hidden, for: .tabBar)
  }

  @ViewBuilder
  private func destination(_ route: Route) -> some View {
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

  /// The three states of the store, with the READY one drawn by the caller — each tab draws
  /// a ready store differently, and the other two states the same.
  @ViewBuilder
  private func ready<Drawn: View>(
    @ViewBuilder _ draw: (ListModel, StoreMetadata) -> Drawn
  ) -> some View {
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
      // reserves progress indication for waits a reader can feel. And the search field went
      // with it — `.searchable` is attached to the READY screen below, so the bottom bar
      // arrives with the rows it searches rather than a beat before them, over nothing.
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
        // `.loading` spinner above is a frame the user cannot read, and closing the
        // measurement there would report an excellent launch and a false one.
        .onAppear { LaunchSignpost.shared.dataOnScreen() }
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
    // Arriving back at the top is when a held favourite may take its place at the front of
    // its tier — on screen, animated, and never out from under a thumb. Both halves of that
    // are the kit's (`listReachedTop`, `TodayModel.settleFavouriteOrder`); this only reports.
    if listReachedTop(scrolled: scrolled, wasAtTop: listAtTop) { model.settleFavouriteOrder() }
    listAtTop = listIsAtTop(scrolled: scrolled)
    let shows = stripShouldShow(
      scrolled: scrolled, stripHeight: stripHeight, showing: showsStrip)
    guard shows != showsStrip else { return }
    showsStrip = shows
  }

  /// The list, reporting its scroll so the strip can yield to it.
  private func listDrawn(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
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
    // field lives in the tab bar — which left a whole row of empty screen under the day
    // strip. Reclaimed deliberately, not by nudging paddings until it looked right.
    List {
      // The headline is a FACT, not a control, so it belongs in the content the eye reads
      // first — not riding in the chrome. It lived in the old filter bar, which is what made
      // that bar two lines tall and left it unable to share a row with anything.
      Text(list.headline, localized)
        .font(.screenHeadline)
        // The count ROLLS rather than cutting when the day changes. `.numericText()` is the one
        // content transition that understands digits, and this is the only line in the app
        // whose leading token is one. It costs nothing on the branches with no number in them.
        .contentTransition(.numericText())
        .animation(.snappy(duration: 0.3), value: list.day)
        .accessibilityIdentifier("headline")
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
    .modifier(PullToCheck(enabled: model.canCheckForUpdates) { await model.checkForUpdates() })
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
      // When the store in use was BUILT — the "when was it updated" a pull is asked for. An
      // instant, not a day key, so it goes through `storeInstant`; still shown as itself if
      // a store ever writes a stamp that is not one.
      if !metadata.builtAt.isEmpty {
        LabeledContent(
          content: { Text(verbatim: localized.format.storeInstant(metadata.builtAt)) },
          label: { Text(Message("meta.builtAt"), localized) })
      }
      // What the last check for a newer store found, and when. Nothing until one has run.
      if let check = model.dataStatus.check, let checkedAt = model.dataStatus.checkedAt {
        LabeledContent(
          content: { Text(verbatim: localized.format.dateTime(checkedAt)) },
          label: { Text(check.message, localized) }
        )
        .accessibilityIdentifier("dataCheck")
      }
      // Every source the build kept from an earlier run because it could not reach the site.
      // One row each, named: a reader told "prices: not refreshed since 30 August" can allow
      // for it; a reader told nothing cannot.
      ForEach(staleSources(metadata), id: \.source) { stale in
        Text(
          Message(
            "meta.staleSource",
            [
              "source": localized(stale.name),
              "date": localized.format.storeInstantDay(stale.fetchedAt),
            ]),
          localized
        )
        .foregroundStyle(.secondary)
        .accessibilityIdentifier("staleSource")
      }
      // The ribbon's colour key, reachable from the screen the ribbons are on. It was two taps
      // deep inside an overflow menu — a legend nobody finds is a legend that is not there,
      // and without it the day tail's colours cannot be read at all.
      // The colour key, at the end of the answer — where the colours are.
      NavigationLink(value: Route.legend) {
        Label(Message("nav.accessTypes"), systemImage: Icon.legend, localized)
      }
      .accessibilityIdentifier("legendLink")
      // Who made this, what state the data is in, and how to help — one screen, at the end.
      NavigationLink(value: Route.about) {
        Label(Message("nav.about"), systemImage: Icon.about, localized)
      }
      .accessibilityIdentifier("aboutLink")
    } footer: {
      if model.canCheckForUpdates {
        Text(Message("meta.offlineNote.pull"), localized)
      } else {
        Text(Message("meta.offlineNote"), localized)
      }
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

/// The pull, attached only when it can answer. SwiftUI has no "refreshable if", and a
/// `.refreshable` that runs a no-op is exactly the gesture the header refuses — so the
/// modifier is applied or not, and the DECISION (`canCheckForUpdates`) is the model's.
private struct PullToCheck: ViewModifier {
  let enabled: Bool
  let check: @Sendable () async -> Void

  func body(content: Content) -> some View {
    if enabled {
      content.refreshable { await check() }
    } else {
      content
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
