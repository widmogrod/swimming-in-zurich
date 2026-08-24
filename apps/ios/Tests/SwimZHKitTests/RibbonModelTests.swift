// The ribbon encoding, replayed against the browser (S3b acceptance 1).
//
// `apps/web/static/js/blocks/fixtures/ribbon_golden.json` is emitted by `ribbonmodel.test.ts`
// (regenerate with `REGENERATE_RIBBON_GOLDEN=1 npm test`) and carries, for every option and
// status in two `/swim` fixtures, the INPUT and the ribbon the browser produced from it. This
// suite feeds the same inputs to the Swift port and demands the same ribbons.
//
// TWO COMPARISONS, because either alone has a hole:
//  * VALUE equality, so the contents must match; and
//  * KEY-SET equality against the raw JSON, because value equality alone would let the port
//    silently ignore a field the golden carries — a decoder that never reads `best_public`
//    would decode it to nil and compare equal to another nil.
//
// One field is deliberately outside the contract: the rendered `label`. It is `t(...)` output,
// so a golden carrying it would pin the browser suite's active locale into a cross-client
// contract. `label_key` is carried instead, and it is asserted here.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Ribbon encoding vs the browser golden")
struct RibbonModelTests {
  static let goldenURL = RepoFixtures.root.appending(
    path: "apps/web/static/js/blocks/fixtures/ribbon_golden.json")

  static let golden: RibbonGolden = {
    // swift-format-ignore
    let data = try! Data(contentsOf: goldenURL)
    // swift-format-ignore
    return try! JSONDecoder().decode(RibbonGolden.self, from: data)
  }()

  /// The same file again, undecoded — the key sets live here, and a typed decode would have
  /// thrown exactly the fields it does not know about away.
  ///
  /// A function rather than a `static let`: `[String: Any]` is not `Sendable`, and a stored
  /// global of it does not compile under strict concurrency.
  static func rawEntries() throws -> [[String: Any]] {
    let data = try Data(contentsOf: goldenURL)
    let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
    return (object?["entries"] as? [[String: Any]]) ?? []
  }

  @Test("the golden covers every variant, so no arm of the mapping is unpinned")
  func goldenIsNotVacuous() throws {
    let entries = Self.golden.entries
    #expect(entries.count >= 60, "\(entries.count) entries")
    #expect(try Self.rawEntries().count == entries.count)
    let variants = Set(entries.map(\.ribbon.variant))
    #expect(variants == ["lanestack", "lanes", "unpublished", "closed", "ghost"])
    // ...and the two halves of the encoding that carry the most meaning are actually present.
    #expect(entries.contains { !($0.ribbon.strips?.isEmpty ?? true) })
    #expect(entries.contains { !($0.ribbon.segments?.isEmpty ?? true) })
    #expect(entries.contains { $0.ribbon.bestPublic != nil })
  }

  @Test("every golden entry: the Swift port produces the browser's ribbon, field for field")
  func portReproducesTheGolden() throws {
    for entry in Self.golden.entries {
      let mine = try #require(entry.produced(), "\(entry.source)#\(entry.index)")
      #expect(mine == entry.ribbon, "\(entry.kind) \(entry.source)#\(entry.index)")
    }
  }

