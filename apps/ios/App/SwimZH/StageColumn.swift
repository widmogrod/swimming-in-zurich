// StageColumn.swift — the list, floating over the map in the STAGE wide layout.
//
// In a wide window under `Lab.WideLayout.stage`, the map is the whole screen and the list
// rides over it in this card: the same answer, the same rows, the same day strip, with the map
// live behind it at every moment. A tapped pool's facts replace the list INSIDE the card
// (`PoolPresentation.column`) while the map flies to the pool — Apple Maps on iPad.
//
// THE CARD MOVES, by the handle at its top. Dragged DOWN it shrinks to one of three rests
// (`ColumnDetent`: the whole height, half, or just the search field and the day strip) and
// gives the map the height back; dragged UP it grows again. Flicked ACROSS the screen it goes
// to the other side (`ColumnSide`), for a left hand, a right hand, or a pool that happens to be
// under it — and the map's framing follows (`TodayView` insets the map by the side). The rules
// — how far it follows a finger, which rest or side a lifted finger lands it on — are the
// kit's, tested; this file reads them. The HANDLE is the drag area, not the whole card: the
// list inside must go on scrolling, and a drag on it is a scroll.
//
// HOW IT MOVES. The card is anchored to the BOTTOM of the window and its content is laid out
// ONCE at the full height; the card is a window onto it from the top, so a shorter card shows
// the list's head — controls first — and nothing inside re-measures during a drag. The same
// construction as the phone's `PoolPanel`, for the same reason.
//
// GLASS, and why this file may paint it. The card floats OVER a map, the case `PoolPanel` and
// the map's pin card already make and the HIG names ("floating info card over a map"); its rows
// are opaque grouped cells, so the glass carries only the card's own margins and the strip's
// ground. TWO grounds have to be cleared for that to be true, and the first cut cleared one: the
// list's own grouped background (`scrollContentBackground`), AND the `NavigationStack`'s — a
// stack paints `systemBackground` under everything it hosts, which turned the whole card into
// an opaque white sheet with glass corners. `containerBackground(.clear, for: .navigation)` is
// the second, and it is applied HERE, around the stack, so a pushed pool's facts are on the
// same glass as the list they replaced.

import SwiftUI
import SwimZHKit

struct StageColumn<Content: View>: View {
  /// The window's width, from which the column's is derived.
  let windowWidth: Double
  /// Which edge the card sits against. Owned by the caller, which insets the map to match.
  @Binding var side: ColumnSide
  @ViewBuilder let content: () -> Content

  /// Which of the three heights the card rests at. It starts tall: the list is the point.
  @State private var detent: ColumnDetent = .tall
  /// The finger's travel during a drag of the handle. Zero at rest.
  @State private var drag: CGSize = .zero

  private var columnWidth: Double { listColumnWidth(in: windowWidth) }

  var body: some View {
    GeometryReader { geo in
      let total = geo.size.height
      let visible = columnVisibleHeight(
        resting: detent.height(in: total), drag: drag.height, in: total)
      VStack(spacing: 0) {
        handle(in: total)
        content()
          .scrollContentBackground(.hidden)
          .containerBackground(.clear, for: .navigation)
      }
      // The content is laid out ONCE, at the full height; the card is the window onto it.
      .frame(width: columnWidth, height: total, alignment: .top)
      .frame(height: visible, alignment: .top)
      .clipShape(.rect(cornerRadius: Design.Radius.panel))
      .glassEffect(.regular, in: .rect(cornerRadius: Design.Radius.panel))
      .offset(x: drag.width)
      .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: anchor)
      .accessibilityElement(children: .contain)
      .accessibilityIdentifier("stageColumn")
    }
    .padding(Design.Space.gutter)
  }

  /// Bottom-anchored, on whichever side the card is.
  private var anchor: Alignment {
    side == .leading ? .bottomLeading : .bottomTrailing
  }

  /// The grab handle, and the one place a drag moves the card. The capsule is the glyph every
  /// phone user reads as "drag me"; the strip around it is the drag area — thin, because the
  /// controls sit right under it and a full hit-target of empty glass above them read as a gap.
  private func handle(in total: Double) -> some View {
    Capsule()
      .fill(.secondary)
      .frame(width: 36, height: 5)
      .frame(maxWidth: .infinity, minHeight: handleHeight)
      .contentShape(Rectangle())
      .gesture(dragging(in: total))
      .accessibilityHidden(true)
  }

  /// Follow the finger both ways; on release, the dominant direction decides: a mostly vertical
  /// drag lands on a rest, a mostly horizontal one lands on a side. Projected travel, so a
  /// flick counts for where it was going.
  private func dragging(in total: Double) -> some Gesture {
    DragGesture(minimumDistance: 10, coordinateSpace: .global)
      .onChanged { value in
        drag = value.translation
      }
      .onEnded { value in
        let projected = value.predictedEndTranslation
        withAnimation(panelSpring) {
          if abs(projected.width) > abs(projected.height) {
            side = columnSide(
              from: side, projectedDrag: projected.width, columnWidth: columnWidth,
              margin: Design.Space.gutter, in: windowWidth)
          } else {
            detent = columnDetent(from: detent, projectedDrag: projected.height, in: total)
          }
          drag = .zero
        }
      }
  }
}

/// The grab strip's height: the phone drawer's own (`Design.Space.row` above, `tight` below the
/// capsule), which is what a thumb already knows how to find.
let handleHeight: Double = Design.Space.row + 5 + Design.Space.tight + Design.Space.row

/// How the pool screen is shown: as a stage of its own (the phone's map with the facts in a
/// drawer), or as a column of facts inside a card that already floats over a map.
enum PoolPresentation: Equatable {
  case stage, column
}

extension EnvironmentValues {
  /// Set by `StageColumn`'s host on the column's stack, read by `FacilitySheet`.
  @Entry var poolPresentation: PoolPresentation = .stage
}
