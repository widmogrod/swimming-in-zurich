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
/// ORDER IS THE LIST'S, best first: the sections arrive ranked (open now, then soon, then the
/// rest) and the pins keep that sequence. This function no longer reverses them for painting —
/// `clusterPins` owns the drawing order now, because it is the one that knows which pins ended
/// up on top of each other. The split is: THIS decides which pools are on the map and what each
/// one knows; `clusterPins` decides how they are laid out and stacked.
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
  return PinSet(pins: pins, missing: missing)
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
  frame(pins, floorMetres: minimumMapSpanMetres)
}

/// The frame for ONE cluster the reader has just tapped, which is a different question from
/// framing the whole answer and needs a different floor.
///
/// `minimumMapSpanMetres` is 1.5 km — a sane floor for "show me the city's pools" and a
/// catastrophic one here: every pin in a cluster is by construction within a few dozen points
/// of the others, so a 1.5 km floor would ZOOM OUT on a reader who tapped a cluster to get
/// closer. The floor is a city block instead, which is tight enough to pull two pools on the
/// same lake shore apart.
public func clusterFrame(_ cluster: PinCluster) -> MapFrame? {
  frame(cluster.pins, floorMetres: expandedClusterSpanMetres)
}

/// The rectangle holding these pins, padded, with the caller's own floor. See both callers.
private func frame(_ pins: [PoolPin], floorMetres: Double) -> MapFrame? {
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
    tallMetres: max(tall * 1000 * mapFramePadding, floorMetres),
    wideMetres: max(wide * 1000 * mapFramePadding, floorMetres))
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

// MARK: - Clustering

/// A group of pins that would otherwise be drawn on top of each other, or a single pin.
///
/// It is ALWAYS a cluster, even of one. The alternative — an enum of "pin or cluster" — makes
/// every call site branch on a distinction the renderer already has to make anyway (a count
/// badge or a tier glyph), and makes the tap handler two functions where it is one.
public struct PinCluster: Equatable, Sendable, Identifiable {
  /// The pins in it, best first. Never empty.
  public let pins: [PoolPin]

  public init(pins: [PoolPin]) {
    self.pins = pins
  }

  /// The best-ranked pin in the group, which is also its ANCHOR: the badge is drawn at this
  /// pool's own coordinates rather than at the group's centroid.
  ///
  /// A centroid would be the obvious choice and is the wrong one here. Expanding a cluster
  /// replaces one badge with several pins, and with a centroid every one of them — including
  /// the one that had been standing for the group — jumps somewhere new. Anchored on the lead,
  /// the badge simply becomes the pin that was already under it and the rest fan out around it.
  public var lead: PoolPin { pins[0] }

  public var point: GeoPoint { lead.point }
  public var count: Int { pins.count }
  public var isSingle: Bool { pins.count == 1 }

  /// Stable across a re-cluster at the same zoom, because it is the lead's id and the lead is
  /// chosen by rank rather than by iteration order. An identity that moved would make SwiftUI
  /// tear the annotation down and rebuild it on every camera change.
  public var id: String { lead.poolID }
}

/// How far apart two pins must be, in SCREEN POINTS, to be drawn separately.
///
/// Points rather than metres, because the thing being avoided is visual overlap and that is a
/// screen fact: 200 m is two touching pins across the whole city and half a screen at street
/// level.
///
/// It is measured against the WIDER of the two marks, not the narrower. A group badge is 34
/// points across, so a spacing of 34 puts two badges exactly rim to rim — which a screenshot
/// showed as pairs of touching circles all down the west of the city. 44 is the badge plus a
/// gap you can see.
public let clusterSpacingPoints: Double = 44

/// The floor for `clusterFrame` — roughly a city block. See there.
public let expandedClusterSpanMetres: Double = 150

