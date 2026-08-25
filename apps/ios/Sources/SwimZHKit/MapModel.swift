// MapModel.swift — the rules behind the map view.
//
// The map is a SECOND RENDERING OF THE SAME ANSWER, never a second query: it is handed the very
// `[ListSection]` the list is drawing, so a pool cannot be on one and absent from the other.
// That is the whole reason this file exists rather than a `Map` reading the roster directly —
// the roster is 57 pools, the answer is whatever the day, the radius, the kind filter and the
// search left, and a map showing the roster beside a list showing the answer would be two
// screens disagreeing about one question.
//
// Coordinates are the ROSTER's (`PoolRecord.geo`), because that is where they live; the answer
// carries no geometry. A pool the roster has no coordinates for is DROPPED and COUNTED, never
// dropped silently — `PinSet.missing` is what lets the screen say so instead of quietly
// showing thirty pins for thirty-four answers.

import Foundation

/// One pool, on the map.
///
/// It carries the row's `tier` and `mark` rather than a colour: colour is the app target's
/// vocabulary (`Theme.swift`), and a kit that named one would be a second place a state becomes
/// a hue. `isFavourite` rides along for the same reason it rides on `PoolRow` — the pin draws
/// it, and re-deriving it at the annotation would be a second source for one fact.
public struct PoolPin: Equatable, Sendable, Identifiable {
  public let poolID: String
  public let name: String
  public let point: GeoPoint
  public let tier: Tier
  public let mark: UIMark
  public let isFavourite: Bool
  /// The row's own answer, carried so the card a tapped pin raises says the same sentence the
  /// list row does. Re-deriving it here would be a second verdict for one pool.
  public let verdict: Verdict
  public let distanceKm: Double?

  public var id: String { poolID }

  public init(
    poolID: String, name: String, point: GeoPoint, tier: Tier, mark: UIMark, isFavourite: Bool,
    verdict: Verdict, distanceKm: Double?
  ) {
    self.poolID = poolID
    self.name = name
    self.point = point
    self.tier = tier
    self.mark = mark
    self.isFavourite = isFavourite
    self.verdict = verdict
    self.distanceKm = distanceKm
  }
}

/// The pins, and the honest count of what could not be pinned.
public struct PinSet: Equatable, Sendable {
  public let pins: [PoolPin]
  /// How many answered pools the roster has no coordinates for.
  public let missing: Int

  public init(pins: [PoolPin], missing: Int) {
    self.pins = pins
    self.missing = missing
  }

  public var isEmpty: Bool { pins.isEmpty }
}

/// Every pool in the answer that can be put on a map, in the answer's own order.
///
/// ORDER IS THE LIST'S, not the map's: the sections arrive ranked (open now, then soon, then
/// the rest) and the pins keep that sequence, so the annotation MapKit draws last — the one on
/// top where two pools overlap — is the least interesting of the pair rather than an arbitrary
/// one. Zürich has pools a hundred metres apart on the same lake shore, so this is not
/// hypothetical.
public func poolPins(_ sections: [ListSection], geo: [String: GeoPoint]) -> PinSet {
  var pins: [PoolPin] = []
  var missing = 0
  for row in sections.flatMap(\.rows) {
    guard let point = geo[row.poolID] else {
      missing += 1
      continue
    }
    pins.append(
      PoolPin(
        poolID: row.poolID, name: row.poolName, point: point, tier: row.tier, mark: row.mark,
        isFavourite: row.isFavourite, verdict: row.verdict, distanceKm: row.distanceKm))
  }
  return PinSet(pins: pins.reversed(), missing: missing)
}

/// The rectangle that holds every pin, with room to breathe.
///
/// Returned as a centre plus a SPAN IN METRES rather than as a MapKit region, because MapKit is
/// the app target's dependency and this is the rule, not the rendering. Nil when there is
/// nothing to frame — the caller then falls back on the city, which is a different decision and
/// belongs to the caller.
///
/// The floor matters more than the fit: three pools on one street corner would otherwise frame
/// to a span of eighty metres, and a map zoomed into a car park says less about "where can I
/// swim" than a map of the city does.
public func pinFrame(_ pins: [PoolPin]) -> MapFrame? {
  guard let first = pins.first else { return nil }
  var minLat = first.point.lat, maxLat = first.point.lat
  var minLon = first.point.lon, maxLon = first.point.lon
  for pin in pins.dropFirst() {
    minLat = min(minLat, pin.point.lat)
    maxLat = max(maxLat, pin.point.lat)
    minLon = min(minLon, pin.point.lon)
    maxLon = max(maxLon, pin.point.lon)
  }
  let centre = GeoPoint(lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2)
  let tall = haversineKm(
    GeoPoint(lat: minLat, lon: centre.lon), GeoPoint(lat: maxLat, lon: centre.lon))
  let wide = haversineKm(
    GeoPoint(lat: centre.lat, lon: minLon), GeoPoint(lat: centre.lat, lon: maxLon))
  return MapFrame(
    centre: centre,
    tallMetres: max(tall * 1000 * mapFramePadding, minimumMapSpanMetres),
    wideMetres: max(wide * 1000 * mapFramePadding, minimumMapSpanMetres))
}

/// A rectangle to point a map at: a centre, and how many metres it covers on each axis.
///
/// TWO SPANS, NOT ONE, and the difference is visible. A single span makes the frame square, and
/// a phone screen is not — MapKit fits the square into the taller axis and the map opens showing
/// the next canton. Zürich's pools span about ten kilometres north to south and rather less east
/// to west, which is exactly the case a square frame gets worst.
public struct MapFrame: Equatable, Sendable {
  public let centre: GeoPoint
  public let tallMetres: Double
  public let wideMetres: Double

  public init(centre: GeoPoint, tallMetres: Double, wideMetres: Double) {
    self.centre = centre
    self.tallMetres = tallMetres
    self.wideMetres = wideMetres
  }
}

/// How much wider than the pins themselves the frame is drawn, so the outermost pin is not
/// sitting on the edge of the screen under the toolbar.
public let mapFramePadding: Double = 1.18

/// The tightest the city map is allowed to be framed. See `pinFrame`.
public let minimumMapSpanMetres: Double = 1_500

/// The fallback frame: Zürich, when the answer has nothing to frame.
public let zurichCentre = GeoPoint(lat: 47.3769, lon: 8.5417)
public let cityMapSpanMetres: Double = 9_000

/// The span of the small map on a single pool's screen — close enough to show which street the
/// entrance is on, wide enough to show the lake or the river that names half of them.
public let poolMapSpanMetres: Double = 700

/// The row for one pool inside a finished answer, or nil when the answer does not contain it.
///
/// The all-pools browser pushes the SAME destination from the roster, where no row exists, so
/// nil is a first-class answer rather than a failure: the pool screen then shows what it knows
/// (a name, a place, a way to get there) and omits what only an answer can say.
public func findRow(_ sections: [ListSection], poolID: String) -> PoolRow? {
  for section in sections {
    if let row = section.rows.first(where: { $0.poolID == poolID }) { return row }
  }
  return nil
}
