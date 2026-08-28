// PoolHeader.swift — the top of a pool's screen, and the reason it stopped being a table.
//
// "When I click on a pool I'm shown a table." That was literally true: the screen opened on a
// `List` of label/value pairs, whose first row was the address. Nothing on it connected to the
// row that had just been tapped, nothing on it could be acted on, and the pool's own answer —
// the sentence the list had spent a row saying — was not there at all.
//
// So the screen opens on the pool instead. Four things, in the order a swimmer wants them:
//
//  1. WHERE IT IS, as a picture. A map, not the string "Mythenquai 95" — the address is still
//     below in the facts, where a string belongs.
//  2. WHAT IT IS CALLED, at the size a screen about one thing can afford, with the pool's own
//     answer under it — the SAME `Verdict` the list row drew, so the push is continuous rather
//     than a change of subject. This is what the zoom transition was always animating towards
//     and never arriving at.
//  3. WHEN, as the same ribbon the row drew, for the same reason: it is the one part of the
//     answer a table genuinely cannot say.
//  4. WHAT TO DO ABOUT IT. Directions, phone, website. A swimmer reading a pool's screen is
//     usually about to go there, and none of the three was reachable as an action.
//
// The rest of the screen — every published fact, every caveat — is unchanged below it, still
// built by `SwimZHKit.detailSections` and still covered by `FieldCoverageTests`. Nothing was
// removed to make room; the header does not repeat a single row that follows it, which is why
// the address is a map here and a string there.

import MapKit
import SwiftUI
import SwimZHKit

struct PoolHeader: View {
  @Environment(\.localized) private var localized
  let detail: FacilityDetail
  /// The answer's row for this pool, when the answer contains it. Nil from the all-pools
  /// browser, which pushes the same screen from the roster — see `SwimZHKit.findRow`. The
  /// verdict and the ribbon are then omitted rather than invented.
  let row: PoolRow?
  let point: GeoPoint?
  let isToday: Bool

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.gutter) {
      map
      VStack(alignment: .leading, spacing: Design.Space.snug) {
        title
        verdict
      }
      ribbon
      PoolActions(detail: detail, point: point)
    }
    .padding(.bottom, Design.Space.row)
  }

  /// The pool, on a map, at a span the kit chooses. `.allowsHitTesting(false)` on purpose: this
  /// is a picture of where the pool is, and a map that panned under a finger scrolling the
  /// facts below would fight the screen it is part of. Getting to a real map is the Directions
  /// action, which hands the whole job to Maps.
  @ViewBuilder
  private var map: some View {
    if let point {
      Map(
        initialPosition: .region(
          MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: point.lat, longitude: point.lon),
            latitudinalMeters: poolMapSpanMetres, longitudinalMeters: poolMapSpanMetres)),
        interactionModes: []
      ) {
        Annotation(
          detail.name,
          coordinate: CLLocationCoordinate2D(
            latitude: point.lat, longitude: point.lon)
        ) {
          Image(systemName: Icon.pin)
            .font(.heroTitle)
            .foregroundStyle(.tint)
            .accessibilityHidden(true)
        }
        .annotationTitles(.hidden)
      }
      .frame(height: heroMapHeight)
      .clipShape(RoundedRectangle(cornerRadius: Design.Radius.control))
      .allowsHitTesting(false)
      .accessibilityHidden(true)
      .accessibilityIdentifier("heroMap")
    }
  }

  private var title: some View {
    HStack(alignment: .firstTextBaseline, spacing: Design.Space.row) {
      // A pool's name is a proper noun, never translated and never truncated.
      Text(verbatim: detail.name)
        .font(.heroTitle)
        .fixedSize(horizontal: false, vertical: true)
      Spacer(minLength: 0)
      mark
    }
  }

  @ViewBuilder
  private var mark: some View {
    if let row {
      Image(systemName: row.mark.symbol)
        .foregroundStyle(row.mark.accent)
        .accessibilityLabel(Text(row.mark.voiceOverLabel, localized))
    }
  }

  /// The pool's kind, and — when the answer knows one — its verdict and how far away it is.
  /// Kind alone from the browser, which is what that screen already shows for it.
  private var verdict: some View {
    HStack(spacing: Design.Space.tight) {
      Text(poolKindLabel(detail.kind), localized)
        .font(.heroSubtitle)
        .foregroundStyle(.secondary)
      verdictClause
      Spacer(minLength: 0)
      distance
    }
  }

  @ViewBuilder
  private var verdictClause: some View {
    if let row {
      // The middot is punctuation between two whole clauses, exactly as the list row uses it.
      Text(verbatim: "· \(localized(.message(row.verdict.head)))")
        .font(.heroSubtitle)
        .foregroundStyle(.primary)
    }
  }

  @ViewBuilder
  private var distance: some View {
    if let km = row?.distanceKm {
      Text(verbatim: localized.format.distance(kilometres: km))
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .monospacedDigit()
    }
  }

  /// The day, drawn exactly as the list row draws it — the same `dayRibbon`, the same canvas,
  /// the same colours. Continuity is the point: the shape under the name here is the shape that
  /// was under the name on the row you tapped.
  @ViewBuilder
  private var ribbon: some View {
    if let row {
      RibbonCanvas(
        day: dayRibbon(for: row), isToday: isToday, selection: .constant(nil),
        localized: localized)
    }
  }
}

