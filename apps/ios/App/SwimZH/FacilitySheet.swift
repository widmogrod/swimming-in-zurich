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
  let detail: FacilityDetail
  let day: String
  let person: Person

  var body: some View {
    List {
      ForEach(sections) { section in
        Section(section.title) {
          ForEach(section.rows) { row in
            DetailRowView(row: row)
          }
        }
      }
    }
    .listStyle(.insetGrouped)
    // The sheet's rendered identity is the pool's NAME, never its id — which is why
    // `FacilityDetailOut.facility_id` stays deliberately omitted from `renderedFields`.
    .navigationTitle(detail.name)
    .navigationBarTitleDisplayMode(.inline)
  }

  private var sections: [DetailSection] {
    detailSections(detail, on: day, for: person)
  }
}

/// One line of the sheet. ONE view per `ForEach` element (the laziness rule), so everything a
/// row can grow into — its caveat, its link — lives inside a single `VStack`.
struct DetailRowView: View {
  let row: DetailRow

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      value
      caveat
    }
    .accessibilityElement(children: .combine)
  }

  @ViewBuilder
  private var value: some View {
    if let url = URL(string: row.value), row.value.hasPrefix("http") {
      Link(destination: url) {
        LabeledContent(row.label) { Text(row.value).lineLimit(1).truncationMode(.middle) }
      }
    } else if row.id == "phone" {
      // `tel:` is the one URL an offline app can still act on usefully.
      Link(destination: URL(string: "tel:\(row.value.filter { !$0.isWhitespace })")!) {
        LabeledContent(row.label) { Text(row.value) }
      }
    } else {
      LabeledContent(row.label) {
        Text(row.value).multilineTextAlignment(.trailing)
      }
    }
  }

  /// The honesty line: why this fact is weaker than it looks. Never truncated — a caveat that
  /// runs off the edge of the row is a caveat nobody reads.
  @ViewBuilder
  private var caveat: some View {
    if let caveat = row.caveat {
      Text(caveat)
        .font(.caption2)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }
  }
}
