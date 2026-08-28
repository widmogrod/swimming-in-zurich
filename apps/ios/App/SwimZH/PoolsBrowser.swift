// PoolsBrowser.swift — every pool in the city, whatever today's answer happens to contain.
//
// The web's "all pools" tab, and it exists for the same reason there: the FIND screen answers
// "where can I swim on this date", which is narrowed by a radius, a kind filter and a search —
// so a pool can be entirely absent from it while still being a pool. This screen is the roster,
// read from the same store, filtered only by `kind` and by name.
//
// Its rows carry the pool's FRESHNESS, not a schedule: a pool that publishes no timetable is
// shown as exactly that, never as closed. The wording comes from `SwimZHKit.freshnessLabel`,
// the same function the detail sheet reads, so the browser and the sheet cannot say different
// things about the same pool.
//
// WHAT THE HIG REVIEW CHANGED HERE. This screen and the find screen are two lists of pools that
// push the same destination, and they were doing all four of the following differently:
//
//  * SEARCH. This one pinned its field open with `navigationBarDrawer(displayMode: .always)` —
//    the exact form `UILintTests` bans on the find screen, because `.always` is a pin rather
//    than a placement. Both now reach the field from the bar the thumb is already near.
//  * THE TITLE. Large here, inline everywhere else. Inline now.
//  * THE FILTER. A menu hanging off the top bar, wearing the same glyph as the find screen's
//    bottom-bar button, which opened a sheet. One idiom now: same glyph, same corner, same
//    sheet, and it fills when something is narrowed.
//  * THE PUSH. This screen pushed a destination VIEW while the find screen pushed a VALUE. Same
//    pool, same sheet, two ways of getting there. It pushes the VALUE now, into the stack's one
//    `navigationDestination` — which is also why it no longer carries `day`, `person`, `load`
//    and `live` of its own.
//
// WHAT IT DOES *NOT* SHARE, and this was measured rather than reasoned. The first version of
// this change also gave these rows `matchedTransitionSource(id: pool.id, in: namespace)`, so the
// push would zoom exactly like the find screen's. Both lists are in the stack at once, so the
// same id was then claimed TWICE in one namespace — and `BehaviourTests.testTheBrowserOpensAPool
// Too` caught what that does: you tap a pool, the sheet pushes, and the stack lands back on the
// browser. A correct push with the system's ordinary animation beats a zoom that undoes itself,
// so these rows claim no transition source at all.

import SwiftUI
import SwimZHKit

struct PoolsBrowser: View {
  @Environment(\.localized) private var localized
  let pools: [PoolRecord]

  @State private var kind: String?
  @State private var search = ""
  @State private var showingFilters = false

  var body: some View {
    listOrEmpty
      .navigationTitle(Text(Message("nav.allPools"), localized))
      .navigationBarTitleDisplayMode(.inline)
      .searchable(text: $search, prompt: Text(Message("nav.findAPool"), localized))
      .searchToolbarBehavior(.minimize)
      .toolbar {
        // Same bottom bar, same order, same reason as the find screen — see `TodayView`.
        DefaultToolbarItem(kind: .search, placement: .bottomBar)
        ToolbarSpacer(.flexible, placement: .bottomBar)
        ToolbarItem(placement: .bottomBar) { filterButton }
      }
      .sheet(isPresented: $showingFilters) {
        KindFilterSheet(kind: $kind, kinds: kinds)
      }
  }

  /// The same control the find screen has, in the same place, wearing the same glyph — filled
  /// when it is narrowing something.
  private var filterButton: some View {
    Button {
      showingFilters = true
    } label: {
      Label {
        Text(Message("mobile.filters"), localized)
      } icon: {
        Image(systemName: kind == nil ? Icon.filter : Icon.filterActive)
      }
    }
    .accessibilityValue(Text(selectedKind, localized))
    .accessibilityIdentifier("filterButton")
  }

  /// What the filter is narrowed to, for the reader who cannot see the filled glyph. The VALUE,
  /// not the label — the same reason the find screen's button speaks its summary tags.
  private var selectedKind: Wording {
    kind.map { Wording.message(poolKindLabel($0)) } ?? .key("filter.allKinds")
  }

  /// The empty state REPLACES the list rather than floating over it. As an `.overlay` the rows,
  /// the separators and the section background stayed visible underneath the sentence saying
  /// there was nothing to show.
  @ViewBuilder
  private var listOrEmpty: some View {
    if shown.isEmpty {
      // The label/icon/description triple takes a `LocalizedStringKey` title, so a `Text` has
      // to go through the ViewBuilder form instead — the title is already localised and must
      // not be looked up a second time.
      ContentUnavailableView {
        Label {
          Text(Message("combo.noPoolsMatch"), localized)
        } icon: {
          Image(systemName: Icon.noMatch)
        }
      } description: {
        Text(Message("browser.noMatch.body"), localized)
      }
    } else {
      list
    }
  }

  private var list: some View {
    List {
      ForEach(shown) { pool in
        // The VALUE, into the stack's one destination — the same push the find screen makes,
        // with the same zoom source. See the header.
        NavigationLink(value: Route.pool(pool.id)) {
          PoolBrowserRow(pool: pool)
        }
        .accessibilityIdentifier("browserRow")
      }
    }
    .listStyle(.insetGrouped)
  }

