// BehaviourTests.swift — the app, driven.
//
// WHY THIS TARGET EXISTS. Everything else that guards this UI reads the SOURCE: `UILintTests`
// proves a modifier is present, a screenshot proves a frame looks right. Neither can answer
// "what happens when you press it", and that gap shipped a real defect — `.searchToolbarBehavior
// (.minimize)` was present, asserted, and commented as putting search in the bottom bar, while
// the field actually collapsed into the NAVIGATION bar and opening it took that bar over, taking
// the browse menu with it. Every gate was green. The first person to press the button found it.
//
// So the rules here are behavioural, and each one names the mistake it would have caught:
//  * pressing search must not cost you the browse menu (the defect above),
//  * a row must open the pool from anywhere on it, not only on its name,
//  * the lane disclosure must expand and must NOT navigate — two controls in one row is exactly
//    where a `List` routes a tap to the wrong one,
//  * tapping the ribbon must put something on screen, because for two slices it did nothing.
//
// QUERIES ARE BY IDENTIFIER, NEVER BY LABEL. Every sentence in this app is one of five
// languages; a test that looked for "Browse" would pass in English and fail in four.

import XCTest

@MainActor
final class BehaviourTests: XCTestCase {
  private var app: XCUIApplication!

  override func setUp() async throws {
    continueAfterFailure = false
    app = XCUIApplication()
    app.launch()
    // The store is bundled, but the first answer is still a query: wait for a row rather than
    // racing it, or every test here fails on a fast machine for the wrong reason.
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 30), "the list never showed a pool row")
  }

  /// One element by identifier, whatever SwiftUI decided to call its type.
  ///
  /// `app.buttons["x"]` guesses the element TYPE, and SwiftUI's choice for the same view changes
  /// with the modifiers on it — a `NavigationLink` in a `List` has been a button, a cell and an
  /// "other" across releases. The identifier is the stable half.
  private func find(_ identifier: String) -> XCUIElement {
    app.descendants(matching: .any).matching(identifier: identifier).firstMatch
  }

  private func all(_ identifier: String) -> XCUIElementQuery {
    app.descendants(matching: .any).matching(identifier: identifier)
  }

  /// The landmark that says the find screen is what is on screen: its LIST/MAP control.
  ///
  /// It has been three things now — the browse menu in the navigation bar, then the all-pools
  /// button in the bottom bar, and now this. The all-pools link stopped working as a landmark
  /// the moment it moved into the list itself: a `List` is lazy, so an off-screen row is not in
  /// the hierarchy at all and `.exists` is false on a screen that is plainly showing. The mode
  /// picker is in the toolbar, which is always resident.
  private var onTheFindScreen: XCUIElement { find("viewMode") }

  /// The two segments of that picker. A `Picker` gives its options no identifiers of their own,
  /// so they are reached by position — and the ORDER is the contract: list first, map second.
  private func modeSegment(_ index: Int) -> XCUIElement {
    app.segmentedControls.firstMatch.buttons.element(boundBy: index)
  }

  /// The search control the system draws for us. It is NOT ours, so it has no identifier of
  /// ours — it is found by being the search field, or the button that becomes one.
  private var searchControl: XCUIElement {
    let field = app.searchFields.firstMatch
    if field.exists { return field }
    return app.buttons.matching(
      NSPredicate(format: "identifier == %@ OR label == %@", "Search", "Search")
    ).firstMatch
  }

  // MARK: - The defect a reader found and every gate missed

  func testSearchIsAWayInAndAWayOut() {
    // WHAT THIS TEST LEARNED, in three rewrites, and none of it was guessable from the source.
    //
    // It first demanded the browse menu SURVIVE opening search. It does not: iOS hides the
    // navigation bar for the duration of a search. It then demanded that scrolling, tapping the
    // day strip or clearing the field bring it back. None of them do — four gestures, and the
    // bar count stayed at zero. That looked like a one-way door, and the menu was very nearly
    // moved into the bottom bar to escape it. A SCREENSHOT is what settled it: the system draws
    // its own `close` button beside the field, and pressing that is the way out.
    //
    // So the contract is: search opens under the thumb, and closing it gives everything back.
    XCTAssertTrue(onTheFindScreen.exists, "the list/map control is not on the find screen")
    let control = searchControl
    XCTAssertTrue(control.waitForExistence(timeout: 5), "no search control on screen")
    control.tap()

    let field = app.searchFields.firstMatch
    XCTAssertTrue(field.waitForExistence(timeout: 5), "pressing search opened no search field")
    // The bottom bar, not the navigation bar. This is what the fix changed: the field used to
    // collapse into the top pill beside the browse menu.
    XCTAssertGreaterThan(
      field.frame.midY, app.frame.height / 2,
      "the search field opened in the top half — it is collapsing into the navigation bar again")

    // The system's own control, so it is found by ITS label rather than one of our catalog's —
    // the one place in this file where a label is the right query.
    let close = app.buttons.matching(NSPredicate(format: "label == %@", "close")).firstMatch
    XCTAssertTrue(close.waitForExistence(timeout: 5), "search has no visible way out")
    close.tap()
    XCTAssertTrue(
      onTheFindScreen.waitForExistence(timeout: 8),
      "closing search did not give the navigation bar back")
  }

  func testTypingInSearchNarrowsTheList() {
    let before = all("poolRow").count
    XCTAssertGreaterThan(before, 1, "one row cannot be narrowed")
    searchControl.tap()
    let field = app.searchFields.firstMatch
    XCTAssertTrue(field.waitForExistence(timeout: 5))
    field.typeText("Hallenbad City")
    // The list is re-queried, not the screen re-read: the rows are the behaviour.
    let narrowed = expectation(
      for: NSPredicate(format: "count < %d", before), evaluatedWith: all("poolRow"))
    XCTAssertEqual(
      XCTWaiter().wait(for: [narrowed], timeout: 10), .completed,
      "typing a pool's name did not narrow the list")
  }

  // MARK: - The row

  func testTheWholeRowOpensThePool() {
    let row = find("poolRow")
    // The BOTTOM of the row, deliberately: the pool's name is at the top, and until this pass
    // the name was the only part of the row that navigated at all.
    row.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)).tap()
    XCTAssertTrue(
      waitForDisappearance(of: onTheFindScreen),
      "tapping the body of a row did not open the pool")
  }

  func testTheLaneDisclosureExpandsAndDoesNotNavigate() {
    let disclosure = find("laneDisclosure")
    guard disclosure.waitForExistence(timeout: 10) else {
      return XCTFail("no row in the fixture store offers a lane plan")
    }
    disclosure.tap()
    // It must NOT have navigated. Two controls in one `List` row is exactly where a tap gets
    // routed to the wrong one, and the row's link covers most of the row.
    XCTAssertTrue(
      onTheFindScreen.exists, "the lane disclosure navigated instead of expanding")
    // ...and it must have expanded: the chart is the only thing it can produce.
    XCTAssertTrue(
      find("laneChart").waitForExistence(timeout: 5), "the lane plan did not appear")
  }

  func testTappingTheRibbonShowsTheBlockAndTappingItAgainHidesIt() {
    let ribbon = find("ribbon")
    XCTAssertTrue(ribbon.waitForExistence(timeout: 10), "no ribbon on the first row")
    XCTAssertFalse(find("blockCaption").exists, "a block caption before anything was tapped")

    ribbon.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    XCTAssertTrue(
      find("blockCaption").waitForExistence(timeout: 5),
      "tapping the ribbon put nothing on screen — the hit test is dead again")

    ribbon.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    XCTAssertTrue(
      waitForDisappearance(of: find("blockCaption")),
      "the same block twice did not put the caption away")
  }

  // MARK: - The day strip, and the day being said once

  func testTheDayStripYieldsToTheListAndComesBack() {
    let strip = find("dayStrip")
    XCTAssertTrue(strip.exists, "the day strip is not on the find screen")

    app.swipeUp()
    app.swipeUp()
    XCTAssertTrue(
      waitForDisappearance(of: find("dayStrip")),
      "scrolling down the list did not give the strip's height back to the rows")

    // ...and it comes back on the way up. Bounded, because "back at the top" is what returns it.
    var swipes = 0
    while !find("dayStrip").exists && swipes < 6 {
      app.swipeDown()
      swipes += 1
    }
    XCTAssertTrue(find("dayStrip").exists, "scrolling back up did not bring the day strip back")
  }

  func testTheStripDoesNotFlapWhileTheListIsStill() {
    // The band in `stripShouldShow`, seen from outside. The first version of that rule was a
    // DIRECTION rule, and hiding the strip moved the scroll by the strip's own height — which
    // re-triggered it, forever. From here that looked like swipes taking eighty seconds and an
    // app that never reported itself idle, so this test is also the timing guard: if the loop
    // ever comes back, these three swipes stop finishing in seconds.
    app.swipeUp()
    app.swipeUp()
    XCTAssertTrue(waitForDisappearance(of: find("dayStrip")), "the strip never yielded")
    let hidden = find("dayStrip")
    for _ in 0..<3 {
      XCTAssertFalse(hidden.exists, "the strip came back on its own while the list sat still")
    }
  }

  func testTheFindScreenSpendsNoRowOnChrome() {
    // Two rounds of the same lesson. FIRST the title went: the bar spelled the day out while
    // the strip underneath drew it, one fact twice, for a row of screen you cannot tap. That
    // left a whole navigation bar holding one overflow button — which is worse, because it
    // costs the same height and says nothing. Both are gone: no title, no bar, and the three
    // controls that were behind them are in the bottom bar, one tap each.
    XCTAssertEqual(
      app.navigationBars.count, 0,
      "the find screen has grown a navigation bar again — that is ~50 points of the list")
    XCTAssertTrue(onTheFindScreen.exists, "the list/map control is not on the find screen")
    XCTAssertTrue(find("dayStrip").exists, "the day strip is not on the find screen")
  }

  // MARK: - The two screens that filter

  func testTheFilterButtonOpensASheetOnBothScreens() {
    find("filterButton").tap()
    XCTAssertTrue(
      app.navigationBars.buttons.firstMatch.waitForExistence(timeout: 5),
      "the filter sheet did not open on the find screen")
    app.navigationBars.buttons.firstMatch.tap()

    openAllPools()
    // The BROWSER's own row first. This assertion used to be the filter button alone — which
    // exists on both screens, so the test went on passing for a whole run in which
    // `openAllPools` was tapping the glass bar and never leaving the find screen. An assertion
    // that cannot tell the two screens apart is not testing the sentence it claims to.
    XCTAssertTrue(
      find("browserRow").waitForExistence(timeout: 10), "the browser never opened")
    XCTAssertTrue(
      find("filterButton").waitForExistence(timeout: 5),
      "the all-pools browser has no filter button in the same place")
  }

  func testTheBrowserOpensAPoolToo() {
    openAllPools()
    let row = find("browserRow")
    if !row.waitForExistence(timeout: 10) {
      print(
        "DBG navbars=\(app.navigationBars.count) titles=\(app.navigationBars.allElementsBoundByIndex.map(\.identifier)) cells=\(app.cells.count) rows=\(all("poolRow").count) link=\(find("allPoolsLink").exists)"
      )
    }
    XCTAssertTrue(row.waitForExistence(timeout: 10), "the browser listed nothing")
    row.tap()
    XCTAssertTrue(
      waitForDisappearance(of: find("browserRow")),
      "a browser row did not push the pool's sheet")
  }

  func testTheColourLegendIsReachableFromTheList() {
    // It is the last row of the list, so it has to be scrolled to — which is the point: it used
    // to be two taps deep inside the overflow menu instead.
    XCTAssertTrue(
      scrollTo(find("legendLink")), "the colour legend is not reachable from the find screen")
  }

  // MARK: - The map: the SAME answer, drawn differently

  func testTheMapDrawsTheAnswerAndOpensAPool() {
    // The complaint this answers was "I can't switch views nicely, ie list, map". The contract
    // is that switching is a MODE, not a journey: one tap out, one tap back, no push, and the
    // day strip still there because the day is still the question.
    modeSegment(1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 10), "the map mode drew no map")
    XCTAssertTrue(find("dayStrip").exists, "switching to the map took the day picker away")

    let pin = find("mapPin")
    XCTAssertTrue(pin.waitForExistence(timeout: 10), "the map has no pins — the answer is empty")
    pin.tap()
    // A card, not a push. Tapping a pin that navigated would make the map a menu: you would
    // have to leave it to learn anything about a pool and come back to try the next one.
    let card = find("pinCard")
    XCTAssertTrue(card.waitForExistence(timeout: 5), "tapping a pin raised no card")
    card.tap()
    XCTAssertTrue(
      waitForDisappearance(of: find("poolMap")), "the card did not open the pool")
  }

  func testTheMapGroupsPinsAndTappingAGroupPullsItApart() {
    // Fifty-seven pins framed on Zürich put roughly forty of them inside the middle third of
    // the screen — the first version was one brown mass you could not read and could not
    // reliably tap. The contract is that the map opens GROUPED, and that tapping a group is a
    // way IN to the pools inside it rather than a dead end.
    modeSegment(1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 10), "the map mode drew no map")

    let group = find("mapCluster")
    XCTAssertTrue(
      group.waitForExistence(timeout: 10),
      "the whole city fits on one screen with no pin overlapping another — clustering is off")

    group.tap()
    // A group must NOT raise a card: the reader asked what is at that place, and the answer is
    // the map showing them, not a menu covering it.
    XCTAssertFalse(find("pinCard").waitForExistence(timeout: 2), "a group raised a card")

    // WHAT "CAME APART" MEANS, and the first version of this assertion had it wrong. It counted
    // single pins and demanded MORE of them afterwards — but expanding zooms into about a city
    // block, so all but the group's own members leave the screen and the count legitimately
    // falls. (A probe confirmed the app was right and the test was not: 33 groups at 27 m per
    // point became 56 marks at 1 m per point.) The honest claim is the one the reader cares
    // about: a pool that was buried in the group is now a pin of its own, and tapping it works.
    let pin = find("mapPin")
    XCTAssertTrue(
      pin.waitForExistence(timeout: 10), "tapping a group left no single pin — it is a dead end")
    pin.tap()
    XCTAssertTrue(
      find("pinCard").waitForExistence(timeout: 5),
      "a pin freed from a group does not raise its card")
  }

  func testTheModeSwitchGoesBothWays() {
    modeSegment(1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 10), "no map after switching to it")
    modeSegment(0).tap()
    XCTAssertTrue(find("poolRow").waitForExistence(timeout: 10), "no way back to the list")
    XCTAssertTrue(waitForDisappearance(of: find("poolMap")), "the map stayed under the list")
  }

  // MARK: - The pool screen: not a table

  func testThePoolScreenOpensOnThePoolAndNotOnATable() {
    // "When I click on a pool I'm shown a table." It was true — the screen opened on a `List`
    // whose first row was a label/value pair for the address. It opens on the pool now: where
    // it is, what it is called, what the answer was, and what you can DO about it.
    find("poolRow").tap()
    XCTAssertTrue(
      find("heroMap").waitForExistence(timeout: 10),
      "the pool screen does not open on a map of the pool")
    XCTAssertTrue(
      find("directionsButton").exists,
      "the pool screen offers no way to get to the pool")
  }

  func testThePoolScreenActionsAreRealControls() {
    find("poolRow").tap()
    let directions = find("directionsButton")
    XCTAssertTrue(directions.waitForExistence(timeout: 10), "no directions action")
    // The HIG's 44 points, measured rather than asserted in a comment. A round glyph that looks
    // pressable and is 20 points across is the defect this app has already shipped once.
    XCTAssertGreaterThanOrEqual(directions.frame.height, 44, "the action is too small to hit")
    XCTAssertGreaterThanOrEqual(directions.frame.width, 44, "the action is too small to hit")
  }

  // MARK: - Helpers

  /// The whole roster. Its link is the second-to-last row of the list now — beside the colour
  /// legend, both of them reference rather than answer — so getting there is a scroll.
  ///
  /// IT SCROLLS PAST THE LINK, to the legend row BELOW it, and that is not belt-and-braces. The
  /// first version stopped the moment `allPoolsLink` entered the hierarchy — which is the exact
  /// frame it appears at the very bottom edge, under the floating bottom bar — so the tap
  /// landed on the glass and the test failed with the browser never having opened. Scrolling to
  /// the LAST row instead puts the one above it comfortably clear. The app is fine here: a real
  /// list has a bottom inset for the toolbar and a human keeps scrolling.
  private func openAllPools() {
    find("allPoolsLink").tap()
  }

  /// Swipe until the element is in the hierarchy, or give up. A lazy `List` does not build a
  /// row it is not showing, so "scroll to it" is the only way to assert anything about one.
  @discardableResult
  private func scrollTo(_ element: XCUIElement, limit: Int = 25) -> Bool {
    var swipes = 0
    while !element.exists && swipes < limit {
      app.swipeUp()
      swipes += 1
    }
    return element.exists
  }

  private func waitForDisappearance(of element: XCUIElement) -> Bool {
    let gone = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: element)
    return XCTWaiter().wait(for: [gone], timeout: 8) == .completed
  }
}
