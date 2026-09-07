import Testing

@testable import SwimZHKit

@Suite("The pool screen's facts panel")
struct PanelLayoutTests {
  static let total: Double = 1000
  static let scale = DetentScale.panel

  func height(_ detent: Detent) -> Double { detent.height(in: Self.total, scale: Self.scale) }
  func visible(resting: Double, drag: Double) -> Double {
    detentVisibleHeight(resting: resting, drag: drag, in: Self.total, scale: Self.scale)
  }
  func landing(from detent: Detent, projectedDrag: Double) -> Detent {
    detentLanding(from: detent, projectedDrag: projectedDrag, in: Self.total, scale: Self.scale)
  }

  @Test("the three rests are ordered and none of them covers the whole map")
  func restsAreOrdered() {
    let heights = Detent.allCases.map(height)
    #expect(heights == heights.sorted())
    #expect(heights.first! > 0)
    #expect(heights.last! < Self.total, "the tallest rest must leave a band of map")
  }

  @Test("between the rests the panel follows the finger exactly")
  func followsTheFinger() {
    let rest = height(.half)
    #expect(visible(resting: rest, drag: 100) == rest - 100)
    #expect(visible(resting: rest, drag: -100) == rest + 100)
  }

  @Test("past either end it follows at a quarter, so it can never leave the screen")
  func overdragIsSoftened() {
    let floor = height(.peek)
    let ceiling = height(.tall)
    // Dragged 200 down from the lowest rest: 50 lower, not 200.
    #expect(
      visible(resting: floor, drag: 200)
        == floor - 200 * detentOverdragShare)
    // Dragged 200 up from the highest: 50 higher, not 200.
    #expect(
      visible(resting: ceiling, drag: -200)
        == ceiling + 200 * detentOverdragShare)
    // ...and even a whole-screen drag down leaves most of the lowest rest on screen.
    #expect(visible(resting: floor, drag: Self.total) > 0)
  }

  @Test("a lifted finger lands on the nearest rest to where it was headed")
  func landsOnTheNearestRest() {
    // From peek, a small drag up goes back to peek; a big one lands on half.
    #expect(landing(from: .peek, projectedDrag: -20) == .peek)
    #expect(landing(from: .peek, projectedDrag: -250) == .half)
    // From tall, a drag down of half the screen lands on half, not peek.
    #expect(landing(from: .tall, projectedDrag: 350) == .half)
  }

  @Test("a flick skips a rest the finger never reached")
  func aFlickSkips() {
    // The projection carries the drag far past half, so peek → tall in one flick.
    #expect(landing(from: .peek, projectedDrag: -700) == .tall)
    // ...and a hard flick down from tall goes all the way to peek.
    #expect(landing(from: .tall, projectedDrag: 900) == .peek)
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
