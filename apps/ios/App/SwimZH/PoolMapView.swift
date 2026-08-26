// PoolMapView.swift — the same answer, on a map.
//
// "I can't switch views nicely, ie list, map" was the request, and the word that mattered in it
// was SAME. This is not a second query and not a second screen: it takes the very `PinSet`
// `SwimZHKit.poolPins` built from the list's own `[ListSection]`, so the day, the radius, the
// kind filter and the search that shaped the list have already shaped this. Toggling the mode
// changes how the answer is DRAWN and nothing about what it is.
//
// WHY MAPKIT IS ACCEPTABLE IN AN OFFLINE APP. The app's promise is that it ANSWERS with no
// network — the schedule, the prices, the eligibility, all baked into the bundled store — and
// that is untouched: nothing here reads the store, and the pins are already in memory. What a
// map adds is tiles, which are a picture of the city, not an answer about it. With no network
// MapKit draws its own placeholder grid and the pins stay exactly where they are, still
// tappable, still labelled — degraded, never wrong. That is the trade this file makes on
// purpose, and it is why the map is a MODE rather than the default.
//
// THE CARD, and why a pin does not simply push. Tapping an annotation that immediately pushed a
// screen would make the map a menu: you would have to leave it to learn anything, and come back
// to try the next pin. Apple Maps raises a card instead, and so does this — the pin's own
// verdict, in the same words the list row uses, with the whole card as the link. Two taps to
// the pool, one tap to compare four of them.
//
// CLUSTERING, and why it is not MapKit's. Fifty-seven pins framed on Zürich put roughly forty
// of them inside the middle third of the screen, overlapping into a single brown mass — the
// first version was a map you could not read and could not reliably tap. `MKMapView` has
// `clusteringIdentifier` for exactly this and SwiftUI's `Map` does not expose it, which turns
// out to be the better outcome: grouping is a RULE, it belongs in `SwimZHKit` where a test
// drives it (`clusterPins`), and doing it ourselves is what lets the group be anchored and
// coloured by the most interesting pool in it rather than by an arbitrary member.
//
// The camera is therefore an INPUT, not just a thing to set: what overlaps depends entirely on
// how far you are zoomed, so `onMapCameraChange` feeds `metresPerPoint` back in and the pins
// regroup. `.onEnd` rather than `.continuous`: the grouping is stable for the whole of a pinch
// and settles when the finger lifts, which is one recompute per gesture instead of one per
// frame — and a badge whose count flickered while you were still zooming would be worse than
// the wait.

import MapKit
import SwiftUI
import SwimZHKit

struct PoolMapView: View {
  @Environment(\.localized) private var localized
  let pins: PinSet

  /// The pin whose card is up, or none. It holds the WHOLE pin rather than its id, for the
  /// reason the ribbon's tap state had to learn: an id alone is a selection nothing can render.
  @State private var selected: PoolPin?
  /// MapKit's OWN selection. See `map` for why the tap cannot be handled in the annotation.
  @State private var selectedID: String?
  @State private var camera: MapCameraPosition = .automatic
  /// How many metres one screen point covers, read off the live camera. Zero until the map has
  /// reported one, which `clusterPins` reads as "no zoom known yet" and leaves every pin alone.
  @State private var metresPerPoint: Double = 0
  /// The map's own width in points — the other half of `metresPerPoint`, and the reason the
  /// clustering distance is a screen fact rather than a geographic one.
  @State private var width: Double = 0

  /// The pins, grouped for THIS zoom. Recomputed when the camera settles or the answer changes,
  /// which is what makes the badges follow a pinch.
  private var clusters: [PinCluster] {
    clusterPins(pins.pins, metresPerPoint: metresPerPoint)
  }

  var body: some View {
    ZStack(alignment: .bottom) {
      map
      card
    }
    // `.contain`, and it is load-bearing rather than tidy. A `Map` publishes itself as an
    // accessibility container that swallows its siblings: with the default treatment the card
    // above it is DRAWN — a screenshot shows it — and absent from the accessibility tree
    // entirely, so VoiceOver cannot reach it and `BehaviourTests` reported it missing on a
    // screen that was plainly showing it. Naming the stack a container puts both children back.
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("poolMap")
    .onGeometryChange(for: Double.self) { proxy in
      proxy.size.width
    } action: {
      width = $0
    }
  }

  private var map: some View {
    Map(position: $camera, selection: $selectedID) {
      // ONE view per element — the same laziness rule the list rows keep, for the same reason.
      ForEach(clusters) { cluster in
        Annotation(cluster.lead.name, coordinate: coordinate(cluster.point)) {
          // THE MARK IS NOT ITS OWN BUTTON, and this was measured rather than reasoned. The
          // obvious form is a `Button` in the annotation body — it compiles, it draws, and
          // `BehaviourTests.testTheMapDrawsTheAnswerAndOpensAPool` found that tapping it
          // selects nothing: a custom annotation body that takes the tap itself stops the
          // map's `selection` binding from ever firing. The tag is what works.
          ClusterMark(cluster: cluster, isSelected: selectedID == cluster.id)
        }
        .tag(cluster.id)
        .annotationTitles(.hidden)
      }
    }
    .mapStyle(.standard(pointsOfInterest: .excluding([.marina])))
    .onAppear(perform: frame)
    // The camera as an INPUT. See the header: what overlaps is a fact about zoom, so the
    // grouping cannot be computed once. `.onEnd`, so it settles when the finger lifts.
    .onMapCameraChange(frequency: .onEnd) { context in
      metresPerPoint = metres(across: context.region) / max(width, 1)
    }
    .onChange(of: selectedID) { _, id in select(id) }
    // A pin is a selection, like a day chip and like the mode switch — same feedback, because
    // it is the same kind of act.
    .sensoryFeedback(.selection, trigger: selectedID)
  }

