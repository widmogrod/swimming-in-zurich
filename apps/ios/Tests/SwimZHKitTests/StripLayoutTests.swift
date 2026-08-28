// S3a acceptance 4, the assertable half: accessibility size is a DESIGNED state.
//
// What a test can see is the decision — how many chips, whether labels collapse, how tall the
// strip is — because it is a pure function. What it cannot see is the rendering: actual
// truncation, `@ScaledMetric` resolution and the ≥ 44×44 pt tap targets are a human check at
// the S3a pause. This suite is deliberately explicit about that split rather than pretending
// the first proves the second.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Day strip layout across dynamic type")
struct StripLayoutTests {
  /// Widths of real phones in portrait, minus the list's own horizontal insets. The property
  /// under test is about a strip that has room for several chips; asserting "fewer chips" on a
  /// 100 pt strip would be asserting the `max(1,)` clamp instead.
  static let phoneWidths: [Double] = [320, 360, 393, 402, 430]

  @Test("the twelve sizes mirror DynamicTypeSize, in order")
  func sizesAreOrdered() {
    #expect(TypeSize.allCases.count == 12)
    #expect(TypeSize.allCases == TypeSize.allCases.sorted())
    #expect(TypeSize.standard == .large)
    let accessibility = TypeSize.allCases.filter(\.isAccessibilitySize)
    #expect(
      accessibility == [
        .accessibility1, .accessibility2, .accessibility3, .accessibility4, .accessibility5,
      ]
    )
  }

  @Test("a rank out of range clamps rather than failing")
  func rankClamps() {
    // A future OS with a thirteenth size must degrade to the largest layout we know, never to
    // no layout at all.
    #expect(TypeSize(rank: 0) == .xSmall)
    #expect(TypeSize(rank: 3) == .large)
    #expect(TypeSize(rank: 11) == .accessibility5)
    #expect(TypeSize(rank: 99) == .accessibility5)
    #expect(TypeSize(rank: -4) == .xSmall)
    for (index, size) in TypeSize.allCases.enumerated() {
      #expect(TypeSize(rank: index) == size)
    }
  }

  @Test("the scale never falls below the standard size, and never falls as the size grows")
  func scaleIsMonotoneAndFloored() {
    var previous = 0.0
    for size in TypeSize.allCases {
      let scale = typeScale(size)
      #expect(scale >= 1.0, "\(size) scales below standard")
      #expect(scale >= previous, "\(size) scales down from the size below it")
      previous = scale
    }
    #expect(typeScale(.standard) == 1.0)
  }

  @Test("chip width NEVER shrinks below the standard-size value", arguments: TypeSize.allCases)
  func chipWidthNeverShrinks(size: TypeSize) {
    // Including the four sizes BELOW `.large`: a smaller text size must not shrink the chip
    // under the 44 pt tap target to win a fraction of a chip.
    let standard = stripLayout(for: .standard, width: 393)
    let layout = stripLayout(for: size, width: 393)
    #expect(layout.chipWidth >= standard.chipWidth)
    #expect(layout.stripHeight >= standard.stripHeight)
    #expect(layout.chipWidth >= 44, "a chip below 44 pt is not a tappable target")
    #expect(layout.stripHeight >= 44)
  }

  @Test("every accessibility size shows FEWER chips and collapses the labels")
  func accessibilitySizesShowFewerChips() {
    for width in Self.phoneWidths {
      let standard = stripLayout(for: .standard, width: width)
      #expect(!standard.labelsCollapsed)
      for size in TypeSize.allCases where size.isAccessibilitySize {
        let layout = stripLayout(for: size, width: width)
        let seen = "\(size) at \(width) pt: \(layout.chipCount) vs \(standard.chipCount) chips"
        #expect(layout.chipCount < standard.chipCount, "\(seen) — must scroll, not squeeze")
        #expect(layout.labelsCollapsed, "\(size) must collapse inline labels to a legend")
        #expect(layout.chipWidth > standard.chipWidth)
      }
    }
  }

  @Test("chip count never rises as the text size rises")
  func chipCountIsMonotone() {
    for width in Self.phoneWidths {
      var previous = Int.max
      for size in TypeSize.allCases {
        let count = stripLayout(for: size, width: width).chipCount
        #expect(count <= previous, "\(size) at \(width) pt shows MORE chips than the size below")
        previous = count
      }
    }
  }

  @Test("a zero or unmeasured width still yields a usable strip")
  func degenerateWidths() {
    // SwiftUI's first layout pass hands out a width of 0, and a zero-chip strip is an empty
    // control the user cannot escape.
    for width in [0.0, -10, .infinity, .nan] {
      let layout = stripLayout(for: .large, width: width)
      #expect(layout.chipCount >= 1)
      #expect(layout.chipWidth > 0)
    }
  }

  // MARK: - Hiding the strip while the list is read

  @Test("near the top the strip always shows, and deep in the list it never does")
  func theTwoThresholds() {
    let height = stripLayout(for: .large, width: 400).stripHeight
    for showing in [true, false] {
      #expect(stripShouldShow(scrolled: 0, stripHeight: height, showing: showing))
      #expect(
        stripShouldShow(scrolled: stripShowsWithin - 1, stripHeight: height, showing: showing))
      #expect(
        !stripShouldShow(
          scrolled: stripHidesBeyond(stripHeight: height) + 1, stripHeight: height,
          showing: showing))
      #expect(!stripShouldShow(scrolled: 5000, stripHeight: height, showing: showing))
    }
  }

  @Test("between them nothing changes, so the strip cannot flap")
  func theBandHolds() {
    let height = stripLayout(for: .large, width: 400).stripHeight
    for scrolled in [stripShowsWithin, stripHidesBeyond(stripHeight: height)] {
      #expect(stripShouldShow(scrolled: scrolled, stripHeight: height, showing: true))
      #expect(!stripShouldShow(scrolled: scrolled, stripHeight: height, showing: false))
    }
  }

  @Test("the band clears the strip at EVERY text size", arguments: TypeSize.allCases)
  func theBandClearsTheInset(size: TypeSize) {
    // The number that makes the feedback loop impossible, stated rather than assumed. A fixed
    // band was written first and this test rejected it: at an accessibility size the strip is
    // three times as tall, so the jump hiding it causes was wider than the band meant to absorb
    // it — the loop would have come back exactly where the layout is already under most strain.
    let height = stripLayout(for: size, width: 400).stripHeight
    #expect(stripHidesBeyond(stripHeight: height) - stripShowsWithin > height)
  }
}

