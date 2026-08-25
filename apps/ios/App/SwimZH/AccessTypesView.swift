// AccessTypesView.swift — what the session labels mean.
//
// The web serves this from `/access-types`; the phone has no network, so the legend ships in
// `SwimZHKit` and is held to the domain's own words by a generated fixture
// (`AccessExplainerTests`). This file only lays it out.
//
// Each row carries its family colour as a swatch, so the legend doubles as the ribbon's key —
// which is what makes the ribbon's colours readable at all. Colour is never the only channel:
// the label says the same thing in words, which is what
// `accessibilityDifferentiateWithoutColor` needs to be true by construction.

import SwiftUI
import SwimZHKit

struct AccessTypesView: View {
  @Environment(\.localized) private var localized

  var body: some View {
    List {
      Section {
        ForEach(accessExplanations) { explanation in
          AccessTypeRow(explanation: explanation)
        }
      } footer: {
        Text(Message("accessTypes.footer"), localized)
      }
    }
    .listStyle(.insetGrouped)
    .navigationTitle(Text(Message("accessTypes.title"), localized))
    .navigationBarTitleDisplayMode(.inline)
  }
}

struct AccessTypeRow: View {
  @Environment(\.localized) private var localized
  let explanation: AccessExplanation

  var body: some View {
    HStack(alignment: .top, spacing: Design.Space.row) {
      swatch
      VStack(alignment: .leading, spacing: Design.Space.hair) {
        Text(explanation.label, localized).font(.noticeTitle)
        Text(explanation.description, localized)
          .font(.noticeBody)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      }
    }
    .padding(.vertical, Design.Space.hair)
    .accessibilityElement(children: .combine)
  }

  /// The ribbon's own colour for this family — the legend's whole purpose. Hidden from
  /// VoiceOver: the label beside it already says what it means, and "teal rectangle" does not.
  private var swatch: some View {
    RoundedRectangle(cornerRadius: Design.Radius.swatch)
      .fill(familyColor(accessFamily(explanation.className)))
      .frame(width: 14, height: 14)
      .padding(.top, Design.Space.hair)
      .accessibilityHidden(true)
  }
}