  /// The card for the selected pin, and nothing at all when none is. A card that was always
  /// present would spend the bottom fifth of a map on a placeholder.
  @ViewBuilder
  private var card: some View {
    if let pin = selected {
      PinCard(pin: pin)
        .padding(.horizontal, Design.Space.gutter)
        .padding(.bottom, Design.Space.row)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
  }

  /// What a tap on a mark does, and it depends on what the mark IS.
  ///
  /// A single pin raises its card — a toggle, exactly like the ribbon's blocks, because the map
  /// has no background tap to dismiss with (a tap on the map itself is a pan waiting to happen)
  /// so the pin that raised the card is what puts it away.
  ///
  /// A GROUP ZOOMS INTO ITSELF instead, which is the one idiom every map on the phone shares.
  /// It could have raised a list of its members and that would have been worse: the reader
  /// tapped a place, and the answer to "what is here" is the map showing them, not a menu
  /// covering it. The frame is `SwimZHKit.clusterFrame`, whose floor is a city block rather
  /// than the whole-answer 1.5 km — a reader who taps to get closer must never be zoomed out.
  private func select(_ id: String?) {
    guard let id, let cluster = clusters.first(where: { $0.id == id }) else {
      return withAnimation(.snappy(duration: 0.24)) { selected = nil }
    }
    guard cluster.isSingle else { return expand(cluster) }
    withAnimation(.snappy(duration: 0.24)) { selected = cluster.lead }
  }

  /// Zoom into one group so its members come apart.
  ///
  /// The selection is cleared first: the tapped id belongs to a cluster that is about to stop
  /// existing, and leaving it set would raise the lead pool's card over a map that is still
  /// moving.
  private func expand(_ cluster: PinCluster) {
    selectedID = nil
    selected = nil
    guard let framed = clusterFrame(cluster) else { return }
    withAnimation(.smooth(duration: 0.45)) { point(at: framed) }
  }

  /// Frame the answer, or the city when there is nothing to frame. Both the rectangle and the
  /// fallback are `SwimZHKit`'s (`pinFrame`, `zurichCentre`) — a map that framed itself in a
  /// view body would be a rule nothing measures.
  private func frame() {
    point(
      at: pinFrame(pins.pins)
        ?? MapFrame(
          centre: zurichCentre, tallMetres: cityMapSpanMetres, wideMetres: cityMapSpanMetres))
  }

  /// Point the camera at one frame. The only place a `MapFrame` becomes MapKit's own type.
  private func point(at framed: MapFrame) {
    camera = .region(
      MKCoordinateRegion(
        center: CLLocationCoordinate2D(
          latitude: framed.centre.lat, longitude: framed.centre.lon),
        latitudinalMeters: framed.tallMetres, longitudinalMeters: framed.wideMetres))
  }

  private func coordinate(_ point: GeoPoint) -> CLLocationCoordinate2D {
    CLLocationCoordinate2D(latitude: point.lat, longitude: point.lon)
  }

  /// How wide this region is on the ground, in metres.
  ///
  /// Measured with the SAME `haversineKm` the kit frames with, rather than by multiplying the
  /// longitude span by a constant: the two would disagree by the cosine of the latitude, and a
  /// clustering radius that was 30% out is a map that groups pools it should not.
  private func metres(across region: MKCoordinateRegion) -> Double {
    let lat = region.center.latitude
    let half = region.span.longitudeDelta / 2
    return haversineKm(
      GeoPoint(lat: lat, lon: region.center.longitude - half),
      GeoPoint(lat: lat, lon: region.center.longitude + half)) * 1000
  }
}

/// How wide a mark is.
///
/// Smaller than `Design.hitTarget` on purpose — fifty-seven 44-point circles would cover Zürich
/// — which is why the tap target is the circle itself and what it raises is full width. A mark
/// on a map is not a control in a row.
let pinDiameter: Double = 26

/// How much a group grows over a single pin. It carries a NUMBER, which needs the room, and it
/// stands for more than one thing, which should look like more than one thing.
let clusterDiameter: Double = 34

/// How faint a pool you cannot swim in today is drawn. See `SwimZHKit.pinProminence` for which
/// those are and why muting a schedule-less pool alongside a closed one is safe.
let mutedPinOpacity: Double = 0.45

/// One mark on the map: a single pool, or a group of them.
///
/// ONE VIEW FOR BOTH, because they are one control — the same tap target, the same selection,
/// the same accessibility shape — differing only in what they draw inside the circle and how
/// loudly. Two views would have meant two `.tag()` paths and two ways to be selected, which is
/// what the first version of the tap handling already got wrong once.
struct ClusterMark: View {
  @Environment(\.localized) private var localized
  let cluster: PinCluster
  let isSelected: Bool

