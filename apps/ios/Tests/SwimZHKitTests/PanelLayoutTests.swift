import Testing

@testable import SwimZHKit

@Suite("The pool screen's facts panel")
struct PanelLayoutTests {
  static let total: Double = 1000

  @Test("the three rests are ordered and none of them covers the whole map")
  func restsAreOrdered() {
    let heights = PanelDetent.allCases.map { $0.height(in: Self.total) }
    #expect(heights == heights.sorted())
    #expect(heights.first! > 0)
    #expect(heights.last! < Self.total, "the tallest rest must leave a band of map")
  }

  @Test("between the rests the panel follows the finger exactly")
  func followsTheFinger() {
    let rest = PanelDetent.half.height(in: Self.total)
    #expect(panelVisibleHeight(resting: rest, drag: 100, in: Self.total) == rest - 100)
    #expect(panelVisibleHeight(resting: rest, drag: -100, in: Self.total) == rest + 100)
  }

  @Test("past either end it follows at a quarter, so it can never leave the screen")
  func overdragIsSoftened() {
    let floor = PanelDetent.peek.height(in: Self.total)
    let ceiling = PanelDetent.tall.height(in: Self.total)
    // Dragged 200 down from the lowest rest: 50 lower, not 200.
    #expect(
      panelVisibleHeight(resting: floor, drag: 200, in: Self.total)
        == floor - 200 * panelOverdragShare)
    // Dragged 200 up from the highest: 50 higher, not 200.
    #expect(
      panelVisibleHeight(resting: ceiling, drag: -200, in: Self.total)
        == ceiling + 200 * panelOverdragShare)
    // ...and even a whole-screen drag down leaves most of the lowest rest on screen.
    #expect(panelVisibleHeight(resting: floor, drag: Self.total, in: Self.total) > 0)
  }

  @Test("a lifted finger lands on the nearest rest to where it was headed")
  func landsOnTheNearestRest() {
    // From peek, a small drag up goes back to peek; a big one lands on half.
    #expect(panelDetent(from: .peek, projectedDrag: -20, in: Self.total) == .peek)
    #expect(panelDetent(from: .peek, projectedDrag: -250, in: Self.total) == .half)
    // From tall, a drag down of half the screen lands on half, not peek.
    #expect(panelDetent(from: .tall, projectedDrag: 350, in: Self.total) == .half)
  }

  @Test("a flick skips a rest the finger never reached")
  func aFlickSkips() {
    // The projection carries the drag far past half, so peek → tall in one flick.
    #expect(panelDetent(from: .peek, projectedDrag: -700, in: Self.total) == .tall)
    // ...and a hard flick down from tall goes all the way to peek.
    #expect(panelDetent(from: .tall, projectedDrag: 900, in: Self.total) == .peek)
  }

  @Test("pulled well below the smallest rest, letting go leaves the screen")
  func pullingPastTheBottomDismisses() {
    // From peek, a drag headed past the dismiss distance leaves; one short of it settles back.
    #expect(
      panelRelease(from: .peek, projectedDrag: panelDismissBeyond + 1, in: Self.total) == .dismiss
    )
    #expect(
      panelRelease(from: .peek, projectedDrag: panelDismissBeyond - 1, in: Self.total)
        == .settle(.peek))
    // A drag that ends ABOVE peek never dismisses, however fast.
    #expect(panelRelease(from: .half, projectedDrag: 200, in: Self.total) == .settle(.peek))
    // ...and neither does a whole-screen flick from higher up: it lands on the smallest size
    // and stops. Two pulls to leave, never one — a reader closing the facts to see the map must
    // not be able to overshoot out of the screen.
    #expect(panelRelease(from: .tall, projectedDrag: 1200, in: Self.total) == .settle(.peek))
    #expect(panelRelease(from: .half, projectedDrag: 900, in: Self.total) == .settle(.peek))
  }

  @Test("a pull past the top of the facts list steps the panel down only when deliberate")
  func aListPullCollapses() {
    #expect(!panelCollapses(listPull: 0))
    #expect(!panelCollapses(listPull: panelCollapsePull / 2))
    #expect(panelCollapses(listPull: panelCollapsePull))
  }
}
