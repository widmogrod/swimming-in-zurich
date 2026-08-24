// DayStrip.swift — the horizontal day picker.
//
// Everything this view decides is read from `SwimZHKit`: `stripLayout(for:width:)` says how
// many chips fit, how wide they are, how tall the strip is and whether the inline captions
// collapse to a legend; `dayChip(for:today:)` says what each one reads. The view lays them out.
//
// Three iOS-26 adoptions, each for a stated reason:
//  * `ScrollPosition` + `.scrollTargetBehavior(.viewAligned)` rather than `ScrollViewReader`,
//    because the position is BIDIRECTIONAL: the strip must scroll the selection into view when
//    the day changes from elsewhere, and report the centred chip back.
//  * `.scrollEdgeEffectHidden(for: .horizontal)` — Apple: "Scroll edge effects aren't
//    decorative". They mark where content passes under a bar; nothing passes under this strip.
//  * `.sensoryFeedback(.selection, trigger:)` on the selected day, so a chip change feels like
//    a picker rather than a tap on glass.

import SwiftUI
import SwimZHKit

struct DayStrip: View {
  let chips: [DayChip]
  @Binding var selection: String

  @Environment(\.dynamicTypeSize) private var dynamicTypeSize
  @State private var position = ScrollPosition(idType: String.self)

  private var typeSize: TypeSize { TypeSize(dynamicTypeSize) }

  /// Height does not depend on width, so it can be read before the strip is measured — which
  /// is what lets the `GeometryReader` below have a height at all.
  private var height: Double { stripLayout(for: typeSize, width: 0).stripHeight }

  var body: some View {
    VStack(alignment: .leading, spacing: 4) {
      legend
      GeometryReader { proxy in
        strip(stripLayout(for: typeSize, width: proxy.size.width))
      }
      .frame(height: height)
    }
    .sensoryFeedback(.selection, trigger: selection)
    .onChange(of: selection) { _, day in
      position.scrollTo(id: day, anchor: .center)
    }
  }

  /// Shown only when the accessibility layout has collapsed the inline captions — the date has
  /// to be readable SOMEWHERE, and a chip that fits one large numeral cannot carry it.
  @ViewBuilder
  private var legend: some View {
    let layout = stripLayout(for: typeSize, width: 0)
    if layout.labelsCollapsed, let chip = chips.first(where: { $0.day == selection }) {
      Text(chip.accessibilityLabel)
        .font(.subheadline.weight(.semibold))
        .padding(.horizontal)
    }
  }

  private func strip(_ layout: StripLayout) -> some View {
    ScrollView(.horizontal) {
      LazyHStack(spacing: 8) {
        ForEach(chips) { chip in
          chipButton(chip, layout: layout)
        }
      }
      .scrollTargetLayout()
      .padding(.horizontal)
    }
    .scrollIndicators(.hidden)
    .scrollTargetBehavior(.viewAligned)
    .scrollPosition($position)
    .scrollEdgeEffectHidden(for: .horizontal)
  }

  private func chipButton(_ chip: DayChip, layout: StripLayout) -> some View {
    Button {
      selection = chip.day
    } label: {
      chipLabel(chip, layout: layout)
    }
    .buttonStyle(.plain)
    // The whole chip is the target, gaps included — without this only the glyphs are tappable
    // and the 44 pt rule is satisfied on paper only.
    .contentShape(Rectangle())
    .accessibilityLabel(chip.accessibilityLabel)
    .accessibilityAddTraits(chip.day == selection ? [.isSelected, .isButton] : .isButton)
  }

  private func chipLabel(_ chip: DayChip, layout: StripLayout) -> some View {
    VStack(spacing: 2) {
      // At an accessibility size the caption is dropped rather than shrunk: the legend above
      // carries it, and squeezing three glyphs into a chip is the failure this rule exists to
      // avoid.
      Text(layout.labelsCollapsed ? "" : chip.caption)
        .font(.caption2)
        .foregroundStyle(.secondary)
        .lineLimit(1)
      Text(chip.number)
        .font(.headline)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }
    .frame(width: layout.chipWidth, height: layout.stripHeight)
    .background(chipBackground(chip), in: .rect(cornerRadius: 12))
    .overlay(chipBorder(chip))
    .overlay(alignment: .bottom) { todayMarker(chip) }
  }

  /// A TINTED background rather than a filled one, so the label keeps `.primary` and its
  /// contrast is the system's problem in both appearances. A saturated fill would force a
  /// hardcoded light-on-dark label colour, which is the literal the lint bans.
  private func chipBackground(_ chip: DayChip) -> Color {
    chip.day == selection ? Color("ChipSelected").opacity(0.22) : Color("TierPast").opacity(0.12)
  }

  /// Selection is carried by a border as well as a tint — a second channel, for a reader who
  /// cannot separate the two accents.
  @ViewBuilder
  private func chipBorder(_ chip: DayChip) -> some View {
    if chip.day == selection {
      RoundedRectangle(cornerRadius: 12).strokeBorder(Color("ChipSelected"), lineWidth: 2)
    }
  }

  /// Today is marked by a rule under the chip as well as by its caption: selection and today
  /// are independent, and a colour alone would make them indistinguishable to a reader who
  /// cannot tell the two accents apart.
  @ViewBuilder
  private func todayMarker(_ chip: DayChip) -> some View {
    if chip.isToday {
      Capsule()
        .fill(Color("ChipToday"))
        .frame(width: 18, height: 3)
        .padding(.bottom, 4)
    }
  }
}