  @Test("every golden entry: the port emits exactly the keys the browser emitted")
  func portEmitsTheSameKeys() throws {
    let encoder = JSONEncoder()
    for (raw, entry) in zip(try Self.rawEntries(), Self.golden.entries) {
      let theirs = Set((raw["ribbon"] as? [String: Any])?.keys ?? [:].keys)
      let mine = try #require(entry.produced())
      let encoded = try encoder.encode(mine)
      let object = try #require(
        try JSONSerialization.jsonObject(with: encoded) as? [String: Any])
      let context = "\(entry.source)#\(entry.index)"
      #expect(
        Set(object.keys) == theirs, "\(context): \(Set(object.keys).symmetricDifference(theirs))")
      #expect(!theirs.contains("label"), "\(context): the golden must not carry a translation")
    }
  }

  @Test("the key-set check would actually catch a dropped field")
  func keySetCheckIsNotVacuous() throws {
    // A guard on the guard: if `Ribbon`'s encoder emitted every key unconditionally, or
    // omitted them all, the comparison above would be uniform noise rather than a check.
    let ghost = statusRibbon(
      RibbonStatusInput(facility: "x", status: "no_source", detail: "d"))
    let stack = optionRibbon(
      RibbonOptionInput(
        access: "PublicSwim", start: "09:00", end: "10:00", facility: "x", basin: "b",
        laneDayView: RibbonDayViewInput(
          weekday: 1, laneCount: 1,
          strips: [
            RibbonDayViewInput.Strip(
              lane: 1,
              segments: [
                RibbonDayViewInput.Segment(
                  start: "09:00", end: "10:00", access: "PublicSwim", owner: nil)
              ])
          ])))
    let encoder = JSONEncoder()
    let ghostKeys = try keys(of: encoder.encode(ghost))
    let stackKeys = try keys(of: encoder.encode(stack))
    #expect(!ghostKeys.contains("strips"), "an absent field must not be encoded as null")
    #expect(stackKeys.contains("strips"))
    #expect(ghostKeys.contains("status"))
    #expect(!stackKeys.contains("status"))
  }

  @Test("an unknown access class falls to `other`, never to the public-swim family")
  func unknownAccessIsNeverPublic() {
    // The store can be newer than the binary (S5 downloads one), so an unheard-of access arm
    // is a real case rather than a hypothetical — and `public` is the family that reads as
    // "open to all". Every known arm keeps its own family, which is what stops a restricted
    // session from being painted in the welcome colour.
    #expect(accessFamily("SomethingNew") == "other")
    for restricted in ["GirlsOnly", "GenderDiverse", "AccompaniedChildren", "WomenOnly"] {
      #expect(accessFamily(restricted) != "public")
      #expect(accessFamily(restricted) != "other")
    }
  }

  @Test("an unrecognised status degrades to the ghost, NEVER to closed")
  func unknownStatusIsNeverClosed() {
    for status in ["open_unscheduled", "awaiting_scrape", "no_source", "something_new", nil] {
      let ribbon = statusRibbon(RibbonStatusInput(facility: "x", status: status, detail: nil))
      #expect(ribbon.variant == "ghost", "\(status ?? "nil")")
      #expect(ribbon.style == "dotted")
      #expect(ribbon.family != "closed")
    }
    #expect(
      statusRibbon(RibbonStatusInput(facility: "x", status: "closed", detail: "s")).variant
        == "closed")
  }

  @Test("a day view with no lane count falls back — an empty stack is not `no lanes free`")
  func emptyDayViewFallsBack() {
    let base = RibbonOptionInput(
      access: "PublicSwim", start: "09:00", end: "10:00", facility: "x", basin: "y",
      laneDayView: RibbonDayViewInput(weekday: 2, laneCount: 0, strips: []))
    #expect(optionRibbon(base).variant == "unpublished")
    // ...and the fallback is to the "not published" ribbon, whose label KEY is what S4 renders.
    #expect(optionRibbon(base).labelKey == noSplitLabelKey)
    #expect(optionRibbon(base).sheath == false)
  }

  @Test("the stack is clipped to the session, never to the whole weekday")
  func stackIsClippedToTheSession() throws {
    // Two of Oerlikon's options share a basin and therefore share a day view; unclipped, each
    // ribbon would paint the whole day and the two would be drawn over each other.
    let dayView = RibbonDayViewInput(
      weekday: 2, laneCount: 2,
      strips: [
        RibbonDayViewInput.Strip(
          lane: 1,
          segments: [
            RibbonDayViewInput.Segment(
              start: "06:00", end: "21:30", access: "PublicSwim", owner: nil)
          ]),
        // Wholly outside the session below: its lane keeps an EMPTY sub-row rather than
        // disappearing, because dropping it would renumber lane 2 as lane 1.
        RibbonDayViewInput.Strip(
          lane: 2,
          segments: [
            RibbonDayViewInput.Segment(
              start: "18:00", end: "20:00", access: "ClubReserved", owner: "ASVZ")
          ]),
      ])
    let ribbon = optionRibbon(
      RibbonOptionInput(
        access: "LaneSwim", start: "06:00", end: "08:00", facility: "x", basin: "y",
        laneDayView: dayView))
    let strips = try #require(ribbon.strips)
    #expect(strips.count == 2)
    #expect(strips[0].segments.map(\.end) == ["08:00"])
    #expect(strips[1].segments.isEmpty)
  }

  @Test("a segment recording no lanes has thickness 0, never NaN")
  func zeroLaneSegmentPinchesShut() throws {
    let ribbon = optionRibbon(
      RibbonOptionInput(
        access: "PublicSwim", start: "08:00", end: "09:00", facility: "x", basin: "y",
        laneTimeline: RibbonTimelineInput(segments: [
          RibbonTimelineInput.Segment(
            start: "08:00", end: "09:00", laneCount: 0, publicLanes: 0, reservedLanes: 0,
            partial: true)
        ])))
    let segments = try #require(ribbon.segments)
    #expect(segments[0].thickness == 0)
    #expect(segments[0].partial == true)
  }

  private func keys(of data: Data) throws -> Set<String> {
    let object = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    return Set(object.keys)
  }
}

/// The generated golden, as the test reads it.
struct RibbonGolden: Decodable {
  struct Entry: Decodable {
    let source: String
    let kind: String
    let index: Int
    let option: RibbonOptionInput?
    let status: RibbonStatusInput?
    let ribbon: Ribbon

    private enum CodingKeys: String, CodingKey {
      case source
      case kind
      case index
      case input
      case ribbon
    }

    init(from decoder: Decoder) throws {
      let container = try decoder.container(keyedBy: CodingKeys.self)
      source = try container.decode(String.self, forKey: .source)
      kind = try container.decode(String.self, forKey: .kind)
      index = try container.decode(Int.self, forKey: .index)
      ribbon = try container.decode(Ribbon.self, forKey: .ribbon)
      // One `input` key carrying two shapes, discriminated by `kind` — the same discrimination
      // `ribbonsFor` makes when it draws statuses first and options on top.
      option = kind == "option" ? try container.decode(RibbonOptionInput.self, forKey: .input) : nil
      status = kind == "status" ? try container.decode(RibbonStatusInput.self, forKey: .input) : nil
    }

    /// The ribbon the Swift port makes of this entry's input.
    func produced() -> Ribbon? {
      if let option { return optionRibbon(option) }
      if let status { return statusRibbon(status) }
      return nil
    }
  }

  let entries: [Entry]
}
