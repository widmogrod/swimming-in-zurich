// MapModelTests.swift — the map's rules, driven.
//
// The map's whole claim is that it draws THE SAME ANSWER the list does. That is a claim about
// `poolPins`, not about MapKit: nothing here builds a view, and a view is the one thing that
// could not be tested anyway.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The map's rules")
struct MapModelTests {
  static func row(
    _ poolID: String, tier: Tier = .now, favourite: Bool = false
  ) -> PoolRow {
    PoolRow(
      poolID: poolID, poolName: "Pool \(poolID)", poolKind: "indoor", distanceKm: 1.5,
      tier: tier, mark: .attend,
      verdict: Verdict(head: Message("mobile.verdict.openNow")),
      options: [], inlineOptions: [], hiddenSessionCount: 0, moreSessionsLabel: nil,
      state: nil, isFavourite: favourite, nextOpenToYou: nil, openToYou: true)
  }

  static func sections(_ rows: [PoolRow]) -> [ListSection] { [ListSection(tier: .now, rows: rows)] }

  static let zurich = GeoPoint(lat: 47.3769, lon: 8.5417)

  @Test("a pin carries the row's own verdict, mark and favourite — never a second derivation")
  func pinsCarryTheRow() {
    let rows = [Self.row("a", favourite: true)]
    let set = poolPins(Self.sections(rows), geo: ["a": Self.zurich])
    let pin = try! #require(set.pins.first)
    #expect(pin.poolID == "a")
    #expect(pin.name == "Pool a")
    #expect(pin.verdict == rows[0].verdict)
    #expect(pin.mark == rows[0].mark)
    #expect(pin.tier == rows[0].tier)
    #expect(pin.isFavourite)
    #expect(pin.distanceKm == 1.5)
    #expect(set.missing == 0)
  }

  @Test("a pool the roster has no coordinates for is dropped and COUNTED, never dropped quietly")
  func missingCoordinatesAreCounted() {
    let set = poolPins(
      Self.sections([Self.row("a"), Self.row("b"), Self.row("c")]), geo: ["b": Self.zurich])
    #expect(set.pins.map(\.poolID) == ["b"])
    #expect(set.missing == 2)
    #expect(!set.isEmpty)
  }

  @Test("an answer with nothing in it pins nothing and blames nobody")
  func emptyAnswer() {
    let set = poolPins([], geo: [:])
    #expect(set.isEmpty)
    #expect(set.missing == 0)
  }

  @Test("the pins arrive in the answer's own order — the stacking is the clusterer's job")
  func pinsKeepTheAnswerOrder() {
    // This USED to return them reversed, so MapKit's last-drawn-on-top rule favoured the best
    // pool. That reversal moved into `clusterPins`, which is the function that actually knows
    // which pins ended up on top of each other; leaving it here as well would have been two
    // places deciding one thing, and the second one wins.
    let set = poolPins(
      Self.sections([Self.row("first"), Self.row("second"), Self.row("third")]),
      geo: ["first": Self.zurich, "second": Self.zurich, "third": Self.zurich])
    #expect(set.pins.map(\.poolID) == ["first", "second", "third"])
  }

  // MARK: - Framing

  @Test("nothing to frame is nil, and the caller falls back on the city")
  func nothingToFrame() {
    #expect(pinFrame([]) == nil)
  }

  @Test("the frame is centred on the pins and padded so none of them sits on the edge")
  func frameCentresAndPads() {
    let west = Self.pin("w", GeoPoint(lat: 47.35, lon: 8.50))
    let east = Self.pin("e", GeoPoint(lat: 47.41, lon: 8.60))
    let framed = try! #require(pinFrame([west, east]))
    #expect(abs(framed.centre.lat - 47.38) < 1e-9)
    #expect(abs(framed.centre.lon - 8.55) < 1e-9)
    // Each axis is padded on its OWN extent. A single span would make the frame square, and a
    // portrait phone then opens on the next canton.
    let wide =
      haversineKm(GeoPoint(lat: 47.38, lon: 8.50), GeoPoint(lat: 47.38, lon: 8.60)) * 1000
    let tall =
      haversineKm(GeoPoint(lat: 47.35, lon: 8.55), GeoPoint(lat: 47.41, lon: 8.55)) * 1000
    #expect(abs(framed.wideMetres - wide * mapFramePadding) < 1)
    #expect(abs(framed.tallMetres - tall * mapFramePadding) < 1)
    #expect(framed.tallMetres != framed.wideMetres, "the frame is square — see MapFrame")
  }

