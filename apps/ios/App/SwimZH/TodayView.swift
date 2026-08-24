// TodayView.swift — the primary screen: "where can I swim?", end to end.
//
// The view decides nothing. `SwimZHKit` produces a `ListModel` — sections, rows, verdicts,
// banners, counts, the beyond-horizon flag — and this file lays it out. That split is the
// plan's governing constraint: the app target is outside the CRAP gate and a SwiftUI body
// cannot be unit-tested at all, so a rule placed here is a rule nothing measures.
//
// The iOS 26 adoptions, each with its reason:
//  * `.searchable` INLINE WITH CONTENT (`navigationBarDrawer(displayMode: .always)`) — the HIG
//    blesses that placement for FILTERING, which is exactly what this search does; it never
//    navigates anywhere.
//  * the filter bar via `safeAreaBar(edge:)` — see `FilterBar.swift`.
//  * `List`, not `LazyVStack`: not for speed (both are lazy, and 57 rows is noise either way)
//    but for `.swipeActions` and system row and section styling.
//  * NO `.refreshable`: the store is bundle-only until S5, so a pull-to-refresh would be a
//    lie — it would spin and change nothing.
//
// Strings are English literals for now. S4 fills `Localizable.xcstrings` in the PACKAGE, and
// the lint it brings catches anything left behind here.

import SwiftUI
import SwimZHKit

struct TodayView: View {
  @State private var model = TodayModel()
  /// The zoom transition's namespace. BOTH halves are required and neither works alone: the row
  /// carries `matchedTransitionSource(id:in:)`, the destination carries
  /// `navigationTransition(.zoom(sourceID:in:))`, and they meet on this namespace.
  @Namespace private var zoom

  var body: some View {
    NavigationStack {
      content
        .navigationTitle("Swim in Zürich")
        .searchable(
          text: $model.filters.search,
          placement: .navigationBarDrawer(displayMode: .always),
          prompt: "Find a pool"
        )
        .toolbar { browseMenu }
        .navigationDestination(for: String.self) { poolID in
          FacilitySheetLoader(
            poolID: poolID, day: model.filters.day, person: model.filters.person,
            load: { await model.facility($0) }
          )
          .navigationTransition(.zoom(sourceID: poolID, in: zoom))
        }
    }
    .task { await model.load() }
  }

  /// The two screens that are not about a date: the whole roster, and what the session labels
  /// mean. Both are pushes rather than tabs — this app has one primary task, and a tab bar
  /// would give three equal ones.
  private var browseMenu: some ToolbarContent {
    ToolbarItem(placement: .topBarTrailing) {
      Menu {
        NavigationLink {
          PoolsBrowser(
            pools: model.pools, day: model.filters.day, person: model.filters.person,
            load: { await model.facility($0) })
        } label: {
          Label("All pools", systemImage: "list.bullet")
        }
        NavigationLink {
          AccessTypesView()
        } label: {
          Label("What the labels mean", systemImage: "questionmark.circle")
        }
      } label: {
        Label("Browse", systemImage: "ellipsis.circle")
      }
    }
  }

  @ViewBuilder
  private var content: some View {
    switch model.state {
    case .loading:
      ProgressView()
    case .failed(let message):
      ContentUnavailableView(
        "Cannot read the pool data", systemImage: "xmark.icloud", description: Text(message)
      )
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
    VStack(spacing: 0) {
      DayStrip(chips: model.chips, selection: $model.filters.day)
      listOrEmpty(list, metadata)
    }
    .safeAreaBar(edge: .bottom) {
      FilterBar(filters: $model.filters, kinds: model.kinds, headline: list.headline)
    }
  }

  @ViewBuilder
  private func listOrEmpty(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    if list.beyondHorizon {
      beyondHorizon(metadata)
    } else if list.isEmpty {
      // "Nothing matched" is NOT "everything is closed", and the wording says so: an empty
      // result is about the filters, and the remedy is in the user's hands.
      ContentUnavailableView(
        "No pools match", systemImage: "line.3.horizontal.decrease.circle",
        description: Text(
          "Try a wider area, another day, or fewer filters. This is not the "
            + "same as everything being closed.")
      )
    } else {
      answerList(list, metadata)
    }
  }

  /// The fifth day state, and it is the WHOLE SCREEN's state rather than any pool's: past the
  /// horizon there are no rows at all, so nothing here may read as a closure.
  private func beyondHorizon(_ metadata: StoreMetadata) -> some View {
    ContentUnavailableView(
      "Beyond the published horizon", systemImage: "calendar.badge.exclamationmark",
      description: Text(
        "We publish answers through \(metadata.horizonEnd). This is not the "
          + "same as the pools being closed — we simply have not resolved this day yet.")
    )
  }

  private func answerList(_ list: ListModel, _ metadata: StoreMetadata) -> some View {
    List {
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
          Label(section.title, systemImage: section.tier.symbol)
        }
      }
      provenance(metadata)
    }
    .listStyle(.insetGrouped)
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
      LabeledContent("Data from", value: metadata.goldValidAsOf)
      LabeledContent("Answers through", value: metadata.horizonEnd)
    } footer: {
      Text("Works offline. Everything here was resolved before the app shipped.")
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
