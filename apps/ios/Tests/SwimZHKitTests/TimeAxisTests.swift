// The three consumers of one time→x mapping, and the Canvas's hand-built accessibility
// (S3b acceptance 5, 6 and the assertable half of 7).
//
// None of this can be a view test: `Canvas` reports nothing about where it painted, exposes no
// accessibility for individual elements, and a SwiftUI body cannot be called headlessly at all.
// What CAN be tested is everything the view is a thin reader of — which is why the mapping, the
// VoiceOver layout, the hit test and the animation policy are all pure functions in the package
// rather than closures inside a `Canvas`.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Time axis, ribbon accessibility and hit testing")
struct TimeAxisTests {
  static let width = 320.0

  static func option(
    pool: String = "p",
    from: (Int, Int),
    to: (Int, Int),
    access: SessionAccess = .publicSwim,
    basin: String = "Hauptbecken",
    lane: LaneDay? = nil
  ) -> SwimOption {
    let window = TimeWindow(
      start: TimeOfDay(hour: from.0, minute: from.1),
      end: TimeOfDay(hour: to.0, minute: to.1))
    return SwimOption(
      poolID: pool, poolName: "Pool \(pool)", poolKind: "indoor", basinID: "\(pool)-b",
      basinName: basin, lengthM: 25, lanes: 6, window: window, access: access, weather: "any",
      eligibility: eligibility(Person(), access), openAtQueryTime: false, price: nil,
      distanceKm: nil,
      laneAvailability: lane?.availability(at: window.start),
      laneTimeline: lane?.availabilityTimeline(within: window),
      laneDayView: lane,
      laneBestPublic: lane?.bestPublicTime(within: window)
    )
  }

  static func row(_ options: [SwimOption], state: DayState? = nil) -> PoolRow {
    PoolRow(
      poolID: "p", poolName: "Pool p", poolKind: "indoor", distanceKm: nil,
      tier: state == nil ? .scheduled : .unknown, mark: .attend,
      verdict: Verdict(head: "Opens 06:00"), options: options, inlineOptions: options,
      hiddenSessionCount: 0, moreSessionsLabel: nil, state: state, isFavourite: false,
      openToYou: false)
  }

  // MARK: - Acceptance 6: one mapping

  @Test("the axis maps the window onto the plot, and inverts")
  func axisMapsAndInverts() {
    let axis = TimeAxis(width: Self.width)
    #expect(axis.x(of: TimeOfDay(hour: 6, minute: 0)) == 0)
    #expect(axis.x(of: TimeOfDay(hour: 22, minute: 30)) == Self.width)
    // Monotone, so a later time is never drawn to the left of an earlier one.
    #expect(axis.x(of: TimeOfDay(hour: 9, minute: 0)) < axis.x(of: TimeOfDay(hour: 9, minute: 1)))
    for hour in 6...22 {
      let time = TimeOfDay(hour: hour, minute: 0)
      #expect(axis.time(atX: axis.x(of: time)) == time, "\(hour)")
    }
  }

  @Test("a zero-width plot cannot divide by zero — a NaN x paints nothing, silently")
  func zeroWidthIsClamped() {
    let axis = TimeAxis(width: 0)
    #expect(axis.width == 1)
    #expect(axis.x(of: TimeOfDay(hour: 12, minute: 0)).isFinite)
    #expect(TimeAxis(width: -100).width == 1)
  }

  @Test("the hour marks and their labels position through the SAME mapping")
  func ticksAgreeWithTheAxis() {
    // The labels are SwiftUI text above the canvas and the marks are painted inside it. If the
    // two derived their own x, a label would sit over the wrong bar — which is the whole
    // failure `tickPercent` exists to prevent on the web.
    let axis = TimeAxis(width: Self.width)
    for hour in dayTailTickHours {
      #expect(abs(tickFraction(hour: hour) * Self.width - axis.x(ofMinutes: hour * 60)) < 1e-9)
    }
    // 06:00 is the plot's left EDGE: a rule there paints on the border and reads as a frame.
    #expect(!dayTailTickHours.contains(6))
    #expect(dayTailLabelHours.contains(6))
    #expect(dayTailTickHours == [9, 12, 15, 18, 21])
  }

