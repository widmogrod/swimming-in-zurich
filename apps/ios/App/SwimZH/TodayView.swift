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
// A WIDE WINDOW — an unfolded phone, an iPad, a landscape Max — is laid out differently, and the
// difference is keyed off the horizontal SIZE CLASS and nothing else (see `Lab.swift` for why:
// there is no fold API, and the size class is what an unfolded phone will report). Under review
// as `Lab.WideLayout`: `stage` (the map with the list floating over it, the default) and `phone`
// (this layout stretched, the control). The content stack's PATH is one
// `@State` shared by the compact list page and the wide detail column, so a pool open when the
// phone unfolds is still open after — the screen changes shape, not place.
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

  /// Whether the window is wide. THE size-class, not the device: an unfolded phone, an iPad and
  /// a landscape Max all report `.regular`, and a folded phone, a Split View slice and a
  /// portrait phone all report `.compact`. Nothing here asks what the hardware is.
  @Environment(\.horizontalSizeClass) private var sizeClass
  /// Which wide layout is under review. Read through `@AppStorage` so a change in Settings
  /// re-renders the app on return, without a relaunch.
  @AppStorage(Lab.wideLayout) private var wideLayoutRaw = Lab.WideLayout.default.rawValue
  private var wideLayout: Lab.WideLayout { Lab.WideLayout(rawValue: wideLayoutRaw) ?? .default }
  /// Where search and the filters live in a wide window — see `Lab.WideChrome`.
  @AppStorage(Lab.wideChrome) private var wideChromeRaw = Lab.WideChrome.default.rawValue
  private var wideChrome: Lab.WideChrome { Lab.WideChrome(rawValue: wideChromeRaw) ?? .default }
  /// Wide, with the column carrying its own controls: no tab bar at all.
  private var columnChrome: Bool { isWide && wideChrome == .column }
  /// Whether the filters popover is up (column chrome only).
  @State private var showsFilters = false
  /// Whether the column's search row is on screen — pulled for, never resident. The DECISION
  /// is the kit's (`columnControlsShouldShow`); this only records it, from the same scroll
  /// report the strip reads.
  @State private var showsSearch = false
  /// Whether the column's field has the keyboard — one of the two things that pin the row.
  @FocusState private var searchFocused: Bool
  /// How far the stage's map flies in when a pool opens — see `Lab.WideFocus`.
  @AppStorage(Lab.wideFocus) private var wideFocusRaw = Lab.WideFocus.default.rawValue
  private var wideFocus: Lab.WideFocus { Lab.WideFocus(rawValue: wideFocusRaw) ?? .default }
  /// Wide, AND a wide layout is chosen. `phone` is the control: a wide window laid out as the
  /// phone is, so the two others can be judged against it.
  private var isWide: Bool { sizeClass == .regular && wideLayout != .phone }
  /// The window's width, for the column widths the kit derives from it.
  @State private var windowWidth: Double = 0
  /// Which edge the stage's column sits against — flicked across by the reader. Held here
  /// because the MAP has to know it: the map is inset by the column's side, so what it frames is
  /// framed in the part of it the reader can see.
  @State private var columnSide: ColumnSide = .leading

  /// The content stack: the list page's pushes in a compact window, the detail column's in a
  /// wide one. ONE path for both, which is what carries an open pool across a fold or unfold.
  @State private var contentPath: [Route] = []
  /// The map tab's own stack, compact only — a wide window has no map tab.
  @State private var mapPath: [Route] = []
  /// The search tab's stack, kept apart: two `NavigationStack`s bound to one path push twice.
  @State private var searchPath: [Route] = []

  private var stripHeight: Double {
    stripLayout(for: TypeSize(dynamicTypeSize), width: 0).stripHeight
  }

  /// The strip's height as laid out — the kit's number until the first measurement, so the
  /// folding frame is right from the first frame and exact once the legend (which only the
  /// accessibility sizes add) has been measured.
  @State private var measuredStripHeight: Double =
    stripLayout(for: TypeSize(.large), width: 0).stripHeight

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
      .onGeometryChange(for: Double.self) { proxy in
        proxy.size.width
      } action: { width in
        windowWidth = width
      }
      // THE FOLD. Going wide takes the map tab away (the map is on screen anyway), so a reader
      // on it lands on the list — with whatever they had pushed from the map carried over, so
      // unfolding over a pool keeps that pool. Going compact brings the tab back and the path
      // is already the list's.
      .onChange(of: isWide) { _, wide in
        guard wide, tab == .map || searchedContent == .map else { return }
        if tab == .map { tab = .list }
        searchedContent = .list
        if contentPath.isEmpty { contentPath = mapPath }
        mapPath = []
      }
  }

  /// The tab bar — or, in a wide window under the column chrome, no bar: the stage alone, its
  /// column carrying search and the filters. The regular-width tab bar floats at the top centre
  /// of the window, over the column's top; there is no API to move it, so the column chrome
  /// does without it (see `Lab.WideChrome`).
  @ViewBuilder
  private var shell: some View {
    if columnChrome {
      widePage(searchable: true, path: $contentPath)
    } else {
      tabShell
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
        if isWide {
          widePage(searchable: false, path: $contentPath)
        } else {
          NavigationStack(path: $contentPath) { routed(findPage(searchable: false)) }
        }
      } label: {
        Label(Message("nav.list"), systemImage: Icon.list, localized)
      }
      // No map tab in a wide window: both wide layouts keep the map on screen.
      if !isWide {
        Tab(value: TabPage.map) {
          NavigationStack(path: $mapPath) { routed(mapPage(searchable: false)) }
        } label: {
          Label(Message("nav.map"), systemImage: Icon.map, localized)
        }
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
        if isWide {
          widePage(searchable: true, path: $searchPath)
        } else {
          NavigationStack(path: $searchPath) {
            if searchedContent == .map {
              routed(mapPage(searchable: true))
            } else {
              routed(findPage(searchable: true))
            }
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
            VStack(spacing: Design.Space.row) {
              // The column's controls, ONE row: the search field and the filters button,
              // side by side under the grab bar — and only when PULLED FOR. A navigation bar
              // did this first (a title row holding one button, the field in a drawer under
              // it: a band of empty glass), then a resident row; the owner wanted neither
              // above the day strip. Mail hides its search the same way.
              if columnChrome && showsSearch {
                columnControls
                  .transition(.move(edge: .top).combined(with: .opacity))
              }
              stripIfShown
                .animation(.snappy(duration: 0.22), value: showsStrip)
            }
          }
          .animation(.snappy(duration: 0.22), value: showsSearch)
      }
    if columnChrome {
      // No navigation bar in the column either: its controls are in the bar above.
      bare(page)
    } else if searchable {
      // ON THE READY PAGE, not on the stack: attached one level up it drew the search field
      // over the loading state — a field for a list that was not there yet.
      searching(bare(page))
    } else {
      bare(page)
    }
  }

  /// A page with NO navigation bar — see `findPage`'s header for why the phone has none.
  private func bare(_ page: some View) -> some View {
    page.toolbarVisibility(.hidden, for: .navigationBar)
  }

  /// The column's search field and filters button, in one row. The field is the app's own —
  /// not `.searchable`, which needs a navigation bar to live in — bound to the same
  /// `filters.search` the phone's field writes, so the list narrows as the reader types.
  private var columnControls: some View {
    HStack(spacing: Design.Space.row) {
      HStack(spacing: Design.Space.row) {
        Image(systemName: Icon.noMatch)
          .foregroundStyle(.secondary)
        TextField(
          text: $model.filters.search, prompt: Text(Message("nav.findAPool"), localized)
        ) {
          Text(Message("nav.findAPool"), localized)
        }
        .textFieldStyle(.plain)
        .autocorrectionDisabled()
        .submitLabel(.search)
        .focused($searchFocused)
        .accessibilityIdentifier("columnSearch")
        if !model.filters.search.isEmpty {
          Button {
            model.filters.search = ""
          } label: {
            Image(systemName: Icon.clearSearch)
              .foregroundStyle(.secondary)
          }
          .buttonStyle(.plain)
          .accessibilityLabel(Text(Message("nav.findAPool"), localized))
        }
      }
      .padding(.horizontal, Design.Space.gutter)
      .frame(minHeight: Design.hitTarget)
      .background(.quaternary, in: Capsule())
      filtersButton
    }
    .padding(.horizontal, Design.Space.gutter)
  }

  /// The filters, behind one button, as a POPOVER: a form-sized surface anchored to the
  /// button, not a screen. The glyph fills when something is narrowed, as the tab's does.
  private var filtersButton: some View {
    Button {
      showsFilters.toggle()
    } label: {
      Image(systemName: model.filters.isNarrowed ? Icon.filterActive : Icon.filter)
        .font(.screenHeadline)
        .frame(width: Design.hitTarget, height: Design.hitTarget)
        .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel(Text(Message("mobile.filters"), localized))
    .accessibilityIdentifier("filtersButton")
    .popover(isPresented: $showsFilters, arrowEdge: .top) {
      FilterPage(
        filters: $model.filters, kinds: model.kinds, location: model.location,
        onUseMyLocation: { await model.useMyLocation() },
        onUseNamedPlace: { model.useNamedPlace($0) }
      )
      .frame(minWidth: listColumnMinimumWidth, minHeight: formPopoverHeight)
    }
  }

  /// A page with the one `navigationDestination` every stack has. Attached by the CALLER, on
  /// the stack's root, so the page itself knows nothing about which stack it is in.
  private func routed(_ page: some View) -> some View {
    page.navigationDestination(for: Route.self, destination: screen)
  }

  /// The wide window's page. Never called for `phone`: that layout is `isWide == false`.
  ///
  /// STAGE: the map is the screen; the list floats over its leading side in a glass card, and
  /// a tapped pool's facts take the card while the map flies to the pool with its neighbours'
  /// pins kept. The map is inset by the card's width so what it frames is framed in the part
  /// of it the reader can see. The map's own pin card opens the same facts in the same card —
  /// it REPLACES the column's stack rather than pushing on it, so pin after pin never piles
  /// up screens behind the back button.
  private func widePage(searchable: Bool, path: Binding<[Route]>) -> some View {
    ZStack(alignment: .topLeading) {
      ready { list, _ in
        PoolMapView(
          pins: poolPins(list.sections, geo: model.geoByPool),
          focus: focusedPool(path.wrappedValue), focusSpanMetres: wideFocus.spanMetres,
          open: { path.wrappedValue = [.pool($0)] }
        )
        .safeAreaPadding(
          columnSide == .leading ? .leading : .trailing,
          listColumnWidth(in: windowWidth) + Design.Space.gutter)
      }
      StageColumn(windowWidth: windowWidth, side: $columnSide) {
        NavigationStack(path: path) {
          routed(findPage(searchable: searchable))
            .containerBackground(.clear, for: .navigation)
        }
        .environment(\.poolPresentation, .column)
      }
    }
  }

  /// The pool the stage's column is showing: the top of its stack, when that is a pool.
  private func focusedPool(_ path: [Route]) -> String? {
    if case .pool(let poolID)? = path.last { return poolID }
    return nil
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
    if searchable {
      searching(bare(page))
    } else {
      bare(page)
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
      // back button are the ways home. In a WIDE window the push lands in a column beside the
      // list, which stays in use — so the bar stays too.
      .toolbarVisibility(isWide ? .automatic : .hidden, for: .tabBar)
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
      // IDENTITY FOLLOWS THE POOL. On the stage a pin REPLACES the open pool in the column's
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
  /// The strip, in a frame that FOLDS when it yields. An `if` alone took the strip out of the
  /// bar in one step: the transition animated the strip's own fade, but the bar's height — and
  /// so the list's top inset — changed at once, and the rows jumped by a strip's height under
  /// the finger ("the animation of days hiding is not smooth"). The frame around it now animates
  /// from the strip's measured height to zero, so the bar and the list move together on one
  /// curve; the strip itself still leaves the tree, so a hidden strip is hidden to VoiceOver and
  /// to the driven tests alike.
  private var stripIfShown: some View {
    ZStack(alignment: .bottom) {
      if showsStrip {
        DayStrip(chips: model.chips, selection: $model.filters.day)
          .onGeometryChange(for: Double.self) { proxy in
            proxy.size.height
          } action: { height in
            if height > 0 { measuredStripHeight = height }
          }
          .transition(.opacity)
      }
    }
    .frame(height: showsStrip ? measuredStripHeight : 0, alignment: .bottom)
    .clipped()
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
    if columnChrome {
      let search = columnControlsShouldShow(
        scrolled: scrolled, showing: showsSearch,
        pinned: searchFocused || !model.filters.search.isEmpty)
      if search != showsSearch { showsSearch = search }
    }
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
    // On the stage the list is inside a glass card, and the card is the ground — see
    // `StageColumn`. On the phone the list keeps the system's grouped ground.
    .scrollContentBackground(isWide ? .hidden : .automatic)
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