  // Both rules live in `SwimZHKit`, where a test drives them: the search predicate is the
  // SAME one the find screen uses, and the kind list comes from the roster rather than from a
  // day's answer.
  private var kinds: [String] { poolKinds(pools) }

  private var shown: [PoolRecord] { browsePools(pools, kind: kind, search: search) }
}

/// The browser's one filter, in the same shape the find screen's sheet uses: a `Form`, standard
/// controls, and a confirmation action to dismiss.
struct KindFilterSheet: View {
  @Environment(\.localized) private var localized
  @Binding var kind: String?
  let kinds: [String]
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        Section {
          Picker(selection: $kind) {
            Text(Message("filter.allKinds"), localized).tag(String?.none)
            ForEach(kinds, id: \.self) { kind in
              // Through `poolKindLabel`, not `.capitalized`: the raw token is the WFS roster's
              // own word, and capitalising it put a domain token on screen.
              Text(poolKindLabel(kind), localized).tag(String?.some(kind))
            }
          } label: {
            Text(Message("filter.poolKinds"), localized)
          }
        } header: {
          Text(Message("filter.section.what"), localized)
        }
      }
      .navigationTitle(Text(Message("mobile.filters"), localized))
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button {
            dismiss()
          } label: {
            Text(Message("action.done"), localized)
          }
        }
      }
    }
    .presentationDetents([.medium, .large])
  }
}

struct PoolBrowserRow: View {
  @Environment(\.localized) private var localized
  let pool: PoolRecord

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      // A pool's NAME is a proper noun and is never translated.
      Text(verbatim: pool.name).font(.rowTitle).fixedSize(horizontal: false, vertical: true)
      Text(poolKindLabel(pool.kind), localized).font(.rowFact).foregroundStyle(.secondary)
      // The freshness state, in words — never a schedule this screen has not asked for, and
      // never "closed", which is what a blank line would be read as.
      Text(freshnessLabel(pool.freshness), localized)
        .font(.rowNote).foregroundStyle(.secondary)
    }
    .padding(.vertical, Design.Space.hair)
    .accessibilityElement(children: .combine)
  }
}

/// The sheet, loaded when it is opened rather than with the list.
///
/// One pool's detail is six reads; doing them for 57 pools to fill a list nobody has tapped
/// would spend the memory budget the list model has already half spent.
struct FacilitySheetLoader: View {
  let poolID: String
  let day: String
  let person: Person
  /// The answer's row for this pool, when the screen was reached from an answer. Nil from the
  /// all-pools browser: the roster has no verdict, and inventing one there is the whole class
  /// of bug this app keeps finding. See `PoolHeader`.
  let row: PoolRow?
  /// Where the pool is, from the roster — the detail payload carries an address and no
  /// coordinates.
  let point: GeoPoint?
  let isToday: Bool
  let load: (String) async -> FacilityDetail?
  let live: (String?) async -> LiveTemp

  @Environment(\.scenePhase) private var scenePhase

  @State private var detail: FacilityDetail?
  /// The live reading, or the honest reason there is none. It starts nil — meaning "not asked
  /// yet" — and the sheet omits the row entirely until the answer arrives, because a row that
  /// said "unavailable" for the first 300 ms and then a temperature would be two claims.
  @State private var reading: LiveTemp?
  /// The instant the reading's AGE is stated as of. It is `@State` rather than `Date()` at the
  /// point of use because that is the difference between "measured 3 min ago" being true when
  /// the sheet opened and being true now: SwiftUI re-evaluates a body when its state changes,
  /// not when the clock moves, so a sheet left open would go on printing the age it had at
  /// load. Moving this is what makes the sentence re-render.
  @State private var asOf = Date()

  var body: some View {
    content
      .task {
        let detail = await load(poolID)
        self.detail = detail
        // ONE fetch, after the sheet has something to show. It cannot fail visibly: every
        // failure inside `LiveClient` is already an `.unavailable` state with its own sentence.
        await reask()
        // ...and then once a minute for as long as the sheet is on screen, because the age it
        // prints is a fact about the clock. Structured concurrency cancels this when the view
        // goes away, and most iterations are served from `LiveClient`'s cache, so the cost is
        // one re-worded sentence per minute rather than a request.
        while !Task.isCancelled {
          try? await Task.sleep(for: .seconds(LiveClient.reaskInterval))
          guard !Task.isCancelled else { return }
          await reask()
        }
      }
      // Time passes while the app is in the background too, and `Task.sleep` is not a promise
      // about wall-clock. Coming back to the foreground is the one moment a stale age is
      // certain, so it is re-asked there as well.
      .onChange(of: scenePhase) { _, phase in
        guard phase == .active else { return }
        Task { await reask() }
      }
  }

  /// Ask again, and restate the age as of now.
  private func reask() async {
    reading = await live(detail?.baditickerPOIID)
    asOf = Date()
  }

  @ViewBuilder
  private var content: some View {
    if let detail {
      FacilitySheet(
        detail: detail, day: day, person: person, live: reading, asOf: asOf, row: row,
        point: point, isToday: isToday)
    } else {
      ProgressView()
    }
  }
}
