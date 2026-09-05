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
//
// And one iOS 27 experiment, behind `Lab.stripStyle` — a PICKER of three glass behaviours
// plus the flat look, because what a tap FEELS like is the thing under review and a reader
// cannot feel it from a description (`Lab.StripStyle` says what each one changes):
//  * `morph`: the selected tint is a separate glass view carrying one `glassEffectID`, so it
//    flies from chip to chip inside the `GlassEffectContainer`. The chip's own glass is swapped
//    off under it, which is where the tap animation goes wrong.
//  * `tint`: one interactive glass per chip, always; selection is a tint cross-fade. The press
//    lens works because the glass under the finger is never removed.
//  * `button`: the system `GlassButtonStyle`, so the press feel is exactly the bars'.
// The border and the today rule stay in every variant: colour is never the only channel.

import SwiftUI
import SwimZHKit

struct DayStrip: View {
  @Environment(\.localized) private var localized
  let chips: [DayChip]
  @Binding var selection: String

  @Environment(\.dynamicTypeSize) private var dynamicTypeSize
  /// Starts ON the selected day. The strip's chips begin at the store's first day, and the
  /// selection is today — which, on a store a week or two old, is a dozen chips to the right.
  /// The first screenshot of the glass strip showed no selected chip at all, because it was
  /// off-screen: the position was only ever scrolled on a CHANGE of selection.
  @State private var position: ScrollPosition
  /// Set by a chip's tap and cleared by the change it causes. A TAPPED chip is on screen by
  /// definition, and centring it anyway made the whole strip lurch under the finger — the
  /// reader's own tap moved the date away from where they pressed. So only a selection that
  /// came from ELSEWHERE (the model picking a covered day) scrolls the strip; a tap never does.
  /// Scrolling is the reader's, tapping is not allowed to scroll for them.
  @State private var selectionCameFromTap = false

