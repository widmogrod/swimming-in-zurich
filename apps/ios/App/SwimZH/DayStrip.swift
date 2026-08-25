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
  @Environment(\.localized) private var localized
  let chips: [DayChip]
  @Binding var selection: String

  @Environment(\.dynamicTypeSize) private var dynamicTypeSize
  @State private var position = ScrollPosition(idType: String.self)

  private var typeSize: TypeSize { TypeSize(dynamicTypeSize) }

  /// Height does not depend on width, so it can be read before the strip is measured — which
  /// is what lets the `GeometryReader` below have a height at all.
  private var height: Double { stripLayout(for: typeSize, width: 0).stripHeight }

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.tight) {
      legend
      GeometryReader { proxy in
        strip(stripLayout(for: typeSize, width: proxy.size.width))
      }
      .frame(height: height)
    }
    .accessibilityIdentifier("dayStrip")
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
      // The formatter's own words for the date — read off its `DateFieldAttribute` runs by
      // `Format.dayParts`, never split out of a rendered string.
      Text(verbatim: chip.accessibilityLabel)
        .font(.stripLegend)
        .padding(.horizontal)
    }
  }

  private func strip(_ layout: StripLayout) -> some View {
    ScrollView(.horizontal) {
      LazyHStack(spacing: Design.Space.row) {
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
    .accessibilityLabel(Text(verbatim: chip.accessibilityLabel))
    .accessibilityAddTraits(chip.day == selection ? [.isSelected, .isButton] : .isButton)
  }

  private func chipLabel(_ chip: DayChip, layout: StripLayout) -> some View {
    VStack(spacing: Design.Space.hair) {
      // At an accessibility size the caption is dropped rather than shrunk: the legend above
      // carries it, and squeezing three glyphs into a chip is the failure this rule exists to
      // avoid.
      captionText(chip, layout: layout)
        .font(.chipCaption)
        .foregroundStyle(.secondary)
        .lineLimit(1)
      Text(verbatim: chip.number)
        .font(.chipNumber)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }
    .frame(width: layout.chipWidth, height: layout.stripHeight)
    .background(chipBackground(chip), in: .rect(cornerRadius: Design.Radius.control))
    .overlay(chipBorder(chip))
    .overlay(alignment: .bottom) { todayMarker(chip) }
  }

  /// The chip's caption: the today WORD (ours) or the weekday (the formatter's).
  ///
  /// At an accessibility size it is dropped rather than shrunk — an empty `Text` keeps the
  /// chip's two-line rhythm without squeezing three glyphs into it, and the legend above
  /// carries the date instead.
  @ViewBuilder
  private func captionText(_ chip: DayChip, layout: StripLayout) -> some View {
    if layout.labelsCollapsed {
      Text(verbatim: "")
    } else {
      Text(chip.caption, localized)
    }
  }

  /// A TINTED background rather than a filled one, so the label keeps `.primary` and its
  /// contrast is the system's problem in both appearances. A saturated fill would force a
  /// hardcoded light-on-dark label colour, which is the literal the lint bans.
  private func chipBackground(_ chip: DayChip) -> Color {
    chip.day == selection
      ? ChipColor.selected.opacity(ChipColor.selectedFill)
      : ChipColor.idle.opacity(ChipColor.idleFill)
  }

  /// Selection is carried by a border as well as a tint — a second channel, for a reader who
  /// cannot separate the two accents.
  @ViewBuilder
  private func chipBorder(_ chip: DayChip) -> some View {
    if chip.day == selection {
      RoundedRectangle(cornerRadius: Design.Radius.control)
        .strokeBorder(ChipColor.selected, lineWidth: 2)
    }
  }

  /// Today is marked by a rule under the chip as well as by its caption: selection and today
  /// are independent, and a colour alone would make them indistinguishable to a reader who
  /// cannot tell the two accents apart.
  @ViewBuilder
  private func todayMarker(_ chip: DayChip) -> some View {
    if chip.isToday {
      Capsule()
        .fill(ChipColor.today)
        .frame(width: 18, height: 3)
        .padding(.bottom, Design.Space.tight)
    }
  }
}
