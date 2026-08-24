// The launch instrument — shipped BEFORE there is a launch worth measuring.
//
// This is not optional instrumentation, it is what keeps the launch number HONEST.
// Apple measures launch as time-to-first-frame, so an app that draws an empty list shell
// and then loads its store would report an excellent official number and a false one: the
// user is still looking at nothing. `extendLaunchMeasurementForTaskID:` exists precisely
// for "extra setup tasks required to make the application perceived as fully launched,
// such as loading up content from the disk", which is exactly what opening the bundled
// store and answering for today is.
//
// Two reporters, one call site:
//  * an `OSSignposter` interval, which is what Instruments and a local trace read;
//  * MetricKit's extended launch measurement, which is what the FIELD number reads.
//
// Launch time is deliberately NOT a CI gate (see `apps/ios/budgets.json`): Xcode stores
// performance baselines per device configuration because they do not travel, and no
// published simulator-variance figure was found. S2b ships the instrument; the number is
// read on a real device.
//
// The MetricKit call is behind `LaunchMeasurement` so the state machine — the part that
// can actually be wrong — is provable headlessly under `swift test`, with no MetricKit
// daemon and no launch. The adapter left over is three one-line calls.

import Foundation
import MetricKit
import os

/// Where an extended launch measurement is reported.
///
/// `@MainActor` is Apple's requirement, not a convenience: "This method needs to be called
/// on the main thread."
@MainActor
public protocol LaunchMeasurement: Sendable {
  func begin(taskID: String)
  func finish(taskID: String)
}

/// One app-start-to-data-on-screen measurement.
///
/// Reentrant by design: `start()` after the first and `dataOnScreen()` after the first are
/// no-ops rather than errors. A SwiftUI body can be evaluated any number of times, and a
/// second `begin` for a task already begun is exactly the mistake this absorbs — Apple caps
/// extended launch tasks at 16 and ends the whole measurement when the last one finishes.
@MainActor
public final class LaunchSignpost {
  /// The task identifier. Stable across releases so field data stays comparable.
  public static let dataOnScreenTaskID = "ch.swimzh.launch.dataOnScreen"

  /// What the app uses. Tests build their own with a recording double.
  public static let shared = LaunchSignpost()

  public enum Phase: Sendable, Equatable {
    case idle
    case measuring
    case finished
  }

  public private(set) var phase: Phase = .idle

  private let taskID: String
  /// Internal rather than private so a test can assert the DEFAULT is the real MetricKit
  /// reporter — an instrument wired to a silent stub is the failure this slice prevents.
  let measurement: LaunchMeasurement?
  private let signposter: OSSignposter
  private var interval: OSSignpostIntervalState?

  public init(
    taskID: String = LaunchSignpost.dataOnScreenTaskID,
    measurement: LaunchMeasurement? = MetricKitLaunchMeasurement()
  ) {
    self.taskID = taskID
    self.measurement = measurement
    self.signposter = OSSignposter(subsystem: "ch.swimzh.app", category: "launch")
  }

  /// Begin the interval. Call it as early as the app can — before the first frame.
  public func start() {
    guard phase == .idle else { return }
    phase = .measuring
    interval = signposter.beginInterval("launch to data on screen")
    measurement?.begin(taskID: taskID)
  }

  /// End the interval, at the moment real data is on screen — never when the shell is.
  public func dataOnScreen() {
    guard phase == .measuring, let interval else { return }
    phase = .finished
    self.interval = nil
    signposter.endInterval("launch to data on screen", interval)
    measurement?.finish(taskID: taskID)
  }
}

/// The real reporter. Errors are swallowed on purpose: a measurement that cannot start is
/// not a reason to fail a launch, and the signpost interval still records locally.
///
/// There is deliberately no `#if` fallback stub. `extendLaunchMeasurementForTaskID:` is
/// declared `API_AVAILABLE(ios(16.0), macos(13.0))` — verified in this SDK's own header —
/// so it exists on BOTH of this package's platforms. A conditional stub would compile
/// nowhere, be covered by nothing, and show up in the CRAP gate as a permanent 0%.
@MainActor
public struct MetricKitLaunchMeasurement: LaunchMeasurement {
  public init() {}

  public func begin(taskID: String) {
    try? MXMetricManager.extendLaunchMeasurement(forTaskID: MXLaunchTaskID(taskID))
  }

  public func finish(taskID: String) {
    try? MXMetricManager.finishExtendedLaunchMeasurement(forTaskID: MXLaunchTaskID(taskID))
  }
}
