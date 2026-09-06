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
    // EVERY TEST STARTS FROM THE STATION, and this is not tidiness — it is a defect two tests
    // found. `LocationSource.preferred` is persisted precisely so the reader's choice survives
    // a launch, which means it also survives from one test to the NEXT: once
    // `testMyLocationChangesWhatNearestMeans` had opted in, every later launch located itself
    // and re-sorted the list. That broke the lane-plan test (a different pool was first, and it
    // publishes no lane plan) and then the location test itself, whose "before" was already
    // measured from the phone so nothing could change.
    //
    // `UserDefaults`' argument domain wins on READ and is not written back, so this gives a
    // clean start WITHOUT a test hook in production code — and without blocking the one test
    // that then opts in through the UI, since that sets the value in memory.
    app.launchArguments += ["-\(locationPreferenceKey)", "NO"]
    app.launch()
    // The store is bundled, but the first answer is still a query: wait for a row rather than
    // racing it, or every test here fails on a fast machine for the wrong reason.
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 30), "the list never showed a pool row")
  }

  /// The defaults key `LocationSource` persists the reader's choice under. Spelled out here
  /// rather than imported: the UI test target links no app code, so this is the one place the
  /// two have to agree by hand, and `LocationSourceKeyTests` in the package asserts they do.
  private let locationPreferenceKey = "swimzh.useMyLocation"

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
  private var onTheFindScreen: XCUIElement { app.tabBars.firstMatch }

  /// The tabs of that bar. A `Tab` label is a sentence in the running language, so they are
  /// reached by position — and the ORDER is the contract: list first, map second.
  private func modeSegment(_ index: Int) -> XCUIElement {
    app.tabBars.firstMatch.buttons.element(boundBy: index)
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
    // the one place in this file where a label is the right query. Case-insensitively: the
    // toolbar's field said "close", the search tab's field says "Close".
    let close = app.buttons.matching(NSPredicate(format: "label ==[c] %@", "close")).firstMatch
    XCTAssertTrue(close.waitForExistence(timeout: 5), "search has no visible way out")
    close.tap()
    XCTAssertTrue(
      onTheFindScreen.waitForExistence(timeout: 8),
      "closing search did not give the tab bar back")
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

  func testSearchFromTheMapStaysOnTheMapAndSuggestsNames() {
    // The reader on the map who taps search wants to search THAT map, not be taken to the
    // list — and expects names to be offered as they type. Picking one completes the field
    // and the map shows that pool alone.
    modeSegment(1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 10), "no map to search")
    searchControl.tap()
    let field = app.searchFields.firstMatch
    XCTAssertTrue(field.waitForExistence(timeout: 5), "search opened no field over the map")
    field.typeText("Hallenbad")
    let suggestion = find("searchSuggestion")
    XCTAssertTrue(suggestion.waitForExistence(timeout: 5), "typing offered no pool name")
    let name = suggestion.label
    suggestion.tap()
    XCTAssertTrue(
      waitFor { field.value as? String == name }, "picking a suggestion did not complete it")
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 5), "search left the map")
    XCTAssertFalse(find("poolRow").exists, "search took the reader to the list")
  }

  // MARK: - The row

  func testFavouritingARowKeepsItWhereItIs() {
    // THE SWIPE THAT MADE A ROW VANISH. Marking a row rebuilt the list with that row sorted to
    // the front of its tier: it left the screen, and every row under it jumped up by its
    // height. Under `Lab.FavouriteMove.hold` (the default) the heart appears in place and the
    // order waits — it is applied when the reader comes back to the top of the list, which is
    // where the front of a tier is.
    let rows = all("poolRow")
    XCTAssertGreaterThan(rows.count, 2, "not enough rows on screen to hold one in place")
    let second = rows.element(boundBy: 1)
    let name = second.label
    second.swipeRight()
    let action = find("favouriteAction")
    XCTAssertTrue(action.waitForExistence(timeout: 5), "swiping a row offered no favourite")
    action.tap()
    // The row is still the second row: nothing moved.
    let held = expectation(
      for: NSPredicate { _, _ in rows.element(boundBy: 1).label == name }, evaluatedWith: nil)
    XCTAssertEqual(XCTWaiter().wait(for: [held], timeout: 5), .completed, "the row moved")
    // Leave the top and come back: the held order is applied now, on screen. The row is at
    // the front of its tier — which is the first row, or still the second when the second
    // row already led a tier of its own.
    app.swipeUp()
    app.swipeDown()
    app.swipeDown()
    let settled = expectation(
      for: NSPredicate { _, _ in
        rows.element(boundBy: 0).label == name || rows.element(boundBy: 1).label == name
      }, evaluatedWith: nil)
    XCTAssertEqual(XCTWaiter().wait(for: [settled], timeout: 8), .completed, "the row was lost")
    // Put it back, so the next launch's order is the one every other test assumes.
    let favourite = rows.element(boundBy: 0).label == name ? rows.element(boundBy: 0) : second
    favourite.swipeRight()
    XCTAssertTrue(action.waitForExistence(timeout: 5))
    action.tap()
  }

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
    // SAMPLED OVER TIME, not three times in the same instant. The first version of this ran
    // three back-to-back `exists` checks with nothing between them, which read the same moment
    // three times and could not have seen the thing the test is named for: a feedback loop
    // between the strip's height and the scroll inset reappears over hundreds of milliseconds,
    // not microseconds. `waitForExistence` inverts cleanly — it polls for two seconds and
    // returning true is the failure.
    XCTAssertFalse(
      find("dayStrip").waitForExistence(timeout: 2),
      "the strip came back on its own while the list sat still")
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

  func testTheDayStripSelectsADayUnderEveryEntryEffect() throws {
    // `Lab.stripEntry` defaults to one arrival effect, so every other test here drives that
    // one. This one relaunches with each of the others and proves a chip still selects under
    // it: a chip is a button, and the chosen one carries `.isSelected`.
    for entry in ["scroll", "none"] {
      try selectsADay(stripEntry: entry)
    }
  }

  func testTheFilterTabOpensTheFiltersToo() {
    // `Lab.filterPlace` defaults to the pill above the bar, which every other test drives.
    // Under `tab` the filters are the third tab, and the form must be the same one.
    app.terminate()
    relaunch(withLab: "lab.filterPlace", value: "tab")
    modeSegment(2).tap()
    XCTAssertTrue(
      find("measureFrom").waitForExistence(timeout: 5), "the filter tab shows no filter form")
    modeSegment(0).tap()
    XCTAssertTrue(find("poolRow").waitForExistence(timeout: 10), "no way back to the list")
  }

  /// Relaunch with one Lab key set — replacing, not appending, an earlier value of the same
  /// key, so a loop over values leaves exactly one on the line.
  private func relaunch(withLab key: String, value: String) {
    if let previous = app.launchArguments.firstIndex(of: "-" + key) {
      app.launchArguments.removeSubrange(previous...(previous + 1))
    }
    app.launchArguments += ["-" + key, value]
    app.launch()
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 30), "the list never showed a pool row")
  }

  private func selectsADay(stripEntry: String) throws {
    app.terminate()
    relaunch(withLab: "lab.stripEntry", value: stripEntry)

    let strip = find("dayStrip")
    XCTAssertTrue(strip.waitForExistence(timeout: 5), "the day strip is not on the find screen")
    // The chip AFTER the selected one, not the strip's second: the strip opens centred on the
    // selected day, so on a store older than a screen of days the first chips are scrolled off
    // to the left and cannot be hit. The neighbour of the selected chip is always on screen.
    let chips = strip.buttons
    XCTAssertGreaterThan(chips.count, 1, "the strip has fewer than two chips to choose between")
    let selectedIndex = (0..<chips.count).first { chips.element(boundBy: $0).isSelected }
    let current = try XCTUnwrap(selectedIndex, "no chip is selected on the find screen")
    XCTAssertLessThan(current + 1, chips.count, "the selected day is the last chip")
    let next = chips.element(boundBy: current + 1)
    XCTAssertFalse(next.isSelected, "the next chip is selected before anything was tapped")
    // BY THE LABEL READ OFF THE CHIP, not by index. The strip is a LAZY stack that scrolls to
    // centre the new selection, so after the tap a different set of chips is materialised and
    // `boundBy:` names a different day — a hierarchy dump showed the tapped day selected while
    // the index-based query said it was not. The label is whatever the running language
    // rendered, so this is still not a test that knows any sentence.
    let previousLabel = chips.element(boundBy: current).label
    let nextLabel = next.label
    next.tap()
    func chip(_ label: String) -> XCUIElement {
      strip.buttons.matching(NSPredicate(format: "label == %@", label)).firstMatch
    }
    XCTAssertTrue(
      waitFor { chip(nextLabel).isSelected }, "tapping the next chip did not select it")
    XCTAssertFalse(chip(previousLabel).isSelected, "the previous chip is still selected too")
  }

  // MARK: - The filter pill

  func testTheFilterPillOpensTheSheetFromTheListAndTheMap() {
    // The pill rides ABOVE the tab bar, on every tab: one tap to the same sheet from the list
    // and from the map, and Done gives the screen back.
    find("filterButton").tap()
    XCTAssertTrue(
      find("measureFrom").waitForExistence(timeout: 5),
      "the filter pill did not open the sheet on the list")
    app.navigationBars.buttons.firstMatch.tap()
    XCTAssertTrue(waitForDisappearance(of: find("measureFrom")), "Done did not close the sheet")

    modeSegment(1).tap()
    XCTAssertTrue(find("poolMap").waitForExistence(timeout: 10), "the map never appeared")
    find("filterButton").tap()
    XCTAssertTrue(
      find("measureFrom").waitForExistence(timeout: 5),
      "the filter pill did not open the sheet on the map")
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

  // MARK: - The pool screen: a map, with the facts in a panel

  func testThePoolScreenOpensOnTheMapWithTheFactsInAPanel() {
    // "When I click on a pool I'm shown a table." It was true — the screen opened on a `List`
    // whose first row was a label/value pair for the address. Then it opened on a picture of
    // the map over that list. It opens on the MAP now: full screen, the pool's facts in a
    // panel over it, and what you can DO about it reachable from the panel.
    find("poolRow").tap()
    XCTAssertTrue(
      find("poolStage").waitForExistence(timeout: 10),
      "the pool screen does not open on a map of the pool")
    let panel = find("poolPanel")
    XCTAssertTrue(panel.waitForExistence(timeout: 5), "the facts are not in a panel")
    XCTAssertGreaterThan(
      panel.frame.height, app.frame.height / 5, "the panel is too small to hold the facts")
    XCTAssertTrue(
      find("directionsButton").waitForExistence(timeout: 5),
      "the pool screen offers no way to get to the pool")
    // The recentre control is a BAR item: the system's glass, at the back button's height and
    // size, on the opposite side. Floated over the map it sat lower and larger than the back
    // button beside it, which is what the owner saw first.
    let recentre = find("poolStageRecentre")
    XCTAssertTrue(recentre.exists, "no way back to the pool once panned")
    // Its LEVEL is asserted, not its height: the element behind the identifier is the glyph's
    // button inside the bar item, and the glass capsule the system draws around it is the
    // back button's — the screenshot shows the two the same size, the tree does not.
    let back = app.navigationBars.firstMatch.buttons.firstMatch
    XCTAssertEqual(
      recentre.frame.midY, back.frame.midY, accuracy: 1,
      "the pin button is not at the back button's height")
    XCTAssertGreaterThan(recentre.frame.minX, back.frame.maxX, "the pin button is not opposite")
    recentre.tap()
    XCTAssertTrue(panel.exists, "recentring the map lost the panel")
  }

  func testThePoolScreenSaysItsNameOnceAtATime() {
    // The screen once opened with the pool's name in the navigation bar AND at `heroTitle`
    // six points under it — the same word twice. The panel says it now, and the bar over the
    // map says nothing: with the panel always present the name never scrolls away, so a bar
    // title would be the duplication back.
    find("poolRow").tap()
    XCTAssertTrue(find("poolPanel").waitForExistence(timeout: 10), "the pool screen never opened")

    let bar = app.navigationBars.firstMatch
    XCTAssertTrue(bar.waitForExistence(timeout: 5), "the pool screen has no navigation bar")
    // Queried by STATIC TEXT rather than by the bar's identifier: a `NavigationStack` names the
    // bar after its title, so `bar.identifier` reports the name even in the frame where nothing
    // is drawn. What the reader can actually see is the label.
    XCTAssertEqual(
      bar.staticTexts.count, 0,
      "the bar is stating the name while the panel is showing it — that is twice")
    // ...and the back button is still there and still works with the panel up, or the map is
    // a screen with no way out.
    let back = bar.buttons.firstMatch
    XCTAssertTrue(back.exists, "the map screen has no way back")
    back.tap()
    XCTAssertTrue(find("poolRow").waitForExistence(timeout: 10), "back did not return to the list")
  }

  func testSwipingFromTheLeadingEdgeGoesBack() {
    // The map takes every pan it is given, and with the map edge to edge that included the
    // system's swipe-back — the only way out was the button. `FacilitySheet.backSwipeEdge`
    // keeps a strip of the leading edge free of the map so the swipe works again.
    find("poolRow").tap()
    XCTAssertTrue(find("poolStage").waitForExistence(timeout: 10), "the pool screen never opened")
    let edge = app.coordinate(withNormalizedOffset: CGVector(dx: 0.005, dy: 0.4))
    edge.press(forDuration: 0.05, thenDragTo: edge.withOffset(CGVector(dx: 320, dy: 0)))
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 8), "a swipe from the leading edge did not go back")
  }

  func testDraggingTheDrawerAnywhereMovesItAndDoesNotLeaveTheScreen() {
    // THE GESTURE THE OWNER ASKED FOR, first half: a drag anywhere on the drawer — not only its
    // handle — moves the drawer between its sizes and stays on the pool screen. With the zoom
    // push this screen used to have, the same drag shrank the whole screen back toward the
    // list and hid the bar on the way.
    find("poolRow").tap()
    let panel = find("poolPanel")
    XCTAssertTrue(panel.waitForExistence(timeout: 10), "the pool screen never opened")
    let restingTop = panel.frame.minY
    // Up, from the middle of the drawer's body.
    let body = panel.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.6))
    body.press(
      forDuration: 0.05, thenDragTo: body.withOffset(CGVector(dx: 0, dy: -260)),
      withVelocity: .slow, thenHoldForDuration: 0.1)
    XCTAssertTrue(
      waitFor { panel.frame.minY < restingTop - 100 }, "the drawer did not rise when dragged")
    XCTAssertTrue(find("poolStage").exists, "dragging the drawer up left the pool screen")
    // ...and a LONG pull down from up there, on the header: all the way back to the smallest
    // size and no further — two pulls to leave, never one. (A 260-point pull was tried first
    // and stepped it down exactly one size, which is the rule working, not failing.)
    let raised = panel.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1))
    raised.press(
      forDuration: 0.05, thenDragTo: raised.withOffset(CGVector(dx: 0, dy: 600)),
      withVelocity: .slow, thenHoldForDuration: 0.1)
    XCTAssertTrue(
      waitFor { abs(panel.frame.minY - restingTop) < 20 },
      "the drawer did not come back down to its smallest size: rest \(restingTop), now "
        + "\(panel.frame.minY), on the pool screen: \(find("poolStage").exists)")
    XCTAssertTrue(find("poolStage").exists, "a moderate pull down left the pool screen")
    XCTAssertTrue(find("directionsButton").exists, "the drawer lost its actions on the way")
  }

  func testPullingTheDrawerPastItsSmallestSizeGoesBack() {
    // Second half: from its smallest size, pulling the drawer on down and letting go is the way
    // out — back to the list, the way a place card in Maps goes.
    find("poolRow").tap()
    let panel = find("poolPanel")
    XCTAssertTrue(panel.waitForExistence(timeout: 10), "the pool screen never opened")
    let grab = panel.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.3))
    grab.press(
      forDuration: 0.05, thenDragTo: grab.withOffset(CGVector(dx: 0, dy: 500)),
      withVelocity: .slow, thenHoldForDuration: 0.1)
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 8),
      "pulling the drawer past its smallest size did not go back to the list")
  }

  func testSwipingFromTheLeadingEdgeOverTheDrawerGoesBack() {
    // The edge swipe must work where the finger lands on the DRAWER too, not only on the map:
    // the drawer's own drag took those swipes until the edge strip was raised above it.
    find("poolRow").tap()
    XCTAssertTrue(find("poolPanel").waitForExistence(timeout: 10), "the pool screen never opened")
    let edge = app.coordinate(withNormalizedOffset: CGVector(dx: 0.005, dy: 0.85))
    edge.press(forDuration: 0.05, thenDragTo: edge.withOffset(CGVector(dx: 320, dy: 0)))
    XCTAssertTrue(
      find("poolRow").waitForExistence(timeout: 8),
      "a swipe from the leading edge over the drawer did not go back")
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

  // MARK: - The pool's own page

  func testTheWebsiteOpensInsideTheApp() {
    // The website action used to hand the address to Safari and put the app in the
    // background. Every opener that claims to keep the reader in the app must put a page on
    // screen with the app still in front. The Safari app itself (`external`) is not driven:
    // it would leave Safari open in front of every later test.
    for opener in ["safari", "sheet", "web"] {
      app.terminate()
      relaunch(withLab: "lab.linkOpener", value: opener)
      find("poolRow").tap()
      let website = find("websiteButton")
      XCTAssertTrue(website.waitForExistence(timeout: 10), "\(opener): no website action")
      website.tap()
      XCTAssertTrue(
        app.webViews.firstMatch.waitForExistence(timeout: 20),
        "\(opener): no page opened inside the app")
      XCTAssertEqual(app.state, .runningForeground, "\(opener): the app left the foreground")
      if opener == "web" {
        // The app's own browser has the app's own Done, and it must give the pool back.
        find("browserDone").tap()
        XCTAssertTrue(
          waitForDisappearance(of: app.webViews.firstMatch), "\(opener): Done left the page up")
        XCTAssertTrue(website.exists, "\(opener): Done did not return to the pool")
      }
    }
  }

  // MARK: - The phone's own position

  func testMyLocationChangesWhatNearestMeans() {
    // WHAT THIS ACTUALLY PROVES. Every distance in this app was measured from Zürich
    // Hauptbahnhof, because `Places.default` is the station and there was no other origin — so
    // "nearest first" meant nearest to the station, on a device that knows exactly where it is.
    //
    // THE WORLD IS SET UP FROM OUTSIDE, by `make ios-qa`:
    //
    //     xcrun simctl privacy booted grant location ch.swimzh.SwimZH
    //     xcrun simctl location booted set 47.3450,8.5340
    //
    // — permission granted, and the device placed at Wollishofen, about four kilometres south
    // of the station. It has to be outside because an XCUITest runs ON the simulator and cannot
    // shell out (`Process` is macOS-only), and because the permission alert belongs to
    // SpringBoard rather than to this app: tapping it is slow, famously flaky, and tests
    // whether iOS can draw its own dialog rather than what this app does with the answer.
    //
    // The position matters as much as the permission. Four kilometres is far enough that the
    // two orderings genuinely differ, so a run that changed nothing would prove nothing.
    //
    // THE REFUSAL PATH IS NOT DRIVEN HERE, deliberately rather than by omission. Its invariant —
    // that no state but a real fix may install a place — is `SwimZHKit.devicePlace`, and
    // `LocatedTests.nothingElseInstallsAPlace` walks EVERY state including all three refusals.
    // Reproducing that through a simulator would be the same assertion through a slower lens.
    // What only a driven app can show is the wiring, which is this: a real fix reaches
    // `filters.place` and the list re-sorts.
    let before = firstRowDistance()
    XCTAssertNotNil(before, "no row shows a distance — is a place selected at all?")

    find("filterButton").tap()
    let measureFrom = find("measureFrom")
    XCTAssertTrue(measureFrom.waitForExistence(timeout: 5), "the filter sheet has no place row")
    measureFrom.tap()
    let row = find("useMyLocation")
    XCTAssertTrue(row.waitForExistence(timeout: 5), "the place list offers no way to use it")
    row.tap()
    // The row deliberately does NOT dismiss the sheet — a fix takes a moment and can fail, and
    // the sheet is where the explanation would live. So the test closes it, as a reader would.
    XCTAssertTrue(
      waitFor { self.find("useMyLocation").isEnabled }, "the row never came out of `.locating`")
    // Back out of the place list, then out of the sheet.
    app.navigationBars.buttons.firstMatch.tap()
    app.navigationBars.buttons.firstMatch.tap()

    // The distances must have MOVED. Not to a particular number: the fixture store's pools and
    // the simulated position are both free to change, and a test pinned to "0.8 km" would fail
    // for a reason that has nothing to do with whether the phone's position is being used.
    XCTAssertTrue(
      waitFor { self.firstRowDistance() != before },
      "the list is still measured from Zürich HB — the phone's position is not being used")
  }

  /// Poll a condition until it holds. XCUITest's own `expectation(for:evaluatedWith:)` needs a
  /// KVO-observable object, and what is being waited for here is a rendered string.
  private func waitFor(_ condition: () -> Bool, seconds: Double = 15) -> Bool {
    let deadline = Date().addingTimeInterval(seconds)
    while Date() < deadline {
      if condition() { return true }
      Thread.sleep(forTimeInterval: 0.3)
    }
    return condition()
  }

  /// The first row's distance, as its rendered text. Read off the ROW rather than off an
  /// identifier of its own, because what is being asserted is what a reader can see.
  private func firstRowDistance() -> String? {
    let row = find("poolRow")
    guard row.waitForExistence(timeout: 15) else { return nil }
    return row.staticTexts.allElementsBoundByIndex.map(\.label).first { $0.contains("km") }
  }

  // MARK: - Helpers

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
