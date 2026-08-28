// RibbonModel.swift — the port of `apps/web/static/js/blocks/ribbonmodel.ts`.
//
// A ribbon is the PURE mapping from one option (or one status) to a drawable state: which
// variant, which colour family, which line style, how thick, and — for a basin with a parsed
// Belegungsplan — the per-lane stack clipped to the session's own hours. No canvas, no SwiftUI:
// every visual decision is made here so it can be tested, and the renderer only obeys.
//
// THE THREE TERMINAL STATES ARE NEVER MERGED, which is this file's whole product invariant:
//   * `closed` — the source says shut. A DASHED ribbon carrying the reason.
//   * `awaiting_scrape` / `no_source` — we do not know its hours. A DOTTED ghost.
//   * `unpublished` — the pool's hours are known, its LANE SPLIT is not. Its own ribbon.
// A pool with no lane plan must never read as a pool with no free lanes, and an unknown
// schedule must never read as a closure. The published universe is eight lane sheets, so most
// pools will never have a stack, and collapsing the third state into the second would mislabel
// almost the whole city.
//
// WHY THIS IS A PORT AND NOT A SECOND IMPLEMENTATION. `blocks/fixtures/ribbon_golden.json` is
// emitted by `ribbonmodel.test.ts` and replayed by `RibbonModelTests`: the browser and the
// phone are held to the same ribbon for the same input, entry by entry. One field is
// deliberately absent from that contract — the rendered `label`, which is `t(...)` output and
// therefore locale-dependent. Its KEY (`labelKey`) is carried instead, and S4 renders it.

import Foundation

/// Access class name → colour-family key. The key carries no colour: `Theme.swift` maps it to
/// an Asset Catalog entry, exactly as the web maps it to a `.fam-*` token.
///
/// The three school-pool arms get their OWN keys rather than falling to `other`, and that is a
/// correctness rule rather than a palette preference: `other` paints in the public-swim colour,
/// so a girls-only session would be drawn in the open-to-all family — the "looks open to you"
/// lie the whole eligibility vocabulary exists to prevent.
public let accessFamilies: [String: String] = [
  "PublicSwim": "public",
  "LaneSwim": "lane",
  "FamilyTime": "family",
  "WomenOnly": "women",
  "SeniorsOnly": "seniors",
  "AdultsOnly": "adults",
  "SchoolReserved": "school",
  "ClubReserved": "club",
  "GirlsOnly": "girls",
  "GenderDiverse": "diverse",
  "AccompaniedChildren": "accompanied",
]

/// The family for an access class name; `other` for one this binary has never heard of — which
/// a store built by a newer export can carry.
public func accessFamily(_ access: String) -> String {
  accessFamilies[access] ?? "other"
}

/// The i18n key for the "lane split not published" label. The KEY travels in the golden; the
/// sentence is S4's.
public let noSplitLabelKey = "insight.noSplit.label"

/// One drawable band. Optional-as-absent throughout: a field that is nil is a field the ribbon
/// does not have, which is exactly how the browser's object literal behaves and exactly what
/// the golden records.
public struct Ribbon: Equatable, Sendable, Codable {
  public let kind: String
  public let variant: String
  public let style: String
  public let family: String
  public let access: String?
  public let facility: String?
  public let basin: String?
  public let start: String?
  public let end: String?
  public let sheath: Bool?
  public let laneCount: Int?
  public let strips: [RibbonStackLane]?
  public let segments: [RibbonSegment]?
  public let bestPublic: RibbonPublicWindow?
  public let labelKey: String?
  public let detail: String?
  public let closureCode: String?
  public let detailParams: [String: String]?
  public let status: String?

  enum CodingKeys: String, CodingKey {
    case kind
    case variant
    case style
    case family
    case access
    case facility
    case basin
    case start
    case end
    case sheath
    case laneCount = "lane_count"
    case strips
    case segments
    case bestPublic = "best_public"
    case labelKey = "label_key"
    case detail
    case closureCode = "closure_code"
    case detailParams = "detail_params"
    case status
  }

  /// The session's window, when the ribbon has one. The wire keeps `"HH:MM"` because that is
  /// what the golden compares; the renderer wants minutes.
  public var window: TimeWindow? {
    guard let start, let end, let lower = TimeOfDay(hhmm: start), let upper = TimeOfDay(hhmm: end)
    else { return nil }
    return TimeWindow(start: lower, end: upper)
  }
}

