// StripLayout.swift — accessibility size as a DESIGNED state, decided by a pure function.
//
// The plan's rule: at an accessibility text size the day strip shows FEWER CHIPS AND SCROLLS
// rather than shrinking them, and inline labels collapse to a legend. That is a design
// decision, so it is a rule; a rule inside a `body` is a rule nothing measures (there is no
// first-party way to unit-test a SwiftUI view body — calling `.body` headlessly crashes the
// process, which is why the app target is outside the CRAP gate). So it lives here and the
// view is a thin reader of it.
//
// WHY THIS TAKES `TypeSize` AND NOT SwiftUI's `DynamicTypeSize`. This package must not import
// SwiftUI — a source lint fails the build if it does, because the whole point of `SwimZHKit`
// is that it is testable headlessly on the host. `TypeSize` mirrors `DynamicTypeSize`'s twelve
// cases in the same order, and the app maps one to the other by RANK (`TypeSize(rank:)`) —
// one line, no branching, and pinned by an app-hosted test that can see both types.

import Foundation

/// The twelve dynamic-type sizes, in ascending order — the same order and the same names as
/// SwiftUI's `DynamicTypeSize`, which is what makes the rank mapping honest.
public enum TypeSize: Int, Comparable, CaseIterable, Sendable {
  case xSmall
  case small
  case medium
  case large
  case xLarge
  case xxLarge
  case xxxLarge
  case accessibility1
  case accessibility2
  case accessibility3
  case accessibility4
  case accessibility5

  /// `.large` is the system default — the size everything else is measured against.
  public static let standard: TypeSize = .large

  public static func < (lhs: TypeSize, rhs: TypeSize) -> Bool {
    lhs.rawValue < rhs.rawValue
  }

  /// The five accessibility sizes, matching `DynamicTypeSize.isAccessibilitySize`.
  public var isAccessibilitySize: Bool { self >= .accessibility1 }

  /// From a position in SwiftUI's `DynamicTypeSize.allCases`, clamped.
  ///
  /// Clamping rather than failing is deliberate: if a future OS adds a thirteenth size, an
  /// app that returned nil would have no layout at all, while one that clamps renders the
  /// largest layout it knows — degraded, never blank.
  public init(rank: Int) {
    self = TypeSize(rawValue: max(0, min(rank, TypeSize.allCases.count - 1))) ?? .large
  }
}

/// How the day strip lays out at one text size and one available width.
public struct StripLayout: Equatable, Sendable {
  /// How many day chips fit across `width` — the strip scrolls through the rest.
  public let chipCount: Int
  /// One chip's width in points. Never below the standard-size width: see `typeScale`.
  public let chipWidth: Double
  /// The strip's height in points, scaled with the text size.
  public let stripHeight: Double
  /// Whether inline ribbon/chip labels collapse to a separate legend.
  public let labelsCollapsed: Bool

  public init(chipCount: Int, chipWidth: Double, stripHeight: Double, labelsCollapsed: Bool) {
    self.chipCount = chipCount
    self.chipWidth = chipWidth
    self.stripHeight = stripHeight
    self.labelsCollapsed = labelsCollapsed
  }
}

/// A chip at the standard text size: two short lines (weekday over day-of-month) plus padding,
/// and comfortably over Apple's 44×44 pt minimum target on both axes.
private let baseChipWidth = 64.0
private let baseStripHeight = 56.0

/// The text scale of each size, FLOORED AT 1.
///
/// The floor is the acceptance criterion, and it is also the right design: at `.large` the chip
/// is already at its minimum comfortable tap target, so shrinking it at `.xSmall` would buy a
/// fraction of a chip and break the 44×44 pt rule. Above `.large` the scale rises monotonically,
/// which is what makes the chip count fall — the chips grow, the strip scrolls, and nothing is
/// squeezed. Values approximate the system's own text scaling; only their ORDER and the floor
/// are load-bearing, and both are asserted.
public func typeScale(_ size: TypeSize) -> Double {
  switch size {
  case .xSmall, .small, .medium, .large: return 1.0
  case .xLarge: return 1.1
  case .xxLarge: return 1.2
  case .xxxLarge: return 1.35
  case .accessibility1: return 1.6
  case .accessibility2: return 1.9
  case .accessibility3: return 2.2
  case .accessibility4: return 2.6
  case .accessibility5: return 3.0
  }
}

/// The day strip's layout at `size` across `width` points.
///
/// `chipCount` is how many chips are VISIBLE, not how many exist: the strip always spans the
/// store's whole horizon and scrolls. That is the difference between "fewer chips" (the designed
/// accessibility state) and "a shorter horizon" (a silent loss of answers).
public func stripLayout(for size: TypeSize, width: Double) -> StripLayout {
  let scale = typeScale(size)
  let chipWidth = baseChipWidth * scale
  // At least one chip, always: a zero-chip strip is an empty control the user cannot escape,
  // and a width of 0 is a real state (the first layout pass, before SwiftUI has measured).
  let fits = width.isFinite && width > 0 ? Int((width / chipWidth).rounded(.down)) : 1
  return StripLayout(
    chipCount: max(1, fits),
    chipWidth: chipWidth,
    stripHeight: baseStripHeight * scale,
    labelsCollapsed: size.isAccessibilitySize
  )
}
