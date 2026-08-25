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
  }

  private var map: some View {
    Map(position: $camera, selection: $selectedID) {
      // ONE view per element — the same laziness rule the list rows keep, for the same reason.
      ForEach(pins.pins) { pin in
        Annotation(pin.name, coordinate: coordinate(pin)) {
          // THE PIN IS ITS OWN BUTTON, and this was measured rather than reasoned. The obvious
          // form is `Map(selection:)` with a `.tag()` on each annotation — it compiles, it
          // draws, and `BehaviourTests.testTheMapDrawsTheAnswerAndOpensAPool` found that
          // tapping a pin selects nothing: a custom annotation body takes the tap itself and
          // the map's selection binding never fires. So the tap is handled where it lands.
          PinMark(pin: pin, isSelected: selected?.poolID == pin.poolID)
        }
        .tag(pin.poolID)
        .annotationTitles(.hidden)
      }
    }
    .mapStyle(.standard(pointsOfInterest: .excluding([.marina])))
    .onAppear(perform: frame)
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

  /// Raise this pin's card, or put it away when it is already up.
  ///
  /// A TOGGLE, exactly like the ribbon's blocks: the map has no background tap to dismiss with —
  /// a tap on the map itself is a pan waiting to happen — so the pin that raised the card is
  /// what puts it away. `.snappy` rather than the default ease because the card arrives from
  /// off screen and the default reads as a lag on a gesture the finger has already finished.
  private func select(_ poolID: String?) {
    withAnimation(.snappy(duration: 0.24)) {
      selected = poolID.flatMap { id in pins.pins.first { $0.poolID == id } }
    }
  }

  /// Frame the answer, or the city when there is nothing to frame. Both the rectangle and the
  /// fallback are `SwimZHKit`'s (`pinFrame`, `zurichCentre`) — a map that framed itself in a
  /// view body would be a rule nothing measures.
  private func frame() {
    let framed =
      pinFrame(pins.pins)
      ?? MapFrame(
        centre: zurichCentre, tallMetres: cityMapSpanMetres, wideMetres: cityMapSpanMetres)
    camera = .region(
      MKCoordinateRegion(
        center: CLLocationCoordinate2D(
          latitude: framed.centre.lat, longitude: framed.centre.lon),
        latitudinalMeters: framed.tallMetres, longitudinalMeters: framed.wideMetres))
  }

  private func coordinate(_ pin: PoolPin) -> CLLocationCoordinate2D {
    CLLocationCoordinate2D(latitude: pin.point.lat, longitude: pin.point.lon)
  }
}

/// How wide a pin is. Smaller than `Design.hitTarget` on purpose — fifty-seven 44-point circles
/// would cover Zürich — which is why the tap target is the circle itself and the card it raises
/// is full width. A pin is a mark on a map, not a control in a row.
let pinDiameter: Double = 26

/// One pool, as a pin.
///
/// The tier's colour AND the tier's glyph, exactly as the list row does it — colour is never the
/// only channel here either, and a reader who cannot tell teal from green still sees a swimmer,
/// a clock or a moon. Selection grows it rather than recolouring it, because recolouring would
/// spend a word of the tier vocabulary on "you tapped this".
struct PinMark: View {
  @Environment(\.localized) private var localized
  let pin: PoolPin
  let isSelected: Bool

  var body: some View {
    Group {
      Image(systemName: pin.tier.symbol)
        .font(.actionCaption)
        .foregroundStyle(.background)
        .frame(width: pinDiameter, height: pinDiameter)
        .background(pin.tier.accent, in: Circle())
        .overlay(favouriteRing)
        .scaleEffect(isSelected ? 1.35 : 1)
        .shadow(radius: isSelected ? 6 : 2, y: 1)
        .animation(.bouncy(duration: 0.3), value: isSelected)
        .contentShape(Circle())
    }
    .accessibilityAddTraits(.isButton)
    .accessibilityLabel(Text(verbatim: pin.name))
    .accessibilityValue(Text(pin.verdict.head, localized))
    .accessibilityIdentifier("mapPin")
  }

  /// A favourite pool wears the app's tint as a ring. Not a second glyph inside the circle:
  /// the tier symbol is already there and two pictures in twenty points is neither.
  @ViewBuilder
  private var favouriteRing: some View {
    if pin.isFavourite {
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
