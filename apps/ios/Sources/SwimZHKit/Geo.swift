// Geo.swift — the port of `src/swimzh/domain/geo.py`.
//
// Distance is one of the three things the pre-resolved export deliberately does NOT bake
// (it depends on the user's position, not on the date), so it is computed here. The
// constant and the formula are copied exactly, because `GeoTests` asserts agreement with
// the Python implementation to 1e-6 km on a committed coordinate-pair fixture.

import Foundation

/// Earth's mean radius, identical to `domain/geo._EARTH_RADIUS_KM`. A different radius is
/// the single most likely way for the two implementations to disagree, so it is pinned here
/// rather than taken from any framework constant.
private let earthRadiusKm = 6_371.0088

public struct GeoPoint: Equatable, Sendable {
  public let lat: Double
  public let lon: Double

  public init(lat: Double, lon: Double) {
    self.lat = lat
    self.lon = lon
  }
}

/// Great-circle distance between two points, in kilometres.
public func haversineKm(_ a: GeoPoint, _ b: GeoPoint) -> Double {
  let lat1 = a.lat * .pi / 180
  let lon1 = a.lon * .pi / 180
  let lat2 = b.lat * .pi / 180
  let lon2 = b.lon * .pi / 180
  let dLat = lat2 - lat1
  let dLon = lon2 - lon1
  let h = pow(sin(dLat / 2), 2) + cos(lat1) * cos(lat2) * pow(sin(dLon / 2), 2)
  return 2 * earthRadiusKm * asin(sqrt(h))
}
