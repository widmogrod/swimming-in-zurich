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

  @Test("a form is held narrower than a wide window and wider than the list column")
  func formWidth() {
    #expect(formMaximumWidth > listColumnMaximumWidth)
    #expect(formMaximumWidth < 744)
  }

  @Test("the column stops growing past its ceiling, so a 13-inch window is mostly map")
  func ceiling() {
    #expect(listColumnWidth(in: 1366) == listColumnMaximumWidth)
    #expect(listColumnMinimumWidth < listColumnMaximumWidth)
  }
}

@Suite("The column's height and side")
struct ColumnGestureTests {
  @Test("the column follows the finger between its rests and resists beyond them")
  func visibleHeight() {
    let total = 800.0
    let tall = ColumnDetent.tall.height(in: total)
    #expect(columnVisibleHeight(resting: tall, drag: 100, in: total) == 700)
    // Past the top: a quarter of the excess.
    #expect(columnVisibleHeight(resting: tall, drag: -100, in: total) == 825)
    // Past the bottom: the same.
    let peek = ColumnDetent.peek.height(in: total)
    #expect(columnVisibleHeight(resting: peek, drag: 100, in: total) == peek - 25)
  }

  @Test("a flick lands on the rest it was headed for, and never leaves the screen")
  func release() {
    let total = 800.0
    #expect(columnDetent(from: .tall, projectedDrag: 300, in: total) == .half)
    #expect(columnDetent(from: .tall, projectedDrag: 600, in: total) == .peek)
    #expect(columnDetent(from: .peek, projectedDrag: -600, in: total) == .tall)
    // Headed far below the lowest rest: still the lowest rest, not gone.
    #expect(columnDetent(from: .peek, projectedDrag: 900, in: total) == .peek)
    #expect(columnDetent(from: .tall, projectedDrag: 10, in: total) == .tall)
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