/// How tall the header's map is. Not a `Design.Space` — those are the rhythm between two pieces
/// of text, and this is the size of a picture.
let heroMapHeight: Double = 150

/// The three things a swimmer standing outside a pool actually does.
///
/// Round, labelled, and each at least `Design.hitTarget` — the pattern Contacts and Maps use for
/// exactly this, and the reason it is a row of buttons rather than three more table rows: a
/// phone number rendered as text beside the word "Phone" is a fact; a button that dials is an
/// action, and this screen exists for someone who is about to leave the house.
///
/// A button appears only when the pool published the thing it acts on. A greyed-out "Call" for a
/// pool with no number is a promise the data cannot keep.
struct PoolActions: View {
  @Environment(\.localized) private var localized
  @Environment(\.openURL) private var openURL
  let detail: FacilityDetail
  let point: GeoPoint?

  var body: some View {
    HStack(spacing: Design.Space.gutter) {
      directions
      call
      website
      Spacer(minLength: 0)
    }
    .accessibilityElement(children: .contain)
  }

  @ViewBuilder
  private var directions: some View {
    if let point {
      // Apple's own documented URL scheme, with the pool's NAME as the label so Maps shows the
      // pool rather than a pair of coordinates. Percent-encoded, because half of them contain
      // an umlaut and one contains a slash.
      // Only when a URL can actually be built. An action that opens nothing is worse than an
      // absent one: the reader presses it and learns only that the app does not work.
      if let url = mapsURL(point) {
        ActionButton(caption: Message("action.directions"), symbol: Icon.directions) {
          openURL(url)
        }
        .accessibilityIdentifier("directionsButton")
      }
    }
  }

  @ViewBuilder
  private var call: some View {
    if let phone = detail.phone, let url = URL(string: "tel:\(phone.filter { !$0.isWhitespace })") {
      ActionButton(caption: Message("action.call"), symbol: Icon.call) { openURL(url) }
        .accessibilityIdentifier("callButton")
    }
  }

  @ViewBuilder
  private var website: some View {
    if let raw = detail.url, let url = URL(string: raw) {
      ActionButton(caption: Message("detail.fact.website"), symbol: Icon.website) { openURL(url) }
        .accessibilityIdentifier("websiteButton")
    }
  }

  /// The kit builds the string; this only turns it into a `URL`. The escaping and the
  /// locale-independent coordinate formatting are rules with a test — see `mapsDirectionsURL`,
  /// which replaced a version here that force-unwrapped a fallback on its own output.
  private func mapsURL(_ point: GeoPoint) -> URL? {
    URL(string: mapsDirectionsURL(to: point, named: detail.name))
  }
}

/// One round action: a filled glyph in a tinted circle, with its word underneath.
struct ActionButton: View {
  @Environment(\.localized) private var localized
  let caption: Message
  let symbol: String
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      VStack(spacing: Design.Space.tight) {
        Image(systemName: symbol)
          .foregroundStyle(.tint)
          .frame(width: Design.hitTarget, height: Design.hitTarget)
          .background(.tint.opacity(ChipColor.idleFill), in: Circle())
        Text(caption, localized)
          .font(.actionCaption)
          .foregroundStyle(.secondary)
      }
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel(Text(caption, localized))
  }
}
