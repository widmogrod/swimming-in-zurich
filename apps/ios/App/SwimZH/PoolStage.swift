// PoolStage.swift — the pool screen IS a map.
//
// Where the pool is, as the whole screen: a map you can pan and zoom, the pool's pin on it, the
// reader's own dot when they have allowed it, and the transport stops and car parks that answer
// "how do I get there". The pool's facts ride in a panel over the lower part of it (`PoolPanel`,
// presented by `FacilitySheet`), with three sizes to drag between. Apple Maps carries a place
// card exactly this way, and a reader who knows that gesture already knows this screen.
//
// HOW IT GOT HERE, because the file replaces two earlier shapes and the reasons matter:
//
//  1. The screen opened on a 150-point PICTURE of the map over a list of facts, first as a
//     rounded card, then full-bleed under the bar. A tap or a button then grew the picture into
//     this map, and the picture-with-a-list was what closing it gave back. Seen side by side on
//     a phone, the owner chose the map as the screen and asked for the picture to go — so the
//     picture, its stretch, its open and close buttons and the two Lab switches that compared
//     the looks are deleted rather than left as an unmeasured second path.
//  2. Opening on a PULL past the top was built and removed on evidence: this screen arrives by
//     a zoom transition, and iOS gives a zoom-pushed screen drag-to-dismiss on overscroll, so
//     the system consumed the pull before any scroll callback saw it. Recorded in the review.
//
// THE MAP VIEW IS NEVER RESIZED. Animating the old picture's frame up to the screen made MapKit
// rebuild its Metal drawable on every frame ("Failed to acquire drawable", and an assertion
// under Metal API validation). There is nothing to animate now — the map is laid out once at
// the size of the screen — and that is one more reason the picture is gone.
//
// NO CONTROL OF ITS OWN. The one thing a reader does to this map besides pan it is bring it
// back to the pool, and that button lives in the navigation bar (`FacilitySheet.toolbar`) — the
// system's own glass, at the back button's height and size, on the opposite side. A glass
// button floated here instead sat lower and larger than the back button beside it, two
// controls that disagreed about where the bar was. The request reaches this view as a count.

import MapKit
import SwiftUI
import SwimZHKit

struct PoolStage: View {
  let name: String
  let point: GeoPoint
  /// Bumped by the bar's button each time the reader asks for the pool back under the pin.
  let homeRequests: Int

  @State private var position: MapCameraPosition

  init(name: String, point: GeoPoint, homeRequests: Int) {
    self.name = name
    self.point = point
    self.homeRequests = homeRequests
    _position = State(initialValue: .region(Self.home(point)))
  }

  var body: some View {
    Map(position: $position) {
      // Where the reader is, drawn only with permission: MapKit renders nothing without it.
      UserAnnotation()
      Annotation(
        name, coordinate: CLLocationCoordinate2D(latitude: point.lat, longitude: point.lon)
      ) {
        Image(systemName: Icon.pin)
          .font(.heroTitle)
          .foregroundStyle(.tint)
          .accessibilityHidden(true)
      }
      .annotationTitles(.hidden)
    }
    // How to get there: stops and car parks. Not shops and hotels, which is the clutter every
    // other point-of-interest category adds around a city-centre pool.
    .mapStyle(.standard(pointsOfInterest: .including([.publicTransport, .parking])))
    // The system's own map controls would crowd the bar's trailing button.
    .mapControlVisibility(.hidden)
    // Under the status bar and the glass navigation bar, which is the point of a map screen.
    .ignoresSafeArea(edges: .top)
    .accessibilityIdentifier("poolStage")
    .onChange(of: homeRequests) { _, _ in goHome() }
  }

  private func goHome() {
    withAnimation(.spring(duration: 0.5, bounce: 0.15)) { position = .region(Self.home(point)) }
  }

  /// The pool, framed at the span the kit chooses.
  private static func home(_ point: GeoPoint) -> MKCoordinateRegion {
    MKCoordinateRegion(
      center: CLLocationCoordinate2D(latitude: point.lat, longitude: point.lon),
      latitudinalMeters: poolMapSpanMetres, longitudinalMeters: poolMapSpanMetres)
  }
}
