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
    _ poolID: String, lat: Double? = nil, tier: Tier = .now, favourite: Bool = false
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

  @Test("the drawing order is the answer's, reversed — the best pool ends up on top")
  func drawingOrderPutsTheBestPoolOnTop() {
    // MapKit draws later annotations over earlier ones, and Zürich has pools a hundred metres
    // apart on the same shore. The list's order is a ranking; reversing it means the pool the
    // ranking put first is the one that is not hidden.
    let set = poolPins(
      Self.sections([Self.row("first"), Self.row("second"), Self.row("third")]),
      geo: ["first": Self.zurich, "second": Self.zurich, "third": Self.zurich])
    #expect(set.pins.map(\.poolID) == ["third", "second", "first"])
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