  init(chips: [DayChip], selection: Binding<String>) {
    self.chips = chips
    self._selection = selection
    self._position = State(
      initialValue: ScrollPosition(id: selection.wrappedValue, anchor: .center))
  }
  @AppStorage(Lab.stripStyle) private var stripStyle = Lab.StripStyle.default
  /// The namespace the morphing selection lives in. One id, `selectionGlassID`, ever in it.
  @Namespace private var glassNamespace
  private let selectionGlassID = "selection"

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
    // Declared here rather than started in the chip's action: the morph needs the selection
    // change to be one animated transaction, and this is what makes it one. Nil when the
    // switch is off, so the flat variant changes exactly as it did before.
    .animation(stripStyle.isGlass ? .snappy(duration: 0.3) : nil, value: selection)
    .onChange(of: selection) { _, day in
      if selectionCameFromTap {
        selectionCameFromTap = false
      } else {
        position.scrollTo(id: day, anchor: .center)
      }
    }
    // ...and when the chips ARRIVE. The strip can be built before the model has its chips, in
    // which case the initial position names an id nothing has laid out yet and is dropped.
    .onChange(of: chips.count, initial: true) { _, _ in
      position.scrollTo(id: selection, anchor: .center)
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
      chipRow(layout)
        .scrollTargetLayout()
        .padding(.horizontal)
    }
    .scrollIndicators(.hidden)
    .scrollTargetBehavior(.viewAligned)
    .scrollPosition($position)
    .scrollEdgeEffectHidden(for: .horizontal)
    // The press lens of interactive glass SWELLS the chip past its frame, and a scroll view
    // clips to its bounds — so the swollen chip was cut off along the strip's bottom edge.
    // Nothing else in the strip overflows, so the clip protected nothing.
    .scrollClipDisabled()
  }

  /// The chips, in a `GlassEffectContainer` when they are glass — adjacent glass shapes are
  /// blended by the container, and the morph only happens inside one.
  @ViewBuilder
  private func chipRow(_ layout: StripLayout) -> some View {
    if stripStyle.isGlass {
      GlassEffectContainer(spacing: Design.Space.row) {
        chipStack(layout)
      }
    } else {
      chipStack(layout)
    }
  }

  private func chipStack(_ layout: StripLayout) -> some View {
    LazyHStack(spacing: Design.Space.row) {
      ForEach(chips) { chip in
        chipButton(chip, layout: layout)
      }
    }
  }

  private func chipButton(_ chip: DayChip, layout: StripLayout) -> some View {
    Button {
      selectionCameFromTap = true
      selection = chip.day
    } label: {
      chipLabel(chip, layout: layout)
    }
    // The whole chip is the target, gaps included — without this only the glyphs are tappable
    // and the 44 pt rule is satisfied on paper only.
    .contentShape(Rectangle())
    .modifier(ChipButtonStyle(style: stripStyle, isSelected: chip.day == selection))
    .accessibilityLabel(Text(verbatim: chip.accessibilityLabel))
    .accessibilityAddTraits(chip.day == selection ? [.isSelected, .isButton] : .isButton)
  }

  /// The glass the `tint` and `button` variants give a chip: the same interactive glass on
  /// every chip, tinted on the selected one. Only the tint changes on a tap, so the glass
  /// under the finger is never removed — which is what lets the press lens show.
  private static func chipGlass(isSelected: Bool) -> Glass {
    isSelected
      ? .regular.tint(ChipColor.selected.opacity(ChipColor.selectedFill)).interactive()
      : .regular.interactive()
  }

  /// How the BUTTON is styled, per variant. `flat` and `morph` paint their surface inside the
  /// label (`ChipSurface`) and keep the plain style; `tint` puts the glass on the button itself,
  /// outside the label, so the border and today rule drawn in the label sit on top of it;
  /// `button` hands the whole surface to the system style.
  private struct ChipButtonStyle: ViewModifier {
    let style: Lab.StripStyle
    let isSelected: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
      switch style {
      case .flat, .morph:
        content.buttonStyle(.plain)
      case .tint:
        content
          .buttonStyle(.plain)
          .glassEffect(
            DayStrip.chipGlass(isSelected: isSelected),
            in: .rect(cornerRadius: Design.Radius.control))
      case .button:
        content
          .buttonStyle(.glass(DayStrip.chipGlass(isSelected: isSelected)))
          .buttonBorderShape(.roundedRectangle(radius: Design.Radius.control))
      }
    }
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
    // The border and the today rule are CONTENT, applied before the surface: a glass surface
    // composites over anything overlaid after it, and the first glass screenshot showed a
    // selected chip with no border and a today chip with no rule — the two second channels a
    // reader who cannot tell the tints apart depends on. Inside the content they draw on top
    // of the glass, and the flat variant does not care about the order.
    .overlay(chipBorder(chip))
    .overlay(alignment: .bottom) { todayMarker(chip) }
    .modifier(
      ChipSurface(chip: chip, selection: selection, style: stripStyle) { selectionGlass }
    )
  }

  /// The selection, as glass. It exists ONLY behind the selected chip, so moving the selection
  /// removes it from one chip and inserts it under another in the same transaction — the two
  /// events a shared `glassEffectID` morphs between. The tint is the same one the flat variant
  /// paints, so the two looks agree on which colour means "chosen".
  private var selectionGlass: some View {
    Color.clear
      .glassEffect(
        .regular.tint(ChipColor.selected.opacity(ChipColor.selectedFill)).interactive(),
        in: .rect(cornerRadius: Design.Radius.control)
      )
      .glassEffectID(selectionGlassID, in: glassNamespace)
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

  /// The chip's surface, in either variant.
  ///
  /// FLAT: a TINTED background rather than a filled one, so the label keeps `.primary` and its
  /// contrast is the system's problem in both appearances. A saturated fill would force a
  /// hardcoded light-on-dark label colour, which is the literal the lint bans.
  ///
  /// MORPH: an idle chip is plain interactive glass; the selected chip carries no glass of its
  /// own (`.identity`) and instead sits on the one tinted `selectionGlass` — one glass layer per
  /// chip, so glass never samples glass, and the layer that moves is the one with the id.
  ///
  /// TINT and BUTTON: nothing here. Their surface is on the button (`ChipButtonStyle`).
  private struct ChipSurface<Selection: View>: ViewModifier {
    let chip: DayChip
    let selection: String
    let style: Lab.StripStyle
    @ViewBuilder let selectionGlass: () -> Selection

    private var isSelected: Bool { chip.day == selection }

    @ViewBuilder
    func body(content: Content) -> some View {
      switch style {
      case .tint, .button:
        content
      case .morph:
        content
          .glassEffect(
            isSelected ? .identity : .regular.interactive(),
            in: .rect(cornerRadius: Design.Radius.control)
          )
          .background {
            if isSelected {
              selectionGlass()
            }
          }
      case .flat:
        content.background(flatFill, in: .rect(cornerRadius: Design.Radius.control))
      }
    }

    private var flatFill: Color {
      isSelected
        ? ChipColor.selected.opacity(ChipColor.selectedFill)
        : ChipColor.idle.opacity(ChipColor.idleFill)
    }
  }

  /// Selection is carried by a border as well as a tint — a second channel, for a reader who
  /// cannot separate the two accents. It stays in the glass variant for the same reason.
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
