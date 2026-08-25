// FacilitySheet.swift — the facility detail screen.
//
// It renders `[DetailSection]` and decides NOTHING. Every sentence, every caveat and every
// omission was decided in `SwimZHKit.detailSections`, where a test drives it — which is what
// makes S3b acceptance 4's "these fields are rendered" a checkable claim rather than a
// declaration. `FieldCoverageTests.renderedRowsExistForEveryClaimedField` walks the whole
// roster out of the committed store and demands a row for every field named as rendered.
//
// The one thing this file decides is which rows are ACTIONABLE: a phone number dials, a website
// opens. Both are `Link`/`Button` rather than plain text because a tappable number beside an
// address is what a swimmer standing outside a locked door actually needs.

import SwiftUI
import SwimZHKit

struct FacilitySheet: View {
  @Environment(\.localized) private var localized
  let detail: FacilityDetail
  let day: String
  let person: Person
  /// The live water temperature, when it has been asked for. Nil means "not asked yet", not
  /// "unavailable" — the unavailable states are values of `LiveTemp` and each says its own
  /// reason. See `SwimZHKit.liveWaterRow`.
  let live: LiveTemp?
  /// The instant the live reading's age is stated as of. Threaded in rather than read here, so
  /// the sheet and its loader cannot disagree about what "now" is — and so a test can state it.
  let asOf: Date
  /// The answer's row for this pool, or nil when the screen was reached from the all-pools
  /// browser. See `PoolHeader`.
  let row: PoolRow?
  /// Where the pool is, from the roster. The detail payload carries an address but no
  /// coordinates, so this is threaded in rather than looked up here.
  let point: GeoPoint?
  let isToday: Bool

  var body: some View {
    List {
      // THE SCREEN NO LONGER OPENS ON A TABLE. See `PoolHeader` for what replaced it and why
      // every row below it survived the change.
      Section {
        PoolHeader(detail: detail, row: row, point: point, isToday: isToday)
          .listRowInsets(
            .init(
              top: Design.Space.row, leading: Design.Space.gutter,
              bottom: Design.Space.row, trailing: Design.Space.gutter)
          )
          .listRowBackground(Color.clear)
          .listRowSeparator(.hidden)
      }
      ForEach(sections) { section in
        Section {
          ForEach(section.rows) { row in
            DetailRowView(row: row)
          }
        } header: {
          // iOS 26 renders a section header exactly as written; it no longer upper-cases it.
          // The catalog entries are therefore sentence case in all five languages.
          Text(section.title, localized)
        }
      }
    }
    .listStyle(.insetGrouped)
    .listSectionSpacing(.compact)
    // The sheet's rendered identity is the pool's NAME, never its id — which is why
    // `FacilityDetailOut.facility_id` stays deliberately omitted from `renderedFields`.
    .navigationTitle(Text(verbatim: detail.name))
    .navigationBarTitleDisplayMode(.inline)
  }

  private var sections: [DetailSection] {
    detailSections(detail, on: day, for: person, in: localized, live: live, at: asOf)
  }
}

/// One line of the sheet. ONE view per `ForEach` element (the laziness rule), so everything a
/// row can grow into — its caveat, its link — lives inside a single `VStack`.
struct DetailRowView: View {
  @Environment(\.localized) private var localized
  let row: DetailRow

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      value
      caveat
    }
    .accessibilityElement(children: .combine)
  }

  /// The row's value, rendered ONCE and reused: a URL test and a `tel:` build both need the
  /// characters, and rendering it twice would be two chances to disagree.
  private var rendered: String { localized(row.value) }

  @ViewBuilder
  private var value: some View {
    if let url = URL(string: rendered), rendered.hasPrefix("http") {
      Link(destination: url) {
        LabeledContent {
          Text(verbatim: rendered).lineLimit(1).truncationMode(.middle)
        } label: {
          Text(row.label, localized)
        }
      }
    } else if row.id == "phone" {
      // `tel:` is the one URL an offline app can still act on usefully.
      Link(destination: URL(string: "tel:\(rendered.filter { !$0.isWhitespace })")!) {
        LabeledContent {
          Text(verbatim: rendered)
        } label: {
          Text(row.label, localized)
        }
      }
    } else {
      LabeledContent {
        Text(verbatim: rendered)
          .multilineTextAlignment(.trailing)
          // A weaker fact, shown as one. `row.muted` is set by ONE rule in the kit — a live
          // water reading that is hours old, or that the sensor has not taken — so a
          // nine-hour-old temperature does not read with the weight of a nine-minute-old one.
          // The words are unchanged either way; only the emphasis moves.
          .foregroundStyle(row.muted ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
      } label: {
        Text(row.label, localized)
      }
    }
  }

  /// The honesty line: why this fact is weaker than it looks. Never truncated — a caveat that
  /// runs off the edge of the row is a caveat nobody reads.
  @ViewBuilder
  private var caveat: some View {
    if let caveat = row.caveat {
      Text(caveat, localized)
        .font(.rowNote)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }
  }
}
