// The three consumers of one time→x mapping, and the Canvas's hand-built accessibility
// (S3b acceptance 5, 6 and the assertable half of 7).
//
// None of this can be a view test: `Canvas` reports nothing about where it painted, exposes no
// accessibility for individual elements, and a SwiftUI body cannot be called headlessly at all.
// What CAN be tested is everything the view is a thin reader of — which is why the mapping, the
// VoiceOver layout, the hit test and the animation policy are all pure functions in the package
// rather than closures inside a `Canvas`.
//
// Since S4 every spoken sentence here is a `Message`, so the assertions render one through a
// real compiled catalog (`CatalogFixture`) rather than reading English off the function. The
// ones about a RULE — "no spoken label claims a moment" — run over all five languages, because
// a translation is exactly where that rule is now easiest to break.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Time axis, ribbon accessibility and hit testing")
struct TimeAxisTests {
  static let width = 320.0

  /// The English renderer. Assertions about a SENTENCE read best in one language; the ones
  /// about the RULE loop over `CatalogFixture.all` instead.
  static let en = CatalogFixture.english

  /// Words that would turn a horizon-wide spoken label into a claim about one moment, per
  /// language. The same lists `DayStateTests.temporalWords` uses, plus "tomorrow": a ribbon is
  /// painted for whichever day the strip has selected, so a relative day word is wrong on every
  /// other date the strip can reach.
  static let temporalWords: [Language: [String]] = [
    .en: ["today", "tonight", "right now", " now", "this morning", "tomorrow"],
    .de: ["heute", "jetzt", "heute abend", "morgen"],
    .fr: ["aujourd", "maintenant", "ce soir", "demain"],
    .it: ["oggi", "adesso", "stasera", "domani"],
    .pl: ["dzisiaj", "dzis", "teraz", "wieczorem", "jutro"],
  ]

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
      verdict: Verdict(head: Message("mobile.verdict.opensAt", ["hhmm": "06:00"])),
      options: options, inlineOptions: options,
      hiddenSessionCount: 0, moreSessionsLabel: nil, state: state, isFavourite: false,
      nextOpenToYou: nil, openToYou: false)
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
    let blocks = a11yBlocks(for: day, width: Self.width, in: Self.en)
    #expect(blocks.count == 3)
    for expected in blocks {
      let midpoint = expected.x + expected.width / 2
      let hit = try #require(
        block(at: midpoint, in: day, width: Self.width, localized: Self.en))
      #expect(hit == expected, "midpoint \(midpoint) selected \(Self.en(hit.label))")
    }
    // In the 12:00-14:30 gap there is nothing to select, and nothing is invented.
    let axis = TimeAxis(width: Self.width)
    #expect(
      block(
        at: axis.x(of: TimeOfDay(hour: 13, minute: 0)), in: day, width: Self.width,
        localized: Self.en) == nil)
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
      horizon: metadata, today: metadata.horizonStart, at: TimeOfDay(hour: 12, minute: 0),
      format: Self.en.format)
    let rows = model.sections.flatMap(\.rows)
    #expect(rows.count > 10, "the store answered with almost nothing — is it empty?")
    var checked = 0
    for row in rows {
      let day = dayRibbon(for: row)
      let blocks = a11yBlocks(for: day, width: Self.width, in: Self.en)
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
          block(
            at: expected.x + expected.width / 2, in: day, width: Self.width, localized: Self.en))
        #expect(
          hit == expected, "\(row.poolName): \(Self.en(hit.label)) vs \(Self.en(expected.label))")
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
    let blocks = a11yBlocks(for: day, width: Self.width, in: Self.en)
    #expect(blocks.count == options.count)
    let axis = TimeAxis(width: Self.width)
    for (block, option) in zip(blocks, options) {
      #expect(block.x == axis.x(of: option.window.start))
      #expect(block.width == axis.width(of: option.window))
      // The times ride through the message as parameters, so the SENTENCE must still carry
      // them: a catalog entry that dropped a specifier would leave the block spoken as a bare
      // access class with no hours at all.
      #expect(Self.en(block.label).contains(option.window.start.hhmm))
      #expect(Self.en(block.label).contains(option.window.end.hhmm))
    }
    #expect(Self.en(blocks[0].label).contains("Public swim"))
    #expect(Self.en(blocks[1].label).contains("Club reserved"))
    // Every element is distinct, or VoiceOver would collapse them into one.
    #expect(Set(blocks.map(\.id)).count == blocks.count)
    // And distinct in every language: two sessions that collapse to one German sentence are
    // one element to a German VoiceOver user, whatever their ids say.
    for (language, localized) in CatalogFixture.all {
      let spoken = a11yBlocks(for: day, width: Self.width, in: localized)
        .map { localized($0.label) }
      #expect(Set(spoken).count == spoken.count, "\(language): two blocks share a sentence")
    }
  }

  @Test("a ghost or closed row still gets an element, spanning the whole plot")
  func stateRowsAreReadableToo() throws {
    for state in [DayState.noSource, .awaitingScrape, .closed(.outOfSeason)] {
      let day = dayRibbon(for: Self.row([], state: state))
      let blocks = a11yBlocks(for: day, width: Self.width, in: Self.en)
      #expect(blocks.count == 1, "\(state)")
      // There is no narrower thing to point at: the state is about the whole day.
      #expect(blocks[0].x == 0)
      #expect(blocks[0].width == Self.width)
      // The KEY AND ITS PARAMS, not a rendering: the state's message must survive the trip
      // through `RibbonStatusInput` intact, or the canvas and VoiceOver would say different
      // things about one row. `DayStateTests` is what pins the sentence each key renders to.
      #expect(blocks[0].label == dayStateLabel(state))
      #expect(Self.en(blocks[0].label) == Self.en(dayStateLabel(state)))
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
    let blocks = a11yBlocks(for: day, width: Self.width, in: Self.en)
    let facts = try #require(blocks.first).customContent
    let labels = facts.map { Self.en($0.label) }
    #expect(labels.contains("Basin"))
    #expect(labels.contains("Lanes"))
    #expect(labels.contains("Reserved by"))
    #expect(labels.contains("Most public lanes free"))
    // The club's name is the SOURCE's word and rides through verbatim — a translated "ASVZ"
    // would be an invented fact.
    let reserved = try #require(facts.first { Self.en($0.label) == "Reserved by" })
    #expect(reserved.value == .verbatim("ASVZ"))
    for (language, localized) in CatalogFixture.all {
      #expect(localized(reserved.value) == "ASVZ", "\(language) translated a club's name")
    }
  }

  @Test("a pool with no published lane split says SO, and never `no lanes free`")
  func unpublishedSplitSaysSo() throws {
    let day = dayRibbon(for: Self.row([Self.option(from: (9, 0), to: (17, 0))]))
    let facts = try #require(a11yBlocks(for: day, width: Self.width, in: Self.en).first)
      .customContent
    #expect(facts.contains { Self.en($0.value).contains("not published") })
    #expect(!facts.contains { Self.en($0.label) == "Lanes open to the public" })
    // The rule, in every language: an unpublished split is never reported as a lane COUNT.
    // The fact is the `laneSplit` one, and no `publicLanes` fact exists at all — asserted
    // structurally, because "0" is not a word a translation can be searched for.
    for (language, localized) in CatalogFixture.all {
      let spoken = a11yBlocks(for: day, width: Self.width, in: localized).flatMap(\.customContent)
      #expect(
        !spoken.contains { $0.label == Message("a11y.fact.publicLanes") },
        "\(language): an unpublished split was counted")
      let split = try #require(spoken.first { $0.label == Message("a11y.fact.laneSplit") })
      let said = localized(split.value)
      #expect(!said.isEmpty && said != "a11y.value.laneSplitUnpublished", "\(language)")
    }
  }

  @Test("every spoken label is DAY-AGNOSTIC — IN ALL FIVE LANGUAGES")
  func a11yLabelsAreDayAgnostic() throws {
    // The same bug class as `stateLabelsAreDayAgnostic`, one layer up: the day strip spans the
    // whole ~400-day horizon, so a sentence saying "today" or "now" is read out on ninety-odd
    // future dates. It has been found twice in this app already.
    //
    // Five languages, for the reason `DayStateTests` gives: the English was written by whoever
    // wrote this rule and the translations were not. "Heute geschlossen" and "aujourd'hui" are
    // the natural phrasings a translator reaches for, and an English-only assertion could never
    // see either.
    //
    // The third option carries a PARTIAL lane plan, so the lane facts — the split, the club
    // name, the "most lanes free" window, the incomplete caveat — are scanned too. Without one
    // the collection is only headlines and access classes, and half the spoken vocabulary
    // would sit outside the rule.
    let lane = try #require(
      LaneDay.decode(
        basinID: "b", weekday: 1, laneCount: 4,
        strips: #"""
          [{"lane":1,"segments":[{"start":"14:00","end":"18:00","access":"PublicSwim","owner":null}]},
           {"lane":2,"segments":[{"start":"14:00","end":"16:00","access":"ClubReserved","owner":"SC Zürich"}]},
           {"lane":3,"segments":[{"start":"14:00","end":"18:00","access":"ClubReserved","owner":"ASVZ"}]},
           {"lane":4,"segments":[]}]
          """#,
        unresolvedLanes: "[4]", confidence: "partial"))
    let day = dayRibbon(
      for: Self.row([
        Self.option(from: (6, 0), to: (8, 0)),
        Self.option(from: (9, 0), to: (12, 0), access: .schoolReserved),
        Self.option(from: (14, 0), to: (18, 0), lane: lane),
      ]))
    let states: [DayState] = [.noSource, .awaitingScrape, .closed(.noSessions), .beyondHorizon]
    // The expanded Gantt's per-mark labels belong to the same family: they are read out for
    // whichever date the strip has selected.
    let hold = LaneHold(
      window: TimeWindow(start: TimeOfDay(hour: 6, minute: 0), end: TimeOfDay(hour: 9, minute: 0)),
      accessKind: "ClubReserved", owner: "ASVZ")
    let publicHold = LaneHold(
      window: TimeWindow(start: TimeOfDay(hour: 9, minute: 0), end: TimeOfDay(hour: 12, minute: 0)),
      accessKind: publicSwimKind, owner: nil)

    for (language, localized) in CatalogFixture.all {
      let temporal = Self.temporalWords[language] ?? []
      #expect(!temporal.isEmpty, "no temporal-word list for \(language)")
      var spoken = a11yBlocks(for: day, width: Self.width, in: localized).flatMap { block in
        [localized(block.label)]
          + block.customContent.flatMap { [localized($0.label), localized($0.value)] }
      }
      for state in states {
        let stateDay = dayRibbon(for: Self.row([], state: state))
        spoken += a11yBlocks(for: stateDay, width: Self.width, in: localized).map {
          localized($0.label)
        }
      }
      spoken += SessionAccess.allKinds.map { localized(accessDescription($0)) }
      spoken += [
        localized(hold.spoken(lane: 3, in: localized)),
        localized(publicHold.spoken(lane: 1, in: localized)),
      ]
      // ...and it really rendered something, so a loop over an empty catalog cannot pass by
      // reading nothing.
      #expect(spoken.count > 15, "\(language): only \(spoken.count) sentences collected")
      for sentence in spoken {
        let said = sentence.folding(
          options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        for word in temporal {
          #expect(!said.contains(word), "\(language): \"\(sentence)\" claims \"\(word)\"")
        }
      }
    }
  }

  @Test("an access class this binary has never seen is never spoken as `open`")
  func unknownAccessIsSpokenHonestly() {
    // A store built by a newer export can carry an arm this binary does not know. The spoken
    // fallback matches `eligibility`'s: check with the pool, never a welcome.
    let said = Self.en(accessDescription("SomethingNew")).lowercased()
    #expect(said.contains("check with the pool"))
    #expect(!said.contains("open to all"))
    // The welcome-by-default failure is now one catalog edit away in four languages nobody on
    // this team reads, so the rule is checked in all five: the unknown arm has its own
    // translated sentence, and it is never the public-swim one.
    for (language, localized) in CatalogFixture.all {
      let unknown = accessDescription("SomethingNew")
      let rendered = localized(unknown)
      #expect(rendered != unknown.key, "\(language) has no translation for \(unknown.key)")
      #expect(
        rendered != localized(accessDescription("PublicSwim")),
        "\(language) welcomes an unknown access class in")
    }
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