/// One segment of a lane-timeline ribbon: the split over a sub-window of the session.
public struct RibbonSegment: Equatable, Sendable, Codable {
  public let start: String
  public let end: String
  /// `public_lanes / lane_count` — the fraction of capacity open to you, and the ribbon's
  /// thickness about its mid-line.
  public let thickness: Double
  /// Any lane is reserved, so the ribbon is drawn narrower than the fraction alone: a
  /// second, non-colour channel for "someone else is in the water".
  public let pinched: Bool
  public let laneCount: Int
  public let publicLanes: Int
  public let reservedLanes: Int
  /// The count may be incomplete — from `PlanCoverage.unresolved_lanes`.
  public let partial: Bool?

  enum CodingKeys: String, CodingKey {
    case start
    case end
    case thickness
    case pinched
    case laneCount = "lane_count"
    case publicLanes = "public_lanes"
    case reservedLanes = "reserved_lanes"
    case partial
  }
}

/// One lane's sub-row of a stack, clipped to the session.
public struct RibbonStackLane: Equatable, Sendable, Codable, Identifiable {
  public let lane: Int
  public let segments: [RibbonStackBlock]

  public var id: Int { lane }
}

/// One drawable hold inside a stack sub-row.
public struct RibbonStackBlock: Equatable, Sendable, Codable, Identifiable {
  public let start: String
  public let end: String
  /// Open to the public. `public` is a Swift keyword, so the property is renamed and the
  /// coding key keeps the wire's spelling.
  public let isPublic: Bool
  public let owner: String?

  public var id: String { "\(start)|\(end)" }

  enum CodingKeys: String, CodingKey {
    case start
    case end
    case isPublic = "public"
    case owner
  }
}

/// The "best time to come" band, already bounded by the session server-side.
public struct RibbonPublicWindow: Equatable, Sendable, Codable {
  public let start: String
  public let end: String
  public let publicLanes: Int

  enum CodingKeys: String, CodingKey {
    case start
    case end
    case publicLanes = "public_lanes"
  }
}

// MARK: - The inputs

/// One option, as the ribbon model reads it. The app builds this from a `SwimOption` plus the
/// lane derivations; the golden test decodes it straight from a `/swim` payload, which is what
/// keeps the two clients comparable at all.
public struct RibbonOptionInput: Equatable, Sendable, Decodable {
  public let access: String?
  public let start: String?
  public let end: String?
  public let facility: String?
  public let basin: String?
  public let laneTimeline: RibbonTimelineInput?
  public let laneDayView: RibbonDayViewInput?
  public let laneBestPublic: RibbonPublicWindow?

  enum CodingKeys: String, CodingKey {
    case access
    case start
    case end
    case facility
    case basin
    case laneTimeline = "lane_timeline"
    case laneDayView = "lane_day_view"
    case laneBestPublic = "lane_best_public"
  }

  public init(
    access: String?,
    start: String?,
    end: String?,
    facility: String?,
    basin: String?,
    laneTimeline: RibbonTimelineInput? = nil,
    laneDayView: RibbonDayViewInput? = nil,
    laneBestPublic: RibbonPublicWindow? = nil
  ) {
    self.access = access
    self.start = start
    self.end = end
    self.facility = facility
    self.basin = basin
    self.laneTimeline = laneTimeline
    self.laneDayView = laneDayView
    self.laneBestPublic = laneBestPublic
  }
}

public struct RibbonTimelineInput: Equatable, Sendable, Decodable {
  public struct Segment: Equatable, Sendable, Decodable {
    public let start: String
    public let end: String
    public let laneCount: Int
    public let publicLanes: Int
    public let reservedLanes: Int?
    public let partial: Bool?

    enum CodingKeys: String, CodingKey {
      case start
      case end
      case laneCount = "lane_count"
      case publicLanes = "public_lanes"
      case reservedLanes = "reserved_lanes"
      case partial
    }

    public init(
      start: String, end: String, laneCount: Int, publicLanes: Int, reservedLanes: Int?,
      partial: Bool?
    ) {
      self.start = start
      self.end = end
      self.laneCount = laneCount
      self.publicLanes = publicLanes
      self.reservedLanes = reservedLanes
      self.partial = partial
    }
  }

  public let segments: [Segment]?

  public init(segments: [Segment]?) {
    self.segments = segments
  }
}

