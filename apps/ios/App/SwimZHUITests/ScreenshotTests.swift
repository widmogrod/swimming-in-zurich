// ScreenshotTests.swift — the App Store screenshots, produced by driving the app.
//
// WHY A TEST AND NOT A PERSON WITH A SIMULATOR. Apple wants a fresh set on every visual change,
// and a hand-captured set rots silently: it keeps looking plausible long after the screen it
// shows stopped existing. Capturing them the same way `BehaviourTests` drives the app means a
// screenshot can only depict a state the app can actually reach — if a navigation step here
// breaks, this FAILS rather than quietly photographing the wrong screen.
//
// NOT PART OF THE QA CHAIN. `make ios-sim-test` skips this class by name, because these run on a
// 6.9" device the rest of the chain does not use and they prove no behaviour of their own. The
// capture is `make ios-screenshots`, which also sets the status bar to Apple's 09:41 and pulls
// the attachments out of the result bundle.
//
// QUERIES ARE BY IDENTIFIER, NEVER BY LABEL — the same rule as `BehaviourTests`, for the same
// reason: every sentence in this app is one of five languages.

import XCTest

@MainActor
final class ScreenshotTests: XCTestCase {
  private var app: XCUIApplication!

  override func setUp() async throws {
    continueAfterFailure = false
    app = XCUIApplication()
    // The same clean start `BehaviourTests` documents: `LocationSource.preferred` is persisted,
    // so without this the shots would be measured from wherever a previous run last opted into.
    // A screenshot set that silently changes its pool ORDER between runs is one nobody can
    // review by looking at it.
    app.launchArguments += ["-swimzh.useMyLocation", "NO"]
    // NOT launched here: each test below launches, because one of them adds arguments first.
  }

  /// The Lab switches, spelled out for the same reason the location key is: this target links
  /// no app code. `Lab.swift` keeps every iOS 27 experiment behind one of these, defaulting to
  /// the new look; `-key NO` at launch is how a test asks for the previous one.
  ///
  /// A LAUNCH ARGUMENT, and never an environment variable. Two attempts to switch the old look
  /// on from the `xcodebuild test` line — `TEST_RUNNER_SWIMZH_LAB_OFF=1`, then a scheme
  /// variable expanded from a build setting — produced "old look" sets that were pixel for
  /// pixel the new one; a marker attachment proved the variable never reached this process.
  /// The argument path is the one `-swimzh.useMyLocation NO` already proves on every run.
  private let labKeys = ["lab.glassStrip", "lab.glassCard", "lab.heroExtends", "lab.symbolMotion"]

