// The glance strip's rules — which number, from where, called what. See `Glance.swift`.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Glance: the three numbers under the pool's name")
struct GlanceTests {
  static let en = CatalogFixture.english
  static let now = Date(timeIntervalSince1970: 1_756_000_000)

  static func basin(
    _ id: String, length: Double? = nil, lanes: Int? = nil, nominal: Double? = nil,
    measured: Double? = nil, plan: String? = nil
  ) -> BasinDetail {
    BasinDetail(
      basinID: id, name: "Becken \(id)", kind: "swimmer", lengthM: length, widthM: nil,
      lanes: lanes, nominalTempC: nominal, measuredTempC: measured, divingPlatformsM: [],
      physicalSource: "curated", lanePlanURL: plan)
  }

  static func facts(
    _ basins: [BasinDetail], live: LiveTemp? = nil, panels: [LanePanel] = []
  ) -> [GlanceFact] {
    glanceFacts(
      FacilityDetailTests.detail(basins: basins, panels: panels), live: live, at: now, in: en)
  }

  static func said(_ facts: [GlanceFact], _ id: String) -> (value: String, caption: String)? {
    facts.first { $0.id == id }.map { (en($0.phrase), en($0.caption)) }
  }

  /// The phrase and its caption as one string, so a whole item can be asserted in one line.
  static func tile(_ facts: [GlanceFact], _ id: String) -> String? {
    said(facts, id).map { "\($0.value) / \($0.caption)" }
  }

  /// A temperature exactly as `Format` writes it — the spacing before the unit is the locale's
  /// business (`FormatTests`), not this suite's.
  static func degrees(_ celsius: Double) -> String { en.format.temperature(celsius: celsius) }

  @Test("a pool that publishes none of the three gets NO tiles, never blanks")
  func nothingPublishedIsNothingShown() {
    #expect(Self.facts([Self.basin("a")]).isEmpty)
    #expect(Self.facts([]).isEmpty)
  }

  @Test("water, length, lanes — in that order, from the basins")
  func orderAndSource() {
    let facts = Self.facts([Self.basin("a", length: 50, lanes: 6, nominal: 28)])
    #expect(facts.map(\.id) == ["water", "length", "lanes"])
    #expect(Self.said(facts, "water")?.value == Self.degrees(28))
    #expect(Self.said(facts, "length")?.value == "50 m")
    #expect(Self.said(facts, "lanes")?.value == "6 lanes")
    // The one-line rendering needs the noun; the tile's caption already has it.
    #expect(Self.en(facts[2].phrase) == "6 lanes")
    #expect(Self.en(facts[1].phrase) == "50 m")
  }

  @Test("length and lanes come from the LONGEST basin, not the first")
  func longestBasinWins() {
    let facts = Self.facts([
      Self.basin("paddle", length: 12, lanes: 2), Self.basin("lap", length: 25, lanes: 5),
    ])
    #expect(Self.said(facts, "length")?.value == "25 m")
    #expect(Self.said(facts, "lanes")?.value == "5 lanes")
  }

  @Test("a nominal temperature says it is the pool's statement, a measured one does not")
  func nominalIsCaptionedHonestly() {
    let nominal = Self.facts([Self.basin("a", nominal: 27)])
    #expect(Self.said(nominal, "water")?.caption == "Water, as stated")
    let measured = Self.facts([Self.basin("a", nominal: 27, measured: 26.5)])
    #expect(Self.tile(measured, "water") == "\(Self.degrees(26.5)) / Water")
  }

  @Test("a live reading beats the published number and is captioned live")
  func liveReadingWins() {
    let live = LiveTemp.reading(
      TempReading(measuredAt: Self.now.addingTimeInterval(-600), celsius: 24.5, isOpen: true))
    let facts = Self.facts([Self.basin("a", nominal: 28)], live: live)
    #expect(Self.tile(facts, "water") == "\(Self.degrees(24.5)) / Live water")
    #expect(facts[0].muted == false)
  }

  @Test("a stale live reading is still shown, muted, and called earlier")
  func staleReadingIsMuted() {
    let live = LiveTemp.reading(
      TempReading(
        measuredAt: Self.now.addingTimeInterval(-9 * 3600), celsius: 24.5, isOpen: true))
    let facts = Self.facts([Self.basin("a", nominal: 28)], live: live)
    #expect(Self.tile(facts, "water") == "\(Self.degrees(24.5)) / Water, earlier")
    #expect(facts[0].muted == true)
  }

  @Test("a live cell with no number falls back to the published temperature")
  func unmeasuredLiveFallsBack() {
    let live = LiveTemp.reading(
      TempReading(measuredAt: Self.now, celsius: nil, isOpen: true))
    let facts = Self.facts([Self.basin("a", nominal: 28)], live: live)
    #expect(Self.tile(facts, "water") == "\(Self.degrees(28)) / Water, as stated")
    #expect(Self.facts([Self.basin("a")], live: .unavailable(.noKey)).isEmpty)
  }

  @Test("a lane count no basin publishes comes from the day's Belegungsplan")
  func lanesFromThePanel() {
    let day = LaneDay(
      basinID: "lap", weekday: 0, laneCount: 6, strips: [], unresolvedLanes: [],
      confidence: "complete")
    let panel = LanePanel(basinID: "lap", basinName: "25m", day: day)
    let facts = Self.facts([Self.basin("lap", length: 25)], panels: [panel])
    #expect(Self.said(facts, "lanes")?.value == "6 lanes")
    #expect(Self.en(facts.last!.phrase) == "6 lanes")
  }

  @Test("a lane plan link exists for exactly the basins that publish one")
  func lanePlanLinksFollowTheData() {
    let detail = FacilityDetailTests.detail(basins: [
      Self.basin("main"), Self.basin("lap", plan: "https://x/lap.pdf"),
      Self.basin("dive", plan: "https://x/dive.pdf"),
    ])
    let links = lanePlanLinks(detail)
    #expect(links.map(\.basinID) == ["lap", "dive"])
    #expect(links[0].url == "https://x/lap.pdf")
    #expect(links[0].basinName == "Becken lap")
    #expect(lanePlanLinks(FacilityDetailTests.detail(basins: [Self.basin("main")])).isEmpty)
  }

  @Test("the contact rows come AFTER the basins now, and the pool's words come first")
  func contactIsPushedDown() {
    let detail = FacilityDetailTests.detail(
      description: "Ein Bad.", basins: [Self.basin("a", length: 50)])
    let ids = detailSections(detail, on: FacilityDetailTests.day, for: Person(age: 30), in: Self.en)
      .map(\.id)
    #expect(ids.first == "about")
    let basins = ids.firstIndex(of: "basins")!
    let contact = ids.firstIndex(of: "where")!
    #expect(contact > basins)
    #expect(ids.last == "source")
  }
}