  var body: some View {
    Group {
      content
        .foregroundStyle(.background)
        .frame(width: diameter, height: diameter)
        .background(cluster.lead.tier.accent, in: Circle())
        .overlay(favouriteRing)
        // The GROUP's opacity, taken from its lead — so a cluster of four closed pools recedes
        // and a cluster of four containing one open pool does not. That falls out of the lead
        // being the best-ranked member rather than an arbitrary one.
        .opacity(pinProminence(cluster.lead.tier) == .muted ? mutedPinOpacity : 1)
        .scaleEffect(isSelected ? 1.35 : 1)
        .shadow(radius: isSelected ? 6 : 2, y: 1)
        .animation(.bouncy(duration: 0.3), value: isSelected)
        .contentShape(Circle())
    }
    .accessibilityAddTraits(.isButton)
    .accessibilityLabel(label)
    .accessibilityValue(value)
    .accessibilityIdentifier(cluster.isSingle ? "mapPin" : "mapCluster")
  }

  /// A count, or the pool's own tier glyph. A group deliberately does NOT wear the glyph as
  /// well: a swimmer over a "4" would be read as four swimmers rather than as four pools of
  /// which one is open, and the colour already carries the tier.
  @ViewBuilder
  private var content: some View {
    if cluster.isSingle {
      Image(systemName: cluster.lead.tier.symbol).font(.actionCaption)
    } else {
      Text(verbatim: localized.format.integer(cluster.count))
        .font(.chipCaption)
        .monospacedDigit()
        .minimumScaleFactor(0.7)
    }
  }

  /// A single pool says its name. A group says HOW MANY, because that is the only fact it
  /// stands for — reading four pool names off one badge would be a list, and a list is what
  /// tapping it deliberately does not produce.
  private var label: Text {
    cluster.isSingle
      ? Text(verbatim: cluster.lead.name)
      : Text(Message("map.poolsHere", count: cluster.count), localized)
  }

  /// The lead's verdict either way: for a single pool it is that pool's answer, and for a group
  /// it is the best answer in it — which is what the colour is already saying.
  private var value: Text { Text(cluster.lead.verdict.head, localized) }

  private var diameter: Double { cluster.isSingle ? pinDiameter : clusterDiameter }

  /// A favourite pool wears the app's tint as a ring. Not a second glyph inside the circle: the
  /// tier symbol is already there and two pictures in twenty points is neither. A GROUP wears
  /// it when any member is a favourite — the ring means "something you starred is here", which
  /// is exactly as true of four pools as of one.
  @ViewBuilder
  private var favouriteRing: some View {
    if cluster.pins.contains(where: \.isFavourite) {
      Circle().strokeBorder(.tint, lineWidth: 2.5)
    }
  }
}

/// The card a tapped pin raises: the pool's name, its answer, how far, and the whole thing is
/// the link. Glass, because it floats over the map — the one place in this app where a surface
/// genuinely sits above content rather than beside it.
struct PinCard: View {
  @Environment(\.localized) private var localized
  let pin: PoolPin

  var body: some View {
    NavigationLink(value: Route.pool(pin.poolID)) {
      HStack(spacing: Design.Space.gutter) {
        VStack(alignment: .leading, spacing: Design.Space.hair) {
          Text(verbatim: pin.name).font(.rowTitle).foregroundStyle(.primary)
          verdict
        }
        Spacer(minLength: 0)
        distance
        Image(systemName: pin.mark.symbol)
          .foregroundStyle(pin.mark.accent)
          .accessibilityLabel(Text(pin.mark.voiceOverLabel, localized))
      }
      .padding(Design.Space.gutter)
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    // A MATERIAL, not `.glassEffect`, and the lint that bans the second is right about this
    // one too: the card floats directly above the system's bottom bar, which IS glass, and
    // glass cannot sample glass. `.regularMaterial` is the surface Apple's own map card uses
    // and it composites correctly against the toolbar under it.
    .background(
      .regularMaterial, in: RoundedRectangle(cornerRadius: Design.Radius.control)
    )
    .shadow(radius: 10, y: 4)
    .accessibilityIdentifier("pinCard")
  }

  private var verdict: some View {
    HStack(spacing: Design.Space.tight) {
      Text(pin.verdict.head, localized).font(.rowVerdict).foregroundStyle(.secondary)
      verdictTail
    }
  }

  @ViewBuilder
  private var verdictTail: some View {
    if let tail = pin.verdict.tail {
      Text(verbatim: "· \(localized(tail))").font(.rowVerdictTail).foregroundStyle(.secondary)
    }
  }

  @ViewBuilder
  private var distance: some View {
    if let km = pin.distanceKm {
      Text(verbatim: localized.format.distance(kilometres: km))
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .monospacedDigit()
    }
  }
}
