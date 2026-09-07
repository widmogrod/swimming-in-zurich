// PoolGlance.swift — the three numbers under the pool's name.
//
// "Water temperature, number of lanes and lane length — at a glance." The facts were there,
// as rows in the "Basins" section of the list, below the address, the phone and the website —
// which the header's buttons already act on. So a reader opened a pool and scrolled past three
// things they could already tap to reach the three numbers they had opened it for.
//
// WHICH numbers, from WHICH basin, and what a stale live reading is called, are
// `SwimZHKit.glanceFacts` — rules with a test. This file only draws the strip: ONE quiet line
// under the kind and the verdict — "26 °C · 50 m · 6 lanes", with the glyphs — the second
// subtitle a Maps place card carries. Decided 2026-09-06 over three captioned tiles: the line
// costs almost no height in the drawer's smallest rest. What the tiles' captions said — that a
// temperature is the pool's statement, or a reading hours old — the line says to VoiceOver
// (each phrase is labelled by its caption) and shows by weight (a stale reading is muted).
// Nothing here is glass: the strip sits INSIDE the panel's content.

import SwiftUI
import SwimZHKit

struct PoolGlance: View {
  @Environment(\.localized) private var localized
  let facts: [GlanceFact]

  var body: some View {
    HStack(spacing: Design.Space.row) {
      if let first = facts.first {
        phrase(first)
      }
      // The first stands alone; every later one brings its own dot. No `if` inside the
      // `ForEach`, which is the laziness rule the lint reads for.
      ForEach(facts.dropFirst()) { fact in
        Circle()
          .fill(.tertiary)
          .frame(width: 3, height: 3)
          .accessibilityHidden(true)
        phrase(fact)
      }
    }
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("poolGlance")
  }

  private func phrase(_ fact: GlanceFact) -> some View {
    Label {
      Text(fact.phrase, localized)
        .monospacedDigit()
    } icon: {
      Image(systemName: fact.symbol)
    }
    .font(.heroSubtitle)
    .foregroundStyle(fact.muted ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
    .lineLimit(1)
    // "Water, earlier: 26 °C" — the caption names the number and says how far to trust it.
    .accessibilityLabel(Text(.joined([fact.caption, fact.phrase]), localized))
  }
}