  private func launch() {
    app.launch()
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 30), "the list never showed a pool row")
  }

  /// One element by identifier, whatever SwiftUI decided to call its type. See the note in
  /// `BehaviourTests`: `app.buttons["x"]` guesses the type, and SwiftUI's choice moves.
  private func find(_ identifier: String) -> XCUIElement {
    app.descendants(matching: .any).matching(identifier: identifier).firstMatch
  }

  /// Capture the whole screen under a name the export step turns into a filename.
  ///
  /// `XCUIScreen.main` rather than `app.screenshot()`: the App Store wants the DEVICE frame,
  /// status bar included, and the app's own screenshot is clipped to the app.
  /// `.keepAlways` is load-bearing — the default lifetime deletes the attachment when the test
  /// passes, which is every time, so the default would produce an empty result bundle.
  private func capture(_ name: String) {
    let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
    shot.name = name
    shot.lifetime = .keepAlways
    add(shot)
  }

  /// The whole set, in one test rather than five.
  ///
  /// Each screen is reached from the one before it, so five tests would mean five launches and
  /// five walks back to the same place — and any per-test ordering surprise would show up as a
  /// screenshot of the wrong screen rather than as a failure. One walk, in listing order.
  func testCaptureTheAppStoreSet() throws {
    launch()
    try walk(prefix: "")
  }

  /// The same walk with every Lab switch off — the look the app shipped before the iOS 27
  /// experiments — so the two sets can be put side by side. Files are prefixed `old-`.
  /// Select it alone with `-only-testing:SwimZHUITests/ScreenshotTests/testCaptureThePreviousLookSet`.
  func testCaptureThePreviousLookSet() throws {
    for key in labKeys {
      app.launchArguments += ["-\(key)", "NO"]
    }
    launch()
    try walk(prefix: "old-")
  }

  private func walk(prefix: String) throws {
    func capture(_ name: String) { self.capture(prefix + name) }
    // 1 — the answer the app exists to give: every pool, nearest first, for today.
    capture("01-find")

    // 2 — the lane plan, which is the fact almost nothing else publishes. It lives ON THE ROW
    // and must not navigate: `testTheLaneDisclosureExpandsAndDoesNotNavigate` is the sentence,
    // and the first draft of this file got it wrong by looking for it inside the pool instead.
    //
    // Not every pool has one — only those with a published Belegungsplan — so a missing chart
    // is a screenshot we skip, not a failure. The behaviour test already owns that assertion.
    let disclosure = find("laneDisclosure")
    if disclosure.waitForExistence(timeout: 10) {
      disclosure.tap()
      if find("laneChart").waitForExistence(timeout: 5) {
        capture("02-lanes")
      }
      disclosure.tap()
    }

    // 3 — the filters. This is where the women-only / age-limit story lives, which is the part
    // of this app a general "pools near me" listing does not get right.
    find("filterButton").tap()
    XCTAssertTrue(find("dayStrip").waitForExistence(timeout: 10), "the filters never opened")
    capture("03-filters")
    closeSheet()

    // 4 — one pool, opened. The BOTTOM of the row, because that is the gesture
    // `testTheWholeRowOpensThePool` pins; the name at the top was once the only part that
    // navigated, so tapping the middle would photograph a path a reader may not have.
    find("poolRow").coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)).tap()
    XCTAssertTrue(find("heroMap").waitForExistence(timeout: 15), "the pool never opened")
    capture("04-pool")
    closeSheet()

    // 5 — the map. Segment 1 by position, because a `Picker` gives its options no identifiers
    // and list-then-map is the order `BehaviourTests` pins as the contract.
    XCTAssertTrue(find("viewMode").waitForExistence(timeout: 10), "no view-mode control")
    app.segmentedControls.firstMatch.buttons.element(boundBy: 1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 15), "the map never appeared")
    capture("05-map")

    // 6 — a pin's card, the surface `Lab.glassCard` is about. The gesture is the one
    // `testTheMapDrawsTheAnswerAndOpensAPool` pins: a single pin raises a card, a group only
    // zooms. Whether a single pin is on screen at the opening zoom depends on the answer and on
    // where the pools overlap, so a map showing only groups is a shot we skip, not a failure —
    // the behaviour test already owns the assertion that a pin raises a card.
    let pin = find("mapPin")
    if pin.waitForExistence(timeout: 10) {
      pin.tap()
      if find("pinCard").waitForExistence(timeout: 5) {
        capture("06-map-card")
      }
    }
  }

  /// Leave whatever is on top, by its navigation bar's leading button.
  ///
  /// This is the gesture `testTheFilterButtonOpensASheetOnBothScreens` already uses, and it is
  /// here because the first draft swiped the sheet down instead: the drag did nothing, and the
  /// run failed with "never got back to the list" after photographing two screens. A dismissal
  /// the behaviour suite already proves is the one to copy.
  private func closeSheet() {
    let back = app.navigationBars.buttons.firstMatch
    XCTAssertTrue(back.waitForExistence(timeout: 10), "nothing on top has a way out")
    back.tap()
    XCTAssertTrue(find("poolRow").waitForExistence(timeout: 15), "never got back to the list")
  }
}
