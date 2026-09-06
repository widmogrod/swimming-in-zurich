// PoolGlance.swift — the three numbers under the pool's name.
//
// "Water temperature, number of lanes and lane length — at a glance." The facts were there,
// as rows in the "Basins" section of the list, below the address, the phone and the website —
// which the header's buttons already act on. So a reader opened a pool and scrolled past three
// things they could already tap to reach the three numbers they had opened it for.
//
// WHICH numbers, from WHICH basin, and what a stale live reading is called, are
// `SwimZHKit.glanceFacts` — rules with a test. This file only draws the strip, in one of the
// two shapes `Lab.Glance` compares (`tiles` and `line`), or not at all (`none`). Nothing here
// is glass: the strip sits INSIDE the panel's content, and the HIG's rule against glass in the
// content layer is the one `UILintTests` enforces.

import SwiftUI
import SwimZHKit

struct PoolGlance: View {
  @Environment(\.localized) private var localized
  @AppStorage(Lab.glance) private var style = Lab.Glance.default
  let facts: [GlanceFact]

  var body: some View {
    if !facts.isEmpty {
      switch style {
      case .tiles: tiles
      case .line: line
      case .none: EmptyView()
      }
    }
  }

  /// Three small cards: a glyph, the number, and under it the caption that names the number
  /// and — for a temperature — says how much to trust it.
  private var tiles: some View {
    HStack(spacing: Design.Space.row) {
      ForEach(facts) { fact in
        VStack(alignment: .leading, spacing: Design.Space.hair) {
          HStack(spacing: Design.Space.tight) {
            Image(systemName: fact.symbol)
              .font(.glanceCaption)
              .foregroundStyle(.tint)
            Text(fact.value, localized)
              .font(.glanceValue)
              .monospacedDigit()
              .foregroundStyle(fact.muted ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
          }
          Text(fact.caption, localized)
            .font(.glanceCaption)
            .foregroundStyle(.secondary)
            .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Design.Space.row + Design.Space.tight)
        .padding(.vertical, Design.Space.row)
        .background(.fill.tertiary, in: RoundedRectangle(cornerRadius: Design.Radius.control))
        .accessibilityElement(children: .combine)
      }
    }
    .padding(.top, Design.Space.tight)
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("poolGlance")
  }

  /// One quiet line: glyph and phrase, glyph and phrase, a dot between — the second subtitle
  /// a Maps place card carries.
  private var line: some View {
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
  }
}
