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

public struct GeoPoint: Equatable, Hashable, Sendable {
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

// MARK: - Rules that were living in view bodies

/// How wide a map region is on the ground, in metres.
///
/// `lonDelta` is the region's full longitude span in DEGREES, which is what MapKit reports.
///
/// IT IS MEASURED, NOT MULTIPLIED, and that is the point of routing it through `haversineKm`
/// rather than scaling degrees by a constant: a degree of longitude is `cos(latitude)` as wide
/// as a degree of latitude, so the constant form is about 32% out at Zürich's 47°N. This value
/// divides the screen width to give metres-per-point, which is the clustering radius — so a
/// third too large silently merges pools that should be drawn apart.
///
/// It lived in `PoolMapView` because MapKit's `MKCoordinateRegion` is the app target's type.
/// Taking the two numbers instead keeps the arithmetic here, where a test can drive it.
public func metresAcross(latitude: Double, lonDelta: Double) -> Double {
  let half = lonDelta / 2
  return haversineKm(
    GeoPoint(lat: latitude, lon: -half), GeoPoint(lat: latitude, lon: half)) * 1000
}

/// The Apple Maps URL for a pool: drive-to coordinates, labelled with the pool's own name.
///
/// A STRING, built here, because it is a rule about escaping rather than a view's business —
/// and because the app target's version carried a force-unwrapped fallback on data it had
/// built itself, which is the shape that eventually crashes on a name nobody anticipated.
///
/// The name is percent-encoded against `.alphanumerics` deliberately, not against the usual
/// `.urlQueryAllowed`: half of Zürich's pools contain an umlaut and one contains a slash, and
/// `urlQueryAllowed` passes both `/` and `&` through — a name with an ampersand would end the
/// query parameter and drop the rest of the label. Escaping everything that is not a letter or
/// a digit is the conservative choice, and Maps decodes it identically.
///
/// The COORDINATES are formatted with an explicit POSIX-style representation rather than the
/// reader's locale: a `Double` rendered in a locale that uses a decimal comma would produce
/// `47,3769` and Maps would read it as two values.
public func mapsDirectionsURL(to point: GeoPoint, named name: String) -> String {
  let label = name.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? ""
  let latitude = String(format: "%.6f", point.lat)
  let longitude = String(format: "%.6f", point.lon)
  return "http://maps.apple.com/?daddr=\(latitude),\(longitude)&q=\(label)"
}
