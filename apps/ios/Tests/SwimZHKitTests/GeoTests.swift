// haversineKm against the Python implementation, to 1e-6 km (plan S2 acceptance 4).
//
// A millimetre is not a meaningful distance for a swimming pool; the tolerance is tight on
// purpose. Anything looser would let a different Earth radius (6371.0 vs 6371.0088 — a 14 m
// difference over a 10 km leg) or a degrees/radians slip pass unnoticed, and those are
// exactly the two ways this function is got wrong.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Geo")
struct GeoTests {
  @Test("matches domain/geo.haversine_km on every generated pair")
  func matchesPython() throws {
    let fixture = try RepoFixtures.json(at: RepoFixtures.haversine)
    let tolerance = fixture["tolerance_km"] as? Double ?? 1e-6
    guard let cases = fixture["cases"] as? [[String: Any]] else {
      Issue.record("haversine fixture has no cases")
      return
    }
    #expect(cases.count >= 5, "the fixture must exercise more than one geometry")
    for testCase in cases {
      guard let a = testCase["a"] as? [String: Double],
        let b = testCase["b"] as? [String: Double],
        let expected = testCase["km"] as? Double,
        let lat1 = a["lat"], let lon1 = a["lon"], let lat2 = b["lat"], let lon2 = b["lon"]
      else {
        Issue.record("malformed haversine case \(testCase)")
        continue
      }
      let got = haversineKm(GeoPoint(lat: lat1, lon: lon1), GeoPoint(lat: lat2, lon: lon2))
      #expect(
        abs(got - expected) < tolerance,
        "\(testCase["name"] ?? "?"): Swift \(got) vs Python \(expected)"
      )
    }
  }

  @Test("a point is exactly zero from itself")
  func zeroDistance() {
    let point = GeoPoint(lat: 47.3739, lon: 8.5310)
    #expect(haversineKm(point, point) == 0)
  }

  @Test("distance is symmetric")
  func symmetric() {
    let a = GeoPoint(lat: 47.3739, lon: 8.5310)
    let b = GeoPoint(lat: 47.4103, lon: 8.5498)
    #expect(haversineKm(a, b) == haversineKm(b, a))
  }
}
