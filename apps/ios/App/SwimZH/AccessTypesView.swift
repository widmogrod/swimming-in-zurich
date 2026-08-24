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
  var body: some View {
    List {
      Section {
        ForEach(accessExplanations) { explanation in
          AccessTypeRow(explanation: explanation)
        }
      } footer: {
        Text(
          "A session's own rules always win: what a pool publishes for a particular hour is "
            + "what this app shows, and these are the categories it sorts them into.")
      }
    }
    .listStyle(.insetGrouped)
    .navigationTitle("Session types")
    .navigationBarTitleDisplayMode(.inline)
  }
}

struct AccessTypeRow: View {
  let explanation: AccessExplanation

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      swatch
      VStack(alignment: .leading, spacing: 2) {
        Text(explanation.label).font(.subheadline.weight(.semibold))
        Text(explanation.description)
          .font(.footnote)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      }
    }
    .padding(.vertical, 2)
    .accessibilityElement(children: .combine)
  }

  /// The ribbon's own colour for this family — the legend's whole purpose. Hidden from
  /// VoiceOver: the label beside it already says what it means, and "teal rectangle" does not.
  private var swatch: some View {
    RoundedRectangle(cornerRadius: 3)
      .fill(familyColor(accessFamily(explanation.className)))
      .frame(width: 14, height: 14)
      .padding(.top, 3)
      .accessibilityHidden(true)
  }
}
