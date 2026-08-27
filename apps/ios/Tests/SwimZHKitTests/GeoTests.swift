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

@Suite("Rules that used to live in a view body")
struct ViewRuleTests {
  static let zurich = GeoPoint(lat: 47.3769, lon: 8.5417)

  // MARK: - How wide a map is

  @Test("a degree of longitude is narrower than a degree of latitude, and by the cosine")
  func longitudeIsScaledByLatitude() {
    // The whole reason this goes through `haversineKm` instead of multiplying degrees by a
    // constant. At Zürich's 47°N a degree of longitude is about 68% of one at the equator, so
    // the constant form is roughly a third too large — and this number divides the screen width
    // to produce the map's clustering radius, where a third too large silently merges pools
    // that should be drawn apart.
    let atZurich = metresAcross(latitude: 47.3769, lonDelta: 1)
    let atEquator = metresAcross(latitude: 0, lonDelta: 1)
    #expect(atZurich < atEquator)
    let ratio = atZurich / atEquator
    #expect(abs(ratio - cos(47.3769 * .pi / 180)) < 0.001, "ratio was \(ratio)")
  }

  @Test("width scales with the span, and a zero span is zero metres")
  func widthScalesWithSpan() {
    let one = metresAcross(latitude: 47.3769, lonDelta: 0.01)
    let two = metresAcross(latitude: 47.3769, lonDelta: 0.02)
    #expect(abs(two - one * 2) < 1)
    // A map that has not been laid out yet reports a zero span. It must produce 0, not a NaN:
    // `PoolMapView` divides by the screen width and compares the result, and a NaN there would
    // make every comparison false and freeze the clustering at whatever it was.
    #expect(metresAcross(latitude: 47.3769, lonDelta: 0) == 0)
  }

  // MARK: - The Maps link

  @Test("the pool's name survives an ampersand, a slash and an umlaut")
  func theLabelIsEscapedConservatively() {
    // `.urlQueryAllowed` would pass `&` and `/` straight through — a name containing an
    // ampersand would end the query parameter and drop the rest of the label. Half of Zürich's
    // pools carry an umlaut and one carries a slash, so this is the real roster, not a
    // hypothetical.
    let url = mapsDirectionsURL(to: Self.zurich, named: "Flussbad Unterer Letten & Wärmebad/Süd")
    let label = String(url.split(separator: "&q=", maxSplits: 1).last ?? "")
    // The letters survive — `.alphanumerics` is what is ALLOWED through, so "Flussbad" is meant
    // to stay readable. What must not survive is anything with meaning in a URL.
    #expect(label.hasPrefix("Flussbad"))
    for dangerous in ["&", "/", " ", "ä", "ü"] {
      #expect(!label.contains(dangerous), "an unescaped \(dangerous) reached the query")
    }
    #expect(url.hasPrefix("http://maps.apple.com/?daddr="))
    // ...and it is still a URL after all that, which the app target's version could not assume:
    // it force-unwrapped a fallback on a string it had built itself.
    #expect(URL(string: url) != nil)
  }

  @Test("the coordinates never take a decimal comma")
  func coordinatesAreLocaleIndependent() {
    // A `Double` interpolated in a locale that uses a decimal comma renders `47,3769`, and Maps
    // reads that as two values. The app renders every OTHER number in the reader's locale
    // deliberately, which is exactly why this one has to opt out in writing.
    let url = mapsDirectionsURL(to: Self.zurich, named: "Hallenbad City")
    // The ONE comma in a correct URL is the separator between the two coordinates, so counting
    // commas is the check: a locale-rendered `Double` would add one inside each number and make
    // three, which Maps reads as a different place entirely.
    #expect(url.contains("daddr=47.376900,8.541700"), "\(url)")
    #expect(url.filter { $0 == "," }.count == 1, "a decimal comma reached the URL: \(url)")
  }

  @Test("a name that escapes to nothing still yields a usable link")
  func anUnnameableePoolStillRoutes() {
    // `addingPercentEncoding` returns nil only in exotic cases, and an empty label is a URL that
    // still navigates to the coordinates. Getting the reader to the pool matters more than the
    // pin's caption.
    let url = mapsDirectionsURL(to: Self.zurich, named: "")
    #expect(URL(string: url) != nil)
    #expect(url.contains("daddr="))
  }
}
