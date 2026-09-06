// CompactShell.swift — the phone: a system tab bar over the answer.
//
// THE BOTTOM OF THE SCREEN IS A SYSTEM TAB BAR — List, Map, Filters, Search — decided
// 2026-09-06 after three bars were felt side by side. The bar it replaced was a bottom toolbar
// holding a segmented list/map picker, and the picker drew a flat thumb inside the bar's own
// glass: glass over glass, and the one control on the screen that did not press or drag like
// Apple's. A tab bar's selection is the system's own glass lens — it slides, it can be dragged
// across the tabs, and it minimises as the list scrolls down — and `Tab(role: .search)` turns
// the bar itself into the search field. The all-pools browser went in the same decision: the
// list already holds every pool for the day, nearest first.
//
// Each tab holds its OWN `NavigationStack`, so a push on one page never moves another, and
// every stack has the same one `navigationDestination` over `Route` (`routed`).
//
// The iOS 26 adoptions the tab bar did not change, each with its reason:
//  * the day strip via `safeAreaBar(edge: .top)` on the scrolling view — see `AnswerList`.
//  * `.refreshable` ONLY when a manifest URL is configured — see `PullToCheck`.

import SwiftUI
import SwimZHKit

struct CompactShell: View {
  @Environment(\.localized) private var localized
  @Bindable var model: TodayModel
  /// The list tab's stack — the owner's, because it outlives this shell across a fold.
  @Binding var contentPath: [Route]
  /// The map tab's stack — the owner's, for the same reason: the fold carries it over.
  @Binding var mapPath: [Route]
  /// The search tab's stack, kept apart: two `NavigationStack`s bound to one path push twice.
  @State private var searchPath: [Route] = []

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

  /// The tab bar. The selection is the bar's own glass lens; the search tab turns the bar into
  /// the field; the bar minimises as the list scrolls down, which is the same instinct the day
  /// strip's yielding follows. The filters are a TAB — a page, not a sheet — chosen over a pill
  /// above the bar (`tabViewBottomAccessory`, the Music mini-player's slot) on 2026-09-06: the
  /// bar is pure, every control in it is a tab, and the glyph fills when something is narrowed.
  var body: some View {
    TabView(selection: $tab) {
      Tab(value: TabPage.list) {
        NavigationStack(path: $contentPath) { findPage(searchable: false).routed(model) }
      } label: {
        Label(Message("nav.list"), systemImage: Icon.list, localized)
      }
      Tab(value: TabPage.map) {
        NavigationStack(path: $mapPath) { mapPage(searchable: false).routed(model) }
      } label: {
        Label(Message("nav.map"), systemImage: Icon.map, localized)
      }
      Tab(value: TabPage.filters) {
        FilterPage(model: model)
      } label: {
        // The glyph fills when something is narrowed.
        Label(
          Message("mobile.filters"),
          systemImage: model.filters.isNarrowed ? Icon.filterActive : Icon.filter, localized)
      }
      Tab(value: TabPage.search, role: .search) {
        // The page the reader came from, with the field over it — see `searchedContent`.
        NavigationStack(path: $searchPath) {
          if searchedContent == .map {
            mapPage(searchable: true).routed(model)
          } else {
            findPage(searchable: true).routed(model)
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
  @ViewBuilder
  private func findPage(searchable: Bool) -> some View {
    let page =
      StoreStates(model: model) { list, metadata in
        AnswerList(model: model, list: list, metadata: metadata)
      }
      .bare()
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
      StoreStates(model: model) { list, _ in
        PoolMapView(pins: poolPins(list.sections, geo: model.geoByPool))
          // ALWAYS up on the map: there is no scroll there to yield it to, and a strip left
          // hidden by the last list scroll would take the day picker away from a screen that
          // cannot get it back.
          .safeAreaBar(edge: .top) {
            DayStrip(chips: model.chips, selection: $model.filters.day)
          }
      }
      .bare()
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
}
