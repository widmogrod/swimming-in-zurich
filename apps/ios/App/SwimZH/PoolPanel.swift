// PoolPanel.swift — the facts drawer over the pool screen's map.
//
// A card that rises from the bottom of the map and rests at one of three heights
// (`Detent` on `DetentScale.panel`), dragged between them by the finger. It is PART OF THE SCREEN, not a
// presented sheet, and the driven app is why: presented as a `.sheet`, the facts lingered
// over the list for the length of their own dismissal after the back button had already
// popped the screen; went opaque (black, in dark mode) the moment they reached the top; and
// could not appear until the screen had a detail to present, so a pool opened on a spinner.
// A view in the hierarchy pops with its screen, looks the same at every height, and can stand
// on the map with the pool's name while the facts are still loading.
//
// TWO SLOTS. The `header` — the pool's name, its answer, its actions — is FIXED under the
// handle and never scrolls; the `facts` below it scroll, and only at the tallest rest. So a
// drag anywhere on the header, at any height, moves the drawer; a drag on the facts moves the
// drawer at the two smaller rests (their list is disabled) and scrolls the facts at the tallest.
// The header is what the smallest rest shows, which is why it is the part that never leaves.
//
// THE GESTURE, as the owner asked for it: pull the drawer down anywhere and it comes down to
// its smallest size first; pull on past that and let go, and the screen goes back to the list.
// The rules — how far the card follows past its ends, which rest a lifted finger lands on, and
// when letting go leaves — are `SwimZHKit.detentVisibleHeight`, `panelRelease(from:)` and
// `panelCollapses(listPull:)`, tested; this file reads them. A drag that starts sideways is
// not the drawer's: it is left alone so the system's edge swipe can have it.
//
// HOW IT MOVES. The content is laid out ONCE, at its tallest height, and the card is a window
// onto it whose height follows the finger: only that one frame and its clip change under a
// drag — nothing inside re-measures, and the card keeps its own four rounded corners at every
// height. The map behind it is never resized either (see `PoolStage`).
//
// GLASS, and why this file may paint it. The panel floats OVER a map, the case `PoolMapView`'s
// pin card already makes and the HIG names ("floating info card over a map"); its rows are
// opaque grouped cells, so the glass carries only the card's own margins and the header the
// name sits in. The system sheet it replaces was glass at every height but the last, which is
// exactly the height at which this one stays glass.

import SwiftUI
import SwimZHKit

struct PoolPanel<Header: View, Facts: View>: View {
  @Binding var detent: Detent
  /// Pulled down past the smallest rest and let go: the screen is done with. See the header.
  let onDismiss: () -> Void
  @ViewBuilder let header: () -> Header
  @ViewBuilder let facts: () -> Facts

  /// The finger's vertical travel during a drag, positive downward. Zero at rest.
  @State private var drag: Double = 0
  /// Whether the current drag is the drawer's. Decided on its first movement: a drag that
  /// begins more sideways than down is not ours, and stays not ours until the finger lifts.
  @State private var dragIsOurs: Bool?
  /// False for the first frame, so the card slides up onto the map as the screen arrives
  /// rather than being already there.
  @State private var risen = false

  var body: some View {
    GeometryReader { geo in
      let total = geo.size.height
      let visible =
        risen
        ? detentVisibleHeight(
          resting: detent.height(in: total, scale: .panel), drag: drag, in: total, scale: .panel)
        : 0
      VStack(spacing: 0) {
        handle
        header()
        facts()
      }
      // The content is laid out ONCE, at the tallest rest; nothing inside re-measures.
      .frame(
        width: geo.size.width - 2 * Design.Space.row,
        height: Detent.tall.height(in: total, scale: .panel),
        alignment: .top
      )
      // ...and the CARD is the visible window onto it, so all four corners are the card's own
      // at every height.
      .frame(height: visible, alignment: .top)
      .clipShape(.rect(cornerRadius: Design.Radius.panel))
      .glassEffect(.regular, in: .rect(cornerRadius: Design.Radius.panel))
      .padding(.horizontal, Design.Space.row)
      .frame(maxHeight: .infinity, alignment: .bottom)
      .gesture(dragging(in: total))
      .accessibilityElement(children: .contain)
      .accessibilityIdentifier("poolPanel")
      .onAppear {
        withAnimation(panelSpring) { risen = true }
      }
    }
  }

  /// The grab handle: the one glyph-free affordance every phone user reads as "drag me".
  private var handle: some View {
    Capsule()
      .fill(.secondary)
      .frame(width: 36, height: 5)
      .padding(.top, Design.Space.row)
      .padding(.bottom, Design.Space.tight)
      .frame(maxWidth: .infinity)
      .accessibilityHidden(true)
  }

  /// The drag: follow the finger, then land on the rest it was heading for — or leave.
  ///
  /// `minimumDistance` keeps a tap on the header from registering as a drag; the panel's own
  /// buttons keep their taps. Inside the facts list, at the tall rest, the list's scroll wins
  /// (a child gesture beats this one).
  private func dragging(in total: Double) -> some Gesture {
    DragGesture(minimumDistance: 10, coordinateSpace: .local)
      .onChanged { value in
        if dragIsOurs == nil {
          dragIsOurs = abs(value.translation.height) >= abs(value.translation.width)
        }
        guard dragIsOurs == true else { return }
        drag = value.translation.height
      }
      .onEnded { value in
        defer { dragIsOurs = nil }
        guard dragIsOurs == true else { return }
        switch panelRelease(
          from: detent, projectedDrag: value.predictedEndTranslation.height, in: total)
        {
        case .dismiss:
          onDismiss()
        case .settle(let landing):
          withAnimation(panelSpring) {
            detent = landing
            drag = 0
          }
        }
      }
  }
}

/// The one motion the panel rises and settles with.
let panelSpring: Animation = .spring(duration: 0.45, bounce: 0.15)
