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
// TWO DEVICE FAMILIES, ONE WALK. Since the target declares iPad (TARGETED_DEVICE_FAMILY 1,2, for
// the unfolded-phone layout) App Store Connect refuses a submission without a 12.9"/13" iPad set
// as well — the v0.2.0 release of 2026-09-17 uploaded its build and then died on exactly that.
// On a wide window the app has no tab bar: the map IS the screen, the list floats over it, the
// filters are pulled for and open as a popover, and a pool takes the card while the same map
// flies to it. So the walk forks on the size class after the two shots both layouts share,
// driving the wide half with the gestures `BehaviourTests`' wide-window tests already pin.
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

  /// The same rule `BehaviourTests` uses: regular width is the wide layout, whatever the idiom.
  private var windowIsWide: Bool { app.windows.firstMatch.frame.width >= 600 }

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

    if windowIsWide {
      try walkWide(capture: capture)
      return
    }

    // 3 — the filters. This is where the women-only / age-limit story lives, which is the part
    // of this app a general "pools near me" listing does not get right.
    app.tabBars.firstMatch.buttons.element(boundBy: 2).tap()
    XCTAssertTrue(find("measureFrom").waitForExistence(timeout: 10), "the filters never opened")
    capture("03-filters")
    app.tabBars.firstMatch.buttons.element(boundBy: 0).tap()

    // 4 — one pool, opened. The BOTTOM of the row, because that is the gesture
    // `testTheWholeRowOpensThePool` pins; the name at the top was once the only part that
    // navigated, so tapping the middle would photograph a path a reader may not have.
    find("poolRow").coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)).tap()
    XCTAssertTrue(find("poolStage").waitForExistence(timeout: 15), "the pool never opened")
    // Let the map's tiles and the panel settle before the frame is taken.
    _ = find("poolPanel").waitForExistence(timeout: 5)
    sleep(2)
    capture("04-pool")

    closeSheet()

    // 5 — the map. The tab bar's second tab, by position: list-then-map is the order
    // `BehaviourTests` pins as the contract.
    XCTAssertTrue(app.tabBars.firstMatch.waitForExistence(timeout: 10), "no tab bar")
    app.tabBars.firstMatch.buttons.element(boundBy: 1).tap()
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

  /// The wide window's half of the set, after the two shots both layouts share.
  ///
  /// Four shots, not six: on the stage the map is already in `01-find`, and a pin opens the pool
  /// in the SAME card `04-pool` shows (`testAWideWindowIsAMapWithTheListFloatingOverIt…` pins
  /// that there is no phone-style pin card here), so `05-map` and `06-map-card` would be two
  /// more photographs of screens already in the set.
  private func walkWide(capture: (String) -> Void) throws {
    // 3 — the filters: pulled for (the control row is not resident on the stage), then a
    // popover, closed by a tap outside it. Both gestures are the behaviour test's.
    let rowTop = find("poolRow").coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2))
    rowTop.press(forDuration: 0.1, thenDragTo: rowTop.withOffset(CGVector(dx: 0, dy: 300)))
    let filters = find("filtersButton")
    XCTAssertTrue(filters.waitForExistence(timeout: 5), "the pull brought no filters button")
    filters.tap()
    XCTAssertTrue(find("measureFrom").waitForExistence(timeout: 5), "the filters did not open")
    capture("03-filters")
    app.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.9)).tap()

    // 4 — one pool, in the card, with the map flown to it. The row, not the map: a pin is the
    // same destination and the row is the gesture the compact walk photographs too.
    let row = find("poolRow")
    XCTAssertTrue(row.waitForExistence(timeout: 10), "the list did not come back")
    row.tap()
    XCTAssertTrue(
      find("poolFacts").waitForExistence(timeout: 10), "the facts did not open in the card")
    // Let the fly-in and the tiles settle before the frame is taken.
    sleep(3)
    capture("04-pool")
  }

  /// Leave whatever is on top, by its navigation bar's leading button.
  ///
  /// This is the gesture `BehaviourTests` already uses to leave a pushed screen, and it is
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
