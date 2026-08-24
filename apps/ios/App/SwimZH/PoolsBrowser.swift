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

import SwiftUI
import SwimZHKit

struct PoolsBrowser: View {
  @Environment(\.localized) private var localized
  let pools: [PoolRecord]
  let day: String
  let person: Person
  let load: (String) async -> FacilityDetail?
  /// The live water temperature for a pool's Baditicker key — passed down rather than reached
  /// for, so the browser and the find screen share the one client (and so its 2-minute cache is
  /// shared too).
  let live: (String?) async -> LiveTemp

  @State private var kind: String?
  @State private var search = ""

  var body: some View {
    List {
      ForEach(shown) { pool in
        NavigationLink {
          FacilitySheetLoader(
            poolID: pool.id, day: day, person: person, load: load, live: live)
        } label: {
          PoolBrowserRow(pool: pool)
        }
      }
    }
    .listStyle(.insetGrouped)
    .navigationTitle(Text(Message("nav.allPools"), localized))
    .searchable(
      text: $search, placement: .navigationBarDrawer(displayMode: .always),
      prompt: Text(Message("nav.findAPool"), localized)
    )
    .toolbar { kindMenu }
    .overlay { emptyState }
  }

  // Both rules live in `SwimZHKit`, where a test drives them: the search predicate is the
  // SAME one the find screen uses, and the kind list comes from the roster rather than from a
  // day's answer.
  private var kinds: [String] { poolKinds(pools) }

  private var shown: [PoolRecord] { browsePools(pools, kind: kind, search: search) }

  private var kindMenu: some ToolbarContent {
    ToolbarItem(placement: .topBarTrailing) {
      Menu {
        Picker(selection: $kind) {
          Text(Message("browser.allKinds"), localized).tag(String?.none)
          ForEach(kinds, id: \.self) { kind in
            Text(poolKindLabel(kind), localized).tag(String?.some(kind))
          }
        } label: {
          Text(Message("browser.kind"), localized)
        }
      } label: {
        Label(
          Message("browser.filterByKind"),
          systemImage: "line.3.horizontal.decrease.circle", localized)
      }
    }
  }

  @ViewBuilder
  private var emptyState: some View {
    if shown.isEmpty {
      // The label/icon/description triple takes a `LocalizedStringKey` title, so a `Text` has
      // to go through the ViewBuilder form instead — the title is already localised and must
      // not be looked up a second time.
      ContentUnavailableView {
        Label {
          Text(Message("combo.noPoolsMatch"), localized)
        } icon: {
          Image(systemName: "magnifyingglass")
        }
      } description: {
        Text(Message("browser.noMatch.body"), localized)
      }
    }
  }
}

struct PoolBrowserRow: View {
  @Environment(\.localized) private var localized
  let pool: PoolRecord

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      // A pool's NAME is a proper noun and is never translated.
      Text(verbatim: pool.name).font(.headline).fixedSize(horizontal: false, vertical: true)
      Text(poolKindLabel(pool.kind), localized).font(.caption).foregroundStyle(.secondary)
      // The freshness state, in words — never a schedule this screen has not asked for, and
      // never "closed", which is what a blank line would be read as.
      Text(freshnessLabel(pool.freshness), localized)
        .font(.caption2).foregroundStyle(.secondary)
    }
    .padding(.vertical, 2)
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
      FacilitySheet(detail: detail, day: day, person: person, live: reading, asOf: asOf)
    } else {
      ProgressView()
    }
  }
}
