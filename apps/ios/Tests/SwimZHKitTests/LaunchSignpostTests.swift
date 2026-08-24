// The launch instrument's state machine, proved with no launch and no MetricKit daemon.
//
// What can actually go wrong here is not the MetricKit call (three one-line forwards) but
// the SEQUENCING: a second `begin` for a task already begun, a `finish` for a task never
// begun, or — the one that would matter most — an interval ended when the empty shell is
// drawn rather than when the data is. Each of those is a test below.

import Foundation
import Testing

@testable import SwimZHKit

/// Records what a real MetricKit reporter would have been told.
@MainActor
final class RecordingMeasurement: LaunchMeasurement {
  private(set) var begun: [String] = []
  private(set) var finished: [String] = []

  func begin(taskID: String) { begun.append(taskID) }
  func finish(taskID: String) { finished.append(taskID) }
}

@Suite("Launch signpost")
@MainActor
struct LaunchSignpostTests {
  func makeSignpost() -> (LaunchSignpost, RecordingMeasurement) {
    let recorder = RecordingMeasurement()
    return (LaunchSignpost(taskID: "test.task", measurement: recorder), recorder)
  }

  @Test("the interval spans start to data on screen, exactly once")
  func oneIntervalPerLaunch() {
    let (signpost, recorder) = makeSignpost()
    #expect(signpost.phase == .idle)

    signpost.start()
    #expect(signpost.phase == .measuring)
    // Begun and NOT finished: the whole point is that the measurement stays open across
    // the store load. A `finish` here would be the false-excellent number.
    #expect(recorder.begun == ["test.task"])
    #expect(recorder.finished.isEmpty)

    signpost.dataOnScreen()
    #expect(signpost.phase == .finished)
    #expect(recorder.finished == ["test.task"])
  }

  @Test("a repeated start does not open a second measurement")
  func startIsIdempotent() {
    // A SwiftUI body can be evaluated any number of times, and Apple caps extended launch
    // tasks at 16 — so a `start()` per evaluation would exhaust them, silently.
    let (signpost, recorder) = makeSignpost()
    signpost.start()
    signpost.start()
    signpost.start()
    #expect(recorder.begun.count == 1)
  }

  @Test("a repeated data-on-screen does not close the measurement twice")
  func finishIsIdempotent() {
    let (signpost, recorder) = makeSignpost()
    signpost.start()
    signpost.dataOnScreen()
    signpost.dataOnScreen()
    #expect(recorder.finished.count == 1)
    #expect(signpost.phase == .finished)
  }

  @Test("data on screen without a start reports nothing at all")
  func finishWithoutStartIsInert() {
    let (signpost, recorder) = makeSignpost()
    signpost.dataOnScreen()
    #expect(recorder.begun.isEmpty)
    #expect(recorder.finished.isEmpty)
    #expect(signpost.phase == .idle)
  }

  @Test("a start after the measurement finished does not reopen it")
  func finishedStaysFinished() {
    let (signpost, recorder) = makeSignpost()
    signpost.start()
    signpost.dataOnScreen()
    signpost.start()
    #expect(recorder.begun.count == 1)
    #expect(signpost.phase == .finished)
  }

  @Test("the task id is stable, namespaced and non-empty")
  func taskIDIsStable() {
    // Field data is only comparable release to release if this string does not move.
    #expect(LaunchSignpost.dataOnScreenTaskID == "ch.swimzh.launch.dataOnScreen")
  }

  @Test("the default reporter is the MetricKit one, not a silent stub")
  func theDefaultReporterIsReal() {
    // An instrument that exists but is wired to nothing is the exact failure this slice
    // is meant to prevent, so the DEFAULT is asserted, not just the injected double.
    // MetricKit is not CALLED here: this test proves the wiring, and the sequencing tests
    // above prove the behaviour, without a launch to measure.
    #expect(LaunchSignpost().measurement is MetricKitLaunchMeasurement)
    #expect(LaunchSignpost.shared.measurement is MetricKitLaunchMeasurement)
  }
}