@Suite("When the pool screen's bar states the name")
struct PoolTitleTests {
  static let nameBottom: Double = 200

  @Test("at the top the hero owns the name and the bar says nothing")
  func atTheTopTheBarIsEmpty() {
    #expect(!poolTitleShows(scrolled: 0, nameBottom: Self.nameBottom, showing: false))
    // ...even if it was showing: scrolling back up must give the hero its name back.
    #expect(!poolTitleShows(scrolled: 0, nameBottom: Self.nameBottom, showing: true))
  }

  @Test("once the hero's name has gone the bar takes it over")
  func pastTheNameTheBarTakesOver() {
    #expect(poolTitleShows(scrolled: 260, nameBottom: Self.nameBottom, showing: false))
  }

  @Test("a finger resting on the boundary does not flicker the title")
  func theBandHolds() {
    // Inside the band the answer is whatever it already was, so a scroll that hovers on the
    // threshold cannot strobe the bar.
    let inside = Self.nameBottom - poolTitleBand / 2
    #expect(poolTitleShows(scrolled: inside, nameBottom: Self.nameBottom, showing: true))
    #expect(!poolTitleShows(scrolled: inside, nameBottom: Self.nameBottom, showing: false))
  }

  @Test("a taller name at an accessibility size hands over later, not sooner")
  func aTallerNameHandsOverLater() {
    // The reason `nameBottom` is a parameter. At an accessibility text size the hero's name is
    // far taller, and a fixed threshold would put the name in the bar while it was still on
    // screen — the exact duplication this rule exists to remove, at the size where the screen
    // has least room for it.
    let scrolled: Double = 240
    #expect(poolTitleShows(scrolled: scrolled, nameBottom: 200, showing: false))
    #expect(!poolTitleShows(scrolled: scrolled, nameBottom: 420, showing: false))
  }
}