public struct RibbonDayViewInput: Equatable, Sendable, Decodable {
  public struct Segment: Equatable, Sendable, Decodable {
    public let start: String
    public let end: String
    public let access: String?
    public let owner: String?

    public init(start: String, end: String, access: String?, owner: String?) {
      self.start = start
      self.end = end
      self.access = access
      self.owner = owner
    }
  }

  public struct Strip: Equatable, Sendable, Decodable {
    public let lane: Int
    public let segments: [Segment]?

    public init(lane: Int, segments: [Segment]?) {
      self.lane = lane
      self.segments = segments
    }
  }

  public let weekday: Int?
  public let laneCount: Int
  public let strips: [Strip]?

  enum CodingKeys: String, CodingKey {
    case weekday
    case laneCount = "lane_count"
    case strips
  }

  public init(weekday: Int?, laneCount: Int, strips: [Strip]?) {
    self.weekday = weekday
    self.laneCount = laneCount
    self.strips = strips
  }
}

/// One status, as the ribbon model reads it.
public struct RibbonStatusInput: Equatable, Sendable, Decodable {
  public let facility: String?
  public let status: String?
  /// The SERVER's own prose for the state, when the input came off a `/swim` payload. It is
  /// English in one branch and curated German in the other (CLAUDE.md), so nothing user-facing
  /// reads it any more; it survives because the golden fixture carries it and dropping the
  /// field would change what the parity test compares.
  public let detail: String?
  public let closureCode: String?
  public let detailParams: [String: String]?
  /// The catalog key for the state's sentence, set on the APP's path (`DayState.ribbonInput`)
  /// and absent on the wire. This is what replaces `detail` for anything a reader sees.
  public let labelKey: String?

  enum CodingKeys: String, CodingKey {
    case facility
    case status
    case detail
    case closureCode = "closure_code"
    case detailParams = "detail_params"
    case labelKey = "label_key"
  }

  public init(
    facility: String?,
    status: String?,
    detail: String?,
    closureCode: String? = nil,
    detailParams: [String: String]? = nil,
    labelKey: String? = nil
  ) {
    self.facility = facility
    self.status = status
    self.detail = detail
    self.closureCode = closureCode
    self.detailParams = detailParams
    self.labelKey = labelKey
  }
}

// MARK: - The mapping

/// One lane's holds, clipped to `[start, end)`.
///
/// The clip is not cosmetic. A `lane_day_view` spans the whole WEEKDAY while a ribbon is one
/// SESSION, and two of a pool's sessions share a basin and therefore share a day view — so an
/// unclipped stack would paint each session across the whole day, two ribbons claiming hours
/// neither covers, drawn over each other.
///
/// A lane with nothing inside the window KEEPS its empty sub-row: "nobody holds this lane" is a
/// fact, and dropping the row would silently renumber the lanes below it.
public func laneStack(
  _ dayView: RibbonDayViewInput,
  from start: String?,
  to end: String?
) -> [RibbonStackLane] {
  guard let lower = TimeOfDay(hhmm: start ?? ""), let upper = TimeOfDay(hhmm: end ?? "") else {
    return []
  }
  var holdsByLane: [Int: [RibbonDayViewInput.Segment]] = [:]
  for strip in dayView.strips ?? [] { holdsByLane[strip.lane] = strip.segments ?? [] }
  guard dayView.laneCount >= 1 else { return [] }
  return (1...dayView.laneCount).map { lane in
    RibbonStackLane(
      lane: lane,
      segments: (holdsByLane[lane] ?? []).compactMap { clipBlock($0, lower, upper) }
    )
  }
}

private func clipBlock(
  _ segment: RibbonDayViewInput.Segment,
  _ lower: TimeOfDay,
  _ upper: TimeOfDay
) -> RibbonStackBlock? {
  guard let holdStart = TimeOfDay(hhmm: segment.start), let holdEnd = TimeOfDay(hhmm: segment.end)
  else { return nil }
  let from = max(lower, holdStart)
  let to = min(upper, holdEnd)
  // Wholly outside this session, or zero-length once clipped.
  guard from < to else { return nil }
  return RibbonStackBlock(
    start: from.hhmm,
    end: to.hhmm,
    isPublic: segment.access == publicSwimKind,
    // An empty owner string is no owner: it would render as an anonymous reservation label.
    owner: (segment.owner?.isEmpty ?? true) ? nil : segment.owner
  )
}