  @Test("three pools on one corner still frame to a map of a neighbourhood, not a car park")
  func theFrameHasAFloor() {
    let framed = try! #require(
      pinFrame([
        Self.pin("a", GeoPoint(lat: 47.3769, lon: 8.5417)),
        Self.pin("b", GeoPoint(lat: 47.3770, lon: 8.5418)),
      ]))
    #expect(framed.tallMetres == minimumMapSpanMetres)
    #expect(framed.wideMetres == minimumMapSpanMetres)
  }

  @Test("one pin frames to the floor rather than to a span of zero")
  func onePinIsNotAZeroSpan() {
    let framed = try! #require(pinFrame([Self.pin("a", Self.zurich)]))
    #expect(framed.tallMetres == minimumMapSpanMetres)
    #expect(framed.wideMetres == minimumMapSpanMetres)
    #expect(framed.centre == Self.zurich)
  }

  static func pin(_ id: String, _ point: GeoPoint) -> PoolPin {
    PoolPin(
      poolID: id, name: id, point: point, tier: .now, mark: .attend, isFavourite: false,
      verdict: Verdict(head: Message("mobile.verdict.openNow")), distanceKm: nil)
  }

  // MARK: - Finding the row a pushed screen was pushed from

  @Test("a pool inside the answer is found, in whichever section it sits")
  func findsARowAcrossSections() {
    let sections = [
      ListSection(tier: .now, rows: [Self.row("a")]),
      ListSection(tier: .soon, rows: [Self.row("b"), Self.row("c")]),
    ]
    #expect(findRow(sections, poolID: "c")?.poolName == "Pool c")
    #expect(findRow(sections, poolID: "a")?.poolName == "Pool a")
  }

  @Test("a pool the answer does not contain is nil, which the pool screen renders as silence")
  func aPoolOutsideTheAnswerIsNil() {
    // The ordinary case from the all-pools browser: the roster has no verdict for a pool the
    // day's answer left out, and inventing one there is the whole class of bug this app keeps
    // finding.
    #expect(findRow(Self.sections([Self.row("a")]), poolID: "zzz") == nil)
    #expect(findRow([], poolID: "a") == nil)
  }
}

@Suite("Clustering, and what recedes")
struct PinClusterTests {
  static let zurich = GeoPoint(lat: 47.3769, lon: 8.5417)

  /// A point `metres` due east of Zürich centre. East rather than north because the longitude
  /// scaling by `cos(lat)` is the half a wrong implementation gets wrong.
  static func east(_ metres: Double) -> GeoPoint {
    let degrees = metres / (111_320 * cos(zurich.lat * .pi / 180))
    return GeoPoint(lat: zurich.lat, lon: zurich.lon + degrees)
  }

  static func pin(_ id: String, _ point: GeoPoint, tier: Tier = .now) -> PoolPin {
    PoolPin(
      poolID: id, name: id, point: point, tier: tier, mark: .attend, isFavourite: false,
      verdict: Verdict(head: Message("mobile.verdict.openNow")), distanceKm: nil)
  }

  // MARK: - The grouping itself

  @Test("pins that would overlap on screen become one badge")
  func nearPinsGroup() {
    // 44 points of spacing at 10 m per point is a 440 m radius, so 200 m apart is an overlap.
    let pins = [Self.pin("a", Self.zurich), Self.pin("b", Self.east(200))]
    let clusters = clusterPins(pins, metresPerPoint: 10)
    #expect(clusters.count == 1)
    #expect(clusters[0].count == 2)
    #expect(!clusters[0].isSingle)
  }

  @Test("pins far enough apart stay their own pins")
  func farPinsStaySeparate() {
    let pins = [Self.pin("a", Self.zurich), Self.pin("b", Self.east(700))]
    let clusters = clusterPins(pins, metresPerPoint: 10)
    #expect(clusters.count == 2)
    #expect(clusters.filter(\.isSingle).count == 2)
  }

  @Test("zooming in pulls a cluster apart — the same pins, a smaller metres-per-point")
  func zoomingInSeparatesThem() {
    // The whole point of taking the camera as a parameter: nothing about the pins changed.
    let pins = [Self.pin("a", Self.zurich), Self.pin("b", Self.east(200))]
    #expect(clusterPins(pins, metresPerPoint: 10).count == 1)
    #expect(clusterPins(pins, metresPerPoint: 1).count == 2)
  }

  @Test("every pin lands in exactly one cluster, whatever the zoom")
  func nothingIsLostOrDuplicated() {
    // The property that matters most and the one an off-by-one in the greedy loop would break:
    // a map that quietly dropped a pool would be the `PinSet.missing` bug in a new place.
    let pins = (0..<20).map { Self.pin("p\($0)", Self.east(Double($0) * 90)) }
    for metresPerPoint in [0.5, 2.0, 10.0, 50.0, 400.0] {
      let clustered = clusterPins(pins, metresPerPoint: metresPerPoint)
      let ids = clustered.flatMap { $0.pins.map(\.poolID) }
      #expect(Set(ids).count == pins.count, "at \(metresPerPoint) m/pt")
      #expect(ids.count == pins.count, "a pin was duplicated at \(metresPerPoint) m/pt")
    }
  }

  @Test("no camera yet means no clustering — a map with no zoom cannot say what overlaps")
  func noCameraMeansEveryPinStandsAlone() {
    let pins = [Self.pin("a", Self.zurich), Self.pin("b", Self.zurich)]
    #expect(clusterPins(pins, metresPerPoint: 0).count == 2)
    #expect(clusterPins(pins, metresPerPoint: -1).count == 2)
  }