  @Test("a tap at a block's midpoint selects that block, for every block of a fixture day")
  func tapAtMidpointSelectsItsBlock() throws {
    let day = dayRibbon(
      for: Self.row([
        Self.option(from: (6, 0), to: (8, 0)),
        Self.option(from: (8, 0), to: (12, 0), access: .laneSwim(note: "")),
        Self.option(from: (14, 30), to: (22, 0), access: .womenOnly(note: "")),
      ]))
    let blocks = a11yBlocks(for: day, width: Self.width)
    #expect(blocks.count == 3)
    for expected in blocks {
      let midpoint = expected.x + expected.width / 2
      let hit = try #require(block(at: midpoint, in: day, width: Self.width))
      #expect(hit == expected, "midpoint \(midpoint) selected \(hit.label)")
    }
    // In the 12:00-14:30 gap there is nothing to select, and nothing is invented.
    let axis = TimeAxis(width: Self.width)
    #expect(
      block(at: axis.x(of: TimeOfDay(hour: 13, minute: 0)), in: day, width: Self.width) == nil)
  }

  @Test("the same midpoint rule holds against the REAL store, not just a synthetic day")
  func tapAtMidpointOnARealDay() async throws {
    // A synthetic day is a day I chose to be easy. This one comes out of the committed export,
    // for the pool with the most sessions on the horizon's first day — overlapping basins
    // included, which is exactly where a 1-D hit test is at risk.
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    let answer = try await store.answer(
      onDay: metadata.horizonStart, at: TimeOfDay(hour: 12, minute: 0), for: Person())
    let model = listModel(
      answer: answer, filters: Filters(day: metadata.horizonStart), favourites: Favourites(),
      horizon: metadata, today: metadata.horizonStart, at: TimeOfDay(hour: 12, minute: 0))
    let rows = model.sections.flatMap(\.rows)
    #expect(rows.count > 10, "the store answered with almost nothing — is it empty?")
    var checked = 0
    for row in rows {
      let day = dayRibbon(for: row)
      let blocks = a11yBlocks(for: day, width: Self.width)
      // Two basins with identical hours are genuinely indistinguishable by x, and the tie rule
      // picks one of them — so only blocks whose (x, width) frame is UNIQUE within the row can
      // be held to identity. The previous version dodged that with `hit.width <= expected.width`
      // and `hit.x <= expected.x + expected.width`, which `block(at:)` satisfies by construction
      // (it returns the narrowest containing block, and a block contains its own midpoint): the
      // assertions could not fail, whatever the hit test did.
      var frames: [String: Int] = [:]
      for block in blocks { frames["\(block.x)|\(block.width)", default: 0] += 1 }
      for expected in blocks where frames["\(expected.x)|\(expected.width)"] == 1 {
        let hit = try #require(
          block(at: expected.x + expected.width / 2, in: day, width: Self.width))
        #expect(hit == expected, "\(row.poolName): \(hit.label) vs \(expected.label)")
        checked += 1
      }
    }
    // Counted over the UNIQUELY-FRAMED blocks only, so a store where every row collapsed into
    // ambiguous ties would fail here rather than pass with nothing checked.
    #expect(checked > 20, "only \(checked) unambiguous blocks — this proved almost nothing")
  }

  // MARK: - Acceptance 5: the Canvas's accessibility

  @Test("one accessibility element per painted session, positioned by the axis")
  func oneBlockPerSession() throws {
    let options = [
      Self.option(from: (6, 0), to: (8, 0)),
      Self.option(from: (9, 30), to: (12, 0), access: .clubReserved(club: "ASVZ")),
    ]
    let day = dayRibbon(for: Self.row(options))
    let blocks = a11yBlocks(for: day, width: Self.width)
    #expect(blocks.count == options.count)
    let axis = TimeAxis(width: Self.width)
    for (block, option) in zip(blocks, options) {
      #expect(block.x == axis.x(of: option.window.start))
      #expect(block.width == axis.width(of: option.window))
      #expect(block.label.contains(option.window.start.hhmm))
      #expect(block.label.contains(option.window.end.hhmm))
    }
    #expect(blocks[0].label.contains("Public swimming"))
    #expect(blocks[1].label.contains("Reserved for a club"))
    // Every element is distinct, or VoiceOver would collapse them into one.
    #expect(Set(blocks.map(\.id)).count == blocks.count)
  }

  @Test("a ghost or closed row still gets an element, spanning the whole plot")
  func stateRowsAreReadableToo() throws {
    for state in [DayState.noSource, .awaitingScrape, .closed(.outOfSeason)] {
      let day = dayRibbon(for: Self.row([], state: state))
      let blocks = a11yBlocks(for: day, width: Self.width)
      #expect(blocks.count == 1, "\(state)")
      // There is no narrower thing to point at: the state is about the whole day.
      #expect(blocks[0].x == 0)
      #expect(blocks[0].width == Self.width)
      #expect(blocks[0].label == dayStateLabel(state))
    }
  }

  @Test("the secondary facts carry the lane split, including `partial`")
  func customContentCarriesTheLaneFacts() throws {
    let lane = try #require(
      LaneDay.decode(
        basinID: "b", weekday: 1, laneCount: 4,
        strips: #"""
          [{"lane":1,"segments":[{"start":"06:00","end":"12:00","access":"PublicSwim","owner":null}]},
           {"lane":2,"segments":[{"start":"06:00","end":"12:00","access":"PublicSwim","owner":null}]},
           {"lane":3,"segments":[{"start":"06:00","end":"09:00","access":"ClubReserved","owner":"ASVZ"}]},
           {"lane":4,"segments":[]}]
          """#,
        unresolvedLanes: "[4]", confidence: "partial"))
    let option = Self.option(from: (6, 0), to: (12, 0), lane: lane)
    let day = dayRibbon(for: Self.row([option]))
    let blocks = a11yBlocks(for: day, width: Self.width)
    let facts = try #require(blocks.first).customContent
    let labels = facts.map(\.label)
    #expect(labels.contains("Basin"))
    #expect(labels.contains("Lanes"))
    #expect(labels.contains("Reserved by"))
    #expect(labels.contains("Most lanes free"))
    #expect(facts.first { $0.label == "Reserved by" }?.value == "ASVZ")
  }

  @Test("a pool with no published lane split says SO, and never `no lanes free`")
  func unpublishedSplitSaysSo() throws {
    let day = dayRibbon(for: Self.row([Self.option(from: (9, 0), to: (17, 0))]))
    let facts = try #require(a11yBlocks(for: day, width: Self.width).first).customContent
    #expect(facts.contains { $0.value.contains("not published") })
    #expect(!facts.contains { $0.label == "Lanes open to the public" })
  }

  @Test("every spoken label is DAY-AGNOSTIC — the ribbon is painted for any day in the horizon")
  func a11yLabelsAreDayAgnostic() {
    // The same bug class as `stateLabelsAreDayAgnostic`, one layer up: the day strip spans the
    // whole ~400-day horizon, so a sentence saying "today" or "now" is read out on ninety-odd
    // future dates. It has been found twice in this app already.
    let day = dayRibbon(
      for: Self.row([
        Self.option(from: (6, 0), to: (8, 0)),
        Self.option(from: (9, 0), to: (12, 0), access: .schoolReserved),
      ]))
    var spoken = a11yBlocks(for: day, width: Self.width).flatMap { block in
      [block.label] + block.customContent.flatMap { [$0.label, $0.value] }
    }
    for state in [DayState.noSource, .awaitingScrape, .closed(.noSessions), .beyondHorizon] {
      let stateDay = dayRibbon(for: Self.row([], state: state))
      spoken += a11yBlocks(for: stateDay, width: Self.width).map(\.label)
    }
    spoken += SessionAccess.allKinds.map { accessDescription($0) }
    // The expanded Gantt's per-mark labels belong to the same family: they are read out for
    // whichever date the strip has selected.
    let hold = LaneHold(
      window: TimeWindow(start: TimeOfDay(hour: 6, minute: 0), end: TimeOfDay(hour: 9, minute: 0)),
      accessKind: "ClubReserved", owner: "ASVZ")
    let publicHold = LaneHold(
      window: TimeWindow(start: TimeOfDay(hour: 9, minute: 0), end: TimeOfDay(hour: 12, minute: 0)),
      accessKind: publicSwimKind, owner: nil)
    spoken += [hold.spoken(lane: 3), publicHold.spoken(lane: 1)]
    for sentence in spoken {
      let said = sentence.lowercased()
      for temporal in ["today", "tonight", "right now", " now", "this morning", "tomorrow"] {
        #expect(!said.contains(temporal), "\"\(sentence)\" claims \"\(temporal)\"")
      }
    }
  }

  @Test("an access class this binary has never seen is never spoken as `open`")
  func unknownAccessIsSpokenHonestly() {
    // A store built by a newer export can carry an arm this binary does not know. The spoken
    // fallback matches `eligibility`'s: check with the pool, never a welcome.
    let said = accessDescription("SomethingNew").lowercased()
    #expect(said.contains("check with the pool"))
    #expect(!said.contains("open to all"))
  }

  // MARK: - The ribbon's geometry

  @Test("thickness and the pinch are two channels, and neither can vanish")
  func ribbonGeometryIsBounded() {
    let height = 46.0
    let full = ribbonHalfHeight(thickness: 1, pinched: false, height: height)
    #expect(full == sheathHalfHeight(height: height))
    // The pinch is a SECOND channel: same fraction, visibly thinner.
    #expect(ribbonHalfHeight(thickness: 1, pinched: true, height: height) < full)
    // A fully reserved band is still a line, never nothing — "no public lanes" must be
    // visible as a state rather than as an absence.
    #expect(ribbonHalfHeight(thickness: 0, pinched: false, height: height) == 1)
  }

  // MARK: - Acceptance 7: the animation policy

  @Test("the cursor pauses whenever the scene is not active, or motion is reduced")
  func animationPolicyAcrossEveryCombination() {
    // Driven across ALL combinations because whether `TimelineView` self-pauses off-screen or
    // in the background is UNDOCUMENTED. A CPU budget resting on undocumented behaviour is not
    // a budget, so the policy is explicit and this is the whole of it.
    //
    // The expectations are a TABLE, not the implementation's own expression restated in a loop
    // body — `paused == (phase != .active || reduceMotion)` would pass against any function
    // written the same way it is, including a wrong one, and the three literals below were
    // carrying the whole test on their own.
    let expected: [(phase: ScenePhaseKind, reduceMotion: Bool, paused: Bool)] = [
      (.active, false, false),
      (.active, true, true),
      (.inactive, false, true),
      (.inactive, true, true),
      (.background, false, true),
      (.background, true, true),
    ]
    // Every combination, exactly once: a phase added to the enum without a row here fails.
    #expect(expected.count == ScenePhaseKind.allCases.count * 2)
    #expect(Set(expected.map { "\($0.phase)|\($0.reduceMotion)" }).count == expected.count)
    for row in expected {
      #expect(
        animationPaused(scenePhase: row.phase, reduceMotion: row.reduceMotion) == row.paused,
        "\(row.phase) reduceMotion=\(row.reduceMotion)")
    }
    // Exactly one combination may animate at all — the CPU budget rests on that.
    #expect(expected.filter { !$0.paused }.count == 1)
  }
}

extension SessionAccess {
  /// Every access class name the export can write — the kinds `accessDescription` must answer
  /// for, plus one it cannot know.
  static var allKinds: [String] {
    accessFamilies.keys.sorted() + ["SomethingNew"]
  }
}
