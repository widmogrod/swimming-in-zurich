// Peak memory, measured where the number means something.
//
// THREE constraints decided this file's shape, and each of them is a way the same
// measurement is routinely reported wrong:
//
//  1. It is an **app-hosted unit test**, never a UI test. `XCTMemoryMetric` against an
//     `XCUIApplication` measures the test RUNNER, not the app, and returns a number that
//     looks plausible and means nothing.
//  2. `XCTMemoryMetric` is a LOOSE ratchet, not a gate. Measured here on Xcode 26 it emits
//     TWO sub-metrics: `XCTMetric_Memory.physical` — the delta, which read **0.000 kB**
//     across all five iterations, exactly the uselessness the plan predicted — and
//     `XCTMetric_Memory.physical_peak`, which read 51.3 MB. Neither is asserted against a
//     baseline: Xcode stores performance baselines per device configuration precisely
//     because they do not travel, and CI runs a simulator. The actual ceiling from
//     `budgets.json` is asserted separately from `task_vm_info.phys_footprint`, which is
//     the number the OS terminates a process on.
//  3. It is XCTest, not Swift Testing. The `XCTMetric` performance APIs are explicitly
//     unsupported in Swift Testing; the two coexist in this target for exactly this reason.
//
// Deliberately NOT used as the canary: `sqlite3_memory_used()`. Apple's libsqlite3 is built
// with SQLITE_CONFIG_MEMSTATUS OFF, so it returns 0 always — a canary that can never sing.

import Foundation
import SwimZHKit
import XCTest

@testable import SwimZH

final class MemoryMetricTests: XCTestCase {
  /// The 100 MB ceiling from `apps/ios/budgets.json`, restated here because a test cannot
  /// read the repository from a device. `test_budgets_json_ceiling_matches_the_metric_test`
  /// in the Python suite is what keeps the two in step.
  static let peakFootprintLimit: UInt64 = 100 * 1024 * 1024

  /// The workload the budget is stated over: open the bundled store and answer for a full
  /// day across the whole roster — the "list of 57 pools" the budgets table names.
  /// `static` is load-bearing, not style: an `XCTestCase` is not `Sendable`, so capturing
  /// `self` in the `@MainActor` task below is a strict-concurrency error.
  @MainActor
  private static func fullDayAnswer() async throws -> Answer {
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    return try await store.answer(
      onDay: metadata.horizonStart,
      at: TimeOfDay(hour: 12, minute: 0),
      for: Person()
    )
  }

  /// Resident footprint, in bytes — the number iOS actually terminates a process on.
  private static func footprint() -> UInt64 {
    var info = task_vm_info_data_t()
    var count = mach_msg_type_number_t(
      MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size
    )
    let result = withUnsafeMutablePointer(to: &info) {
      $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
        task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
      }
    }
    return result == KERN_SUCCESS ? UInt64(info.phys_footprint) : 0
  }

  /// The loose ratchet: how much one full answer ALLOCATES, run repeatedly by XCTest.
  ///
  /// No baseline is asserted here on purpose — Xcode stores performance baselines per
  /// device configuration precisely because they do not travel, and CI runs a simulator.
  /// The recorded number is what a human compares across runs; the hard ceiling is below.
  func testMemoryOfAFullDayAnswer() {
    measure(metrics: [XCTMemoryMetric()]) {
      let answered = expectation(description: "answered")
      Task { @MainActor in
        _ = try? await Self.fullDayAnswer()
        answered.fulfill()
      }
      wait(for: [answered], timeout: 30)
    }
  }

  /// The gate: after the workload, the process is inside the budget's ceiling.
  @MainActor
  func testFootprintStaysInsideTheBudget() async throws {
    let answer = try await Self.fullDayAnswer()
    // Guard against a vacuous pass: a measurement over an empty answer would sit far
    // under any ceiling and prove nothing about the app.
    XCTAssertFalse(answer.options.isEmpty)
    XCTAssertFalse(answer.statuses.isEmpty)

    let used = Self.footprint()
    XCTAssertGreaterThan(used, 0, "task_vm_info gave no reading — the ceiling is unproven")
    XCTAssertLessThan(
      used, Self.peakFootprintLimit,
      "footprint \(used / 1024 / 1024) MB exceeds the \(Self.peakFootprintLimit / 1024 / 1024) MB budget"
    )
  }
}