/// Public fraction of a timeline segment. Explicitly 0 — never a division by zero — when the
/// basin records no lanes, so the ribbon pinches shut rather than vanishing into NaN.
func publicFraction(_ segment: RibbonTimelineInput.Segment) -> Double {
  segment.laneCount > 0 ? Double(segment.publicLanes) / Double(segment.laneCount) : 0
}

/// The ribbon for one option — the three-way choice at the heart of this module.
public func optionRibbon(_ option: RibbonOptionInput) -> Ribbon {
  let family = accessFamily(option.access ?? "")
  // Hours are required to CLIP the day view to this session, so an option missing them cannot
  // be stacked: a stack with no window would paint every lane empty — "nothing free" — which is
  // the one thing a missing fact must never look like.
  let hasHours =
    TimeOfDay(hhmm: option.start ?? "") != nil && TimeOfDay(hhmm: option.end ?? "") != nil
  // `strips` must be PRESENT but may be empty, exactly as the browser tests it
  // (`Array.isArray(dayView.strips)`): a plan with a lane count and no strips is still a plan,
  // and its lanes render as empty sub-rows rather than falling back to "not published".
  if let dayView = option.laneDayView, dayView.laneCount > 0, dayView.strips != nil, hasHours {
    return Ribbon(
      kind: "option", variant: "lanestack", style: "solid", family: family,
      access: option.access, facility: option.facility, basin: option.basin,
      start: option.start, end: option.end, sheath: true, laneCount: dayView.laneCount,
      strips: laneStack(dayView, from: option.start, to: option.end), segments: nil,
      // ABSENT, not zero-width, when the server has no window for this session: the band is a
      // claim ("come then"), and a null one is no claim at all.
      bestPublic: option.laneBestPublic, labelKey: nil, detail: nil, closureCode: nil,
      detailParams: nil, status: nil
    )
  }
  if let segments = option.laneTimeline?.segments, !segments.isEmpty {
    return Ribbon(
      kind: "option", variant: "lanes", style: "solid", family: family,
      access: option.access, facility: option.facility, basin: option.basin,
      start: option.start, end: option.end, sheath: true, laneCount: nil, strips: nil,
      segments: segments.map(ribbonSegment), bestPublic: nil, labelKey: nil, detail: nil,
      closureCode: nil, detailParams: nil, status: nil
    )
  }
  return Ribbon(
    kind: "option", variant: "unpublished", style: "solid", family: family,
    access: option.access, facility: option.facility, basin: option.basin,
    start: option.start, end: option.end, sheath: false, laneCount: nil, strips: nil,
    segments: nil, bestPublic: nil, labelKey: noSplitLabelKey, detail: nil, closureCode: nil,
    detailParams: nil, status: nil
  )
}

private func ribbonSegment(_ segment: RibbonTimelineInput.Segment) -> RibbonSegment {
  RibbonSegment(
    start: segment.start,
    end: segment.end,
    thickness: publicFraction(segment),
    pinched: (segment.reservedLanes ?? 0) > 0,
    laneCount: segment.laneCount,
    publicLanes: segment.publicLanes,
    reservedLanes: segment.reservedLanes ?? 0,
    partial: segment.partial
  )
}

/// The ribbon for one status: dashed when the source says closed, dotted otherwise.
///
/// ANY unrecognised status falls to the ghost, never to closed. That direction is the whole
/// point — a client reading a store newer than itself must degrade to "we do not know", which
/// is true, rather than to "it is shut", which would be a fabricated closure.
public func statusRibbon(_ status: RibbonStatusInput) -> Ribbon {
  let closed = status.status == "closed"
  return Ribbon(
    kind: "status",
    variant: closed ? "closed" : "ghost",
    style: closed ? "dashed" : "dotted",
    family: closed ? "closed" : "unknown",
    access: nil, facility: status.facility, basin: nil, start: nil, end: nil, sheath: nil,
    laneCount: nil, strips: nil, segments: nil, bestPublic: nil, labelKey: status.labelKey,
    detail: status.detail, closureCode: status.closureCode, detailParams: status.detailParams,
    // Carried on the ghost so the canvas can render the SPECIFIC freshness state
    // (`awaiting_scrape` vs `no_source`) rather than one merged bucket.
    status: closed ? nil : status.status
  )
}