  @Test("no pins, no clusters — and no empty cluster either")
  func emptyIsEmpty() {
    #expect(clusterPins([], metresPerPoint: 10).isEmpty)
  }

  // MARK: - Which pin leads, and where the badge sits

  @Test("the best pool in a group anchors and colours it, whatever order it arrived in")
  func theBestPinLeads() {
    // A cluster of four where one is open now: the badge must be the open one's colour and sit
    // at the open one's coordinates. Handed to the clusterer WORST first, so an implementation
    // that simply took `pins[0]` would fail.
    let open = Self.pin("open", Self.east(120), tier: .now)
    let pins = [
      Self.pin("shut", Self.zurich, tier: .closed),
      Self.pin("ghost", Self.east(40), tier: .unknown),
      open,
    ]
    let clusters = clusterPins(pins, metresPerPoint: 10)
    #expect(clusters.count == 1)
    #expect(clusters[0].lead.poolID == "open")
    #expect(clusters[0].point == open.point)
    #expect(clusters[0].id == "open")
  }

  @Test("a cluster's pins come out best first")
  func clusterPinsAreRanked() {
    let clusters = clusterPins(
      [
        Self.pin("c", Self.east(60), tier: .closed),
        Self.pin("a", Self.zurich, tier: .now),
        Self.pin("b", Self.east(30), tier: .soon),
      ], metresPerPoint: 10)
    #expect(clusters[0].pins.map(\.poolID) == ["a", "b", "c"])
  }

  @Test("the most interesting cluster is emitted LAST, so MapKit draws it on top")
  func drawingOrderPutsTheBestClusterOnTop() {
    let clusters = clusterPins(
      [
        Self.pin("open", Self.zurich, tier: .now),
        Self.pin("shut", Self.east(4_000), tier: .closed),
      ], metresPerPoint: 1)
    #expect(clusters.map(\.lead.poolID) == ["shut", "open"])
  }

  @Test("two pools in the same tier cluster the same way twice — the order is total")
  func theOrderIsTotal() {
    // `sorted(by:)` is not documented as stable, so without the id tie-break two same-tier
    // pools could swap, the cluster's `id` would change, and SwiftUI would rebuild the
    // annotation on a camera change that moved nothing.
    let pins = [Self.pin("b", Self.east(50)), Self.pin("a", Self.zurich)]
    let once = clusterPins(pins, metresPerPoint: 10)
    let twice = clusterPins(pins.reversed(), metresPerPoint: 10)
    #expect(once.map(\.id) == twice.map(\.id))
    #expect(once[0].lead.poolID == "a")
  }

  // MARK: - Expanding one

  @Test("tapping a cluster zooms IN on it, never out")
  func expandingZoomsIn() {
    // The bug this exists to prevent: `pinFrame`'s 1.5 km floor is right for the whole city and
    // catastrophic for one cluster, whose pins are a few dozen metres apart by construction. A
    // reader who taps to get closer must not be thrown out to a 1.5 km view.
    let cluster = PinCluster(pins: [
      Self.pin("a", Self.zurich), Self.pin("b", Self.east(80)),
    ])
    let framed = try! #require(clusterFrame(cluster))
    #expect(framed.wideMetres == expandedClusterSpanMetres)
    #expect(framed.wideMetres < minimumMapSpanMetres)
  }

  @Test("a cluster wide enough to need it is framed on its own extent, not on the floor")
  func aWideClusterKeepsItsExtent() {
    let cluster = PinCluster(pins: [
      Self.pin("a", Self.zurich), Self.pin("b", Self.east(900)),
    ])
    let framed = try! #require(clusterFrame(cluster))
    #expect(framed.wideMetres > expandedClusterSpanMetres)
  }

  // MARK: - What recedes

  @Test("only the three you cannot swim in today recede")
  func prominenceMutesTheUnswimmable() {
    #expect(pinProminence(.now) == .full)
    #expect(pinProminence(.soon) == .full)
    #expect(pinProminence(.past) == .muted)
    #expect(pinProminence(.unknown) == .muted)
    #expect(pinProminence(.closed) == .muted)
  }

  @Test("`scheduled` is never muted, or every future date would be a grey map")
  func scheduledStaysFull() {
    // The case that would have made the whole rule useless: off today EVERY pool is
    // `scheduled`, so muting it fades the entire map on every date but one.
    #expect(pinProminence(.scheduled) == .full)
  }

  @Test("the tier rank agrees with the order the list puts its sections in")
  func rankMatchesTheSectionOrder() {
    // `Tier.rank` is a switch so a new case fails to build rather than ranking itself silently.
    // This is the other half: the numbers it returns must be the enum's own declaration order,
    // which is what `sections(from:)` walks — so the map and the list cannot start disagreeing
    // about which of two pools is the more interesting.
    #expect(Tier.allCases.map(\.rank) == Array(0..<Tier.allCases.count))
  }
}