/// Group pins that would overlap at this zoom.
///
/// GREEDY, ANCHORED ON THE BEST PIN, rather than the obvious grid. A grid snaps each pin to a
/// cell and groups by cell, which is O(n) and has one bad property that matters on this map:
/// two pools ten metres apart but either side of a cell boundary stay drawn on top of each
/// other, which is the exact case the whole function exists for. Greedy has no boundary — a pin
/// joins whichever existing cluster it is genuinely near — and at 57 pools the O(n²) it costs
/// is about three thousand distance checks, run once when the camera stops.
///
/// Walking the pins BEST FIRST is what makes it deterministic and what makes `lead` mean
/// something: the first pin to claim a patch of screen is the most interesting one there, so a
/// cluster containing an open pool is anchored and coloured by that pool rather than by
/// whichever closed one happened to be first in the array.
///
/// `metresPerPoint` comes from the live camera. Zero or less means the caller has no camera yet
/// (the first frame, before `onMapCameraChange` has fired), and every pin stands alone — which
/// is the pre-clustering behaviour, and correct: a map with no known zoom cannot say what
/// overlaps.
public func clusterPins(_ pins: [PoolPin], metresPerPoint: Double) -> [PinCluster] {
  guard metresPerPoint > 0 else { return pins.map { PinCluster(pins: [$0]) } }
  let radiusKm = clusterSpacingPoints * metresPerPoint / 1000
  var groups: [[PoolPin]] = []
  for pin in pins.sorted(by: pinRankOrder) {
    if let index = groups.firstIndex(where: { haversineKm($0[0].point, pin.point) <= radiusKm }) {
      groups[index].append(pin)
    } else {
      groups.append([pin])
    }
  }
  // WORST FIRST on the way out, so the most interesting cluster is the annotation MapKit draws
  // LAST and therefore the one on top where two badges still touch. `poolPins` used to do this
  // with a `.reversed()`; it belongs here, where the stacking is actually decided.
  return groups.map(PinCluster.init).sorted { $0.lead.tier.rank > $1.lead.tier.rank }
}

/// Best first, and TOTAL — ties broken by pool id.
///
/// The tie-break is not decoration. `sorted(by:)` is not documented as stable in Swift, so two
/// pools in the same tier could swap between two runs at the same zoom; the cluster they anchor
/// would change identity and SwiftUI would rebuild the annotation for no reason.
private func pinRankOrder(_ lhs: PoolPin, _ rhs: PoolPin) -> Bool {
  (lhs.tier.rank, lhs.poolID) < (rhs.tier.rank, rhs.poolID)
}

// MARK: - What recedes

/// How loudly a pin is drawn.
///
/// Not a colour and not an opacity — those are `Theme.swift`'s, and a kit that named one would
/// be a second place a state becomes a hue.
public enum PinProminence: Equatable, Sendable {
  case full
  case muted
}

/// Whether this tier should recede on the map.
///
/// A LIST can afford to give every pool a full row, because rows are read in order and the
/// heading above each group already says what it is. A map has no order and no headings: fifty
/// seven pins arrive at once, and a pool that shut at nine this morning competes for attention
/// with one that is open right now.
///
/// The three that recede are the three that cannot be swum in today: `past` (today's sessions
/// are over), `closed` (the source says shut) and `unknown` (we do not know its hours).
///
/// MUTING `unknown` ALONGSIDE `closed` IS SAFE, and it is worth saying why, because the app's
/// governing invariant is that a schedule-less pool must never read as a closed one. Prominence
/// is not the channel that distinction travels on: the two keep different glyphs, different
/// colours and different words, exactly as they do in the list. What they share is only that
/// neither is an answer to "where can I swim now" — and receding is a claim about attention,
/// not about state.
///
/// `scheduled` is deliberately NOT muted, and that is the case that would have made this rule
/// useless: on any day that is not today EVERY pool is `scheduled`, so muting it would fade the
/// entire map to grey on every future date.
public func pinProminence(_ tier: Tier) -> PinProminence {
  switch tier {
  case .now, .soon, .scheduled: return .full
  case .past, .unknown, .closed: return .muted
  }
}
