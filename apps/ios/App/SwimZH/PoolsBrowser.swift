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
  let pools: [PoolRecord]
  let day: String
  let person: Person
  let load: (String) async -> FacilityDetail?

  @State private var kind: String?
  @State private var search = ""

  var body: some View {
    List {
      ForEach(shown) { pool in
        NavigationLink {
          FacilitySheetLoader(poolID: pool.id, day: day, person: person, load: load)
        } label: {
          PoolBrowserRow(pool: pool)
        }
      }
    }
    .listStyle(.insetGrouped)
    .navigationTitle("All pools")
    .searchable(
      text: $search, placement: .navigationBarDrawer(displayMode: .always),
      prompt: "Find a pool"
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
        Picker("Kind", selection: $kind) {
          Text("All kinds").tag(String?.none)
          ForEach(kinds, id: \.self) { kind in
            Text(poolKindLabel(kind)).tag(String?.some(kind))
          }
        }
      } label: {
        Label("Filter by kind", systemImage: "line.3.horizontal.decrease.circle")
      }
    }
  }

  @ViewBuilder
  private var emptyState: some View {
    if shown.isEmpty {
      ContentUnavailableView(
        "No pools match", systemImage: "magnifyingglass",
        description: Text("Try a different name, or another kind."))
    }
  }
}

struct PoolBrowserRow: View {
  let pool: PoolRecord

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      Text(pool.name).font(.headline).fixedSize(horizontal: false, vertical: true)
      Text(poolKindLabel(pool.kind)).font(.caption).foregroundStyle(.secondary)
      // The freshness state, in words — never a schedule this screen has not asked for, and
      // never "closed", which is what a blank line would be read as.
      Text(freshnessLabel(pool.freshness)).font(.caption2).foregroundStyle(.secondary)
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

  @State private var detail: FacilityDetail?

  var body: some View {
    content
      .task { detail = await load(poolID) }
  }

  @ViewBuilder
  private var content: some View {
    if let detail {
      FacilitySheet(detail: detail, day: day, person: person)
    } else {
      ProgressView()
    }
  }
}
