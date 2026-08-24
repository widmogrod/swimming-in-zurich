// The one seam `swift test` structurally cannot reach: SwiftUI's `DynamicTypeSize` mapped onto
// the kit's `TypeSize`.
//
// `SwimZHKit` must not import SwiftUI (a package source lint fails the build if it does), so the
// two enums are declared separately with the same twelve cases in the same order and joined by
// `TypeSize(_ dynamic:)`. That mapping is by RANK, which has exactly one failure mode — the two
// enums disagreeing about order — and this is the only target that can see both types and
// assert it.
//
// It also pins the property the whole accessibility rule rests on: `isAccessibilitySize` must
// mean the same thing on both sides. If SwiftUI's five accessibility sizes ever mapped onto four
// of ours, the day strip would keep its standard layout for one of them and the acceptance
// criterion would be quietly false while every SwimZHKit test stayed green.

import SwiftUI
import Testing

@testable import SwimZH
import SwimZHKit

@Suite("DynamicTypeSize bridge")
struct TypeSizeBridgeTests {
  @Test("the two enums have the same twelve cases in the same order")
  func rankMappingIsOrderPreserving() {
    #expect(DynamicTypeSize.allCases.count == TypeSize.allCases.count)
    for (index, dynamic) in DynamicTypeSize.allCases.enumerated() {
      #expect(
        TypeSize(dynamic) == TypeSize.allCases[index],
        "\(dynamic) is rank \(index) in SwiftUI but maps to \(TypeSize(dynamic))"
      )
    }
  }

  @Test("the named cases line up one for one")
  func namedCasesLineUp() {
    #expect(TypeSize(.xSmall) == .xSmall)
    #expect(TypeSize(.large) == .large)
    #expect(TypeSize(.large) == TypeSize.standard)
    #expect(TypeSize(.xxxLarge) == .xxxLarge)
    #expect(TypeSize(.accessibility1) == .accessibility1)
    #expect(TypeSize(.accessibility5) == .accessibility5)
  }

  @Test("accessibility means the same thing on both sides")
  func accessibilityAgrees() {
    for dynamic in DynamicTypeSize.allCases {
      #expect(
        TypeSize(dynamic).isAccessibilitySize == dynamic.isAccessibilitySize,
        "\(dynamic) disagrees about being an accessibility size"
      )
    }
  }

  @Test("the strip really does collapse at every SwiftUI accessibility size")
  func stripCollapsesAtEveryAccessibilitySize() {
    // The end-to-end statement of acceptance 4's assertable half, driven from SwiftUI's own
    // enum rather than from ours — so the criterion cannot be satisfied by a mapping that
    // happens to be wrong.
    let standard = stripLayout(for: TypeSize(.large), width: 393)
    for dynamic in DynamicTypeSize.allCases where dynamic.isAccessibilitySize {
      let layout = stripLayout(for: TypeSize(dynamic), width: 393)
      #expect(layout.labelsCollapsed)
      #expect(layout.chipCount < standard.chipCount)
      #expect(layout.chipWidth >= standard.chipWidth)
    }
  }
}
