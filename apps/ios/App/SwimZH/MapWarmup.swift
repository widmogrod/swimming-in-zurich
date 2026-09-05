// MapWarmup.swift — pay MapKit's first-map cost before the reader taps a pool.
//
// The first `MKMapView` a process creates loads the Maps frameworks, builds its Metal
// pipelines and opens its tile cache — a few hundred milliseconds on a phone, more in a debug
// build. The find screen draws no map until the reader asks for one, so the first pool tapped
// used to pay that bill as a push that froze for a beat and then jumped. Creating one throwaway
// map view here, after the answer is on screen, moves the bill to a moment nobody is watching.
//
// A UIKit `MKMapView` rather than a hidden SwiftUI `Map`: it needs no window and no layout, so
// nothing in the hierarchy learns of it, and a one-point frame keeps its layer from logging a
// zero drawable. It is kept alive on purpose — a released map view releases what it warmed.

import MapKit

@MainActor
enum MapWarmup {
  private static var warmed: MKMapView?

  /// Create the first map view of the process, once, after a breath so it never competes with
  /// the answer's own first frame.
  static func warm() async {
    guard warmed == nil else { return }
    try? await Task.sleep(for: .milliseconds(600))
    guard warmed == nil else { return }
    warmed = MKMapView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
  }
}
