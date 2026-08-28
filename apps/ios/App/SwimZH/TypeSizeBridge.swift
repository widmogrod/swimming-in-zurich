// TypeSizeBridge.swift — SwiftUI's `DynamicTypeSize` to the kit's `TypeSize`.
//
// `SwimZHKit` may not import SwiftUI (a source lint fails the build if it does), because the
// whole point of the package is that it is testable headlessly on the host — and the layout
// rule the day strip obeys must live there, where a test can drive it. So the two enums are
// declared separately with the same twelve cases in the same order, and this is the single
// line that joins them.
//
// It maps by RANK rather than by a twelve-arm switch on purpose: a switch here would be twelve
// chances to transpose two cases in a target the CRAP gate does not score, while a rank has
// exactly one failure mode — the two enums disagreeing about order — which the app-hosted test
// beside it asserts case by case, because it is the one target that can see both types.

import SwiftUI
import SwimZHKit

extension TypeSize {
  init(_ dynamic: DynamicTypeSize) {
    self.init(rank: DynamicTypeSize.allCases.firstIndex(of: dynamic) ?? 3)
  }
}
