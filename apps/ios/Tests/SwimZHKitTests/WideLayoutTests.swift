import Testing

@testable import SwimZHKit

@Suite("Wide-window layout numbers")
struct WideLayoutTests {
  @Test("the list column takes under half of a wide window, within its bounds")
  func columnShare() {
    // An unfolded phone / iPad mini portrait class of width.
    #expect(listColumnWidth(in: 744) == 744 * listColumnShare)
    #expect(listColumnWidth(in: 744) < 744 / 2)
  }

  @Test("the column never drops under a phone's width, however narrow the window")
  func floor() {
    #expect(listColumnWidth(in: 600) == listColumnMinimumWidth)
  }

  @Test("the column stops growing past its ceiling, so a 13-inch window is mostly map")
  func ceiling() {
    #expect(listColumnWidth(in: 1366) == listColumnMaximumWidth)
    #expect(listColumnMinimumWidth < listColumnMaximumWidth)
  }
}

@Suite("The column's height and side")
struct ColumnGestureTests {
  @Test("the column is the phone drawer's rules on its own scale, reaching the whole height")
  func scale() {
    let total = 800.0
    let scale = DetentScale.column
    #expect(Detent.tall.height(in: total, scale: scale) == total)
    #expect(
      Detent.peek.height(in: total, scale: scale) < Detent.half.height(in: total, scale: scale))
    // Dragged 100 down from tall: 700. Past the top: a quarter of the excess.
    #expect(detentVisibleHeight(resting: total, drag: 100, in: total, scale: scale) == 700)
    #expect(detentVisibleHeight(resting: total, drag: -100, in: total, scale: scale) == 825)
    // A flick lands on the rest it was headed for, and never leaves the screen.
    #expect(detentLanding(from: .tall, projectedDrag: 300, in: total, scale: scale) == .half)
    #expect(detentLanding(from: .tall, projectedDrag: 600, in: total, scale: scale) == .peek)
    #expect(detentLanding(from: .peek, projectedDrag: 900, in: total, scale: scale) == .peek)
  }

  @Test("the column changes side only when its centre crosses the middle")
  func side() {
    // A 744-point window, a 327-point column, 16 of margin: the centre rests at 179.5.
    let width = 744.0
    let column = listColumnWidth(in: width)
    #expect(
      columnSide(from: .leading, projectedDrag: 100, columnWidth: column, margin: 16, in: width)
        == .leading)
    #expect(
      columnSide(from: .leading, projectedDrag: 300, columnWidth: column, margin: 16, in: width)
        == .trailing)
    #expect(
      columnSide(from: .trailing, projectedDrag: -300, columnWidth: column, margin: 16, in: width)
        == .leading)
    #expect(
      columnSide(from: .trailing, projectedDrag: -50, columnWidth: column, margin: 16, in: width)
        == .trailing)
  }
}

@Suite("The column's search row, pulled for")
struct ColumnControlsTests {
  @Test("hidden at rest, shown by a pull, kept through the settle, hidden by a scroll")
  func lifecycle() {
    #expect(!columnControlsShouldShow(scrolled: 0, showing: false, pinned: false))
    #expect(!columnControlsShouldShow(scrolled: -20, showing: false, pinned: false))
    #expect(columnControlsShouldShow(scrolled: -60, showing: false, pinned: false))
    // The pull lets go: the list settles at zero, and the row stays.
    #expect(columnControlsShouldShow(scrolled: 0, showing: true, pinned: false))
    #expect(columnControlsShouldShow(scrolled: 5, showing: true, pinned: false))
    // Scrolling on into the list puts it away.
    #expect(!columnControlsShouldShow(scrolled: 30, showing: true, pinned: false))
  }

  @Test("a focused field or a typed query pins the row whatever the list does")
  func pinned() {
    #expect(columnControlsShouldShow(scrolled: 400, showing: true, pinned: true))
    #expect(columnControlsShouldShow(scrolled: 400, showing: false, pinned: true))
  }
}
