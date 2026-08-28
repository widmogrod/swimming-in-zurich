// Answer.swift — the shape of one day's answer.
//
// `Answer` mirrors the DOMAIN `QueryResult` (`query.py:355`) — options / statuses /
// warnings / notices — not the pydantic `AnswerOut`. That choice is deliberate: the two
// clients then answer the same question in the same shape, and the golden fixture the Swift
// side replays is generated straight from `find_swim_options`, with no DTO in between to
// disagree with.
//
// The three date-independent halves each carry their own honesty:
//
//  * a `PoolDayStatus` is NEVER "closed" unless the source says so. `awaiting_scrape`,
//    `no_source` and `open_unscheduled` are first-class states for a pool whose schedule is
//    UNKNOWN, and collapsing them into "closed" is the one thing the data model forbids.
//  * a `DayWarning` travels as a CODE plus params, so the client says it in its own
//    language. `rendered` reproduces `find_swim_options`'s English byte for byte, which is
//    what lets the golden test compare against `QueryResult.warnings` verbatim.
//  * a `DayNotice` is the pool's own words and is passed through untranslated.

import Foundation

/// One attendable (or explicitly not-attendable) session at one basin on one day.
public struct SwimOption: Equatable, Sendable, Identifiable {
  public let poolID: String
  public let poolName: String
  public let poolKind: String
  public let basinID: String
  public let basinName: String
  public let lengthM: Double?
  public let lanes: Int?
  public let window: TimeWindow
  public let access: SessionAccess
  public let weather: String
  public let eligibility: EligibilityResult
  /// The one clock-dependent field on an option (`query.py:552`).
  public let openAtQueryTime: Bool
  public let price: PriceEntry?
  public let distanceKm: Double?
  // --- the lane quartet (S3b) ------------------------------------------------------------
  //
  // All four are DERIVED on the client, from the `lane_day` row for this basin and this day's
  // weekday, at the queried instant (invariant E1: the plan is baked, the clock is not). They
  // are nil for the ~50 basins with no parsed Belegungsplan — nil meaning "no plan published",
  // which the ribbon renders as its own state and never as "no lanes free".
  /// `OptionOut.lane_availability` — the split at the queried instant.
  public let laneAvailability: LaneAvailability?
  /// `OptionOut.lane_timeline` — the split boundary by boundary across this session.
  public let laneTimeline: LaneTimeline?
  /// `OptionOut.lane_day_view` — which lane and whose, across the whole weekday.
  public let laneDayView: LaneDay?
  /// `OptionOut.lane_best_public` — the best time to come, BOUNDED by this session's hours.
  public let laneBestPublic: PublicWindow?

  public init(
    poolID: String,
    poolName: String,
    poolKind: String,
    basinID: String,
    basinName: String,
    lengthM: Double?,
    lanes: Int?,
    window: TimeWindow,
    access: SessionAccess,
    weather: String,
    eligibility: EligibilityResult,
    openAtQueryTime: Bool,
    price: PriceEntry?,
    distanceKm: Double?,
    laneAvailability: LaneAvailability? = nil,
    laneTimeline: LaneTimeline? = nil,
    laneDayView: LaneDay? = nil,
    laneBestPublic: PublicWindow? = nil
  ) {
    self.poolID = poolID
    self.poolName = poolName
    self.poolKind = poolKind
    self.basinID = basinID
    self.basinName = basinName
    self.lengthM = lengthM
    self.lanes = lanes
    self.window = window
    self.access = access
    self.weather = weather
    self.eligibility = eligibility
    self.openAtQueryTime = openAtQueryTime
    self.price = price
    self.distanceKm = distanceKm
    self.laneAvailability = laneAvailability
    self.laneTimeline = laneTimeline
    self.laneDayView = laneDayView
    self.laneBestPublic = laneBestPublic
  }

  public var id: String { "\(poolID)|\(basinID)|\(window.start.hhmm)|\(access.kind)" }

  public var mark: UIMark { uiMark(eligibility) }
}

/// A pool with no sessions on this day, and WHY — the four-state `StatusOut` vocabulary.
public struct PoolDayStatus: Equatable, Sendable, Identifiable {
  public let poolID: String
  public let poolName: String
  public let poolKind: String
  /// `closed` | `awaiting_scrape` | `no_source` | `open_unscheduled`.
  public let status: String
  public let detailCode: String
  /// Present only on `closed`, and the reason it is not merely "closed":
  /// `out_of_season` / `no_sessions` / `unmapped`.
  public let closureCode: String?
  public let detailParams: [String: String]
  public let distanceKm: Double?

  public var id: String { poolID }
}

public struct DayNotice: Equatable, Sendable {
  public let poolID: String
  public let text: String
}

/// A day-level caveat, as a code plus its interpolation params.
public struct DayWarning: Equatable, Sendable {
  public static let calendarCoverage = "calendar_coverage"
  public static let holidayHoursUnverified = "holiday_hours_unverified"

  public let code: String
  public let params: [String: String]

  public init(code: String, params: [String: String]) {
    self.code = code
    self.params = params
  }

  /// The warning as a catalog message: the code chooses the sentence, the params fill it in.
  ///
  /// S2 rendered this as English glued together here, reproducing
  /// `etl/ios_export.render_warning` verbatim so the golden fixture could prove the
  /// decomposition. S4 keys it off `code` + `params` instead, which is what the S2 header
  /// promised and what the ledger recorded as debt ("`DayWarning.rendered` duplicates Python's
  /// renderer"). The Python renderer is now the TEST's oracle, not a second implementation:
  /// `GoldenAnswerTests` renders these messages through the English catalog and compares.
  ///
  /// The unknown-code arm survives the change and still differs from Python's deliberately:
  /// `render_warning` has no unknown arm and would `KeyError`. That is defensible in an export
  /// where the code and the renderer ship in one commit; it is not defensible in a client that
  /// S5 lets download a store built by a newer export. So an unrecognised code rides through
  /// the passthrough key rather than crashing or borrowing the holiday sentence's claim about
  /// pools it never named.
  /// It takes a `Format` for ONE parameter, and that parameter is the reason: `params["date"]`
  /// is Python's `date.isoformat()` — `2026-12-25` — so a warning that interpolated it raw
  /// would tell a Polish reader "2026-12-25 jest dniem ustawowo wolnym" where the browser says
  /// "25 grudnia 2026". It was the sixth machine date found on this surface, and the one a
  /// three-day sample missed by three days; the sweeps that now cover the whole horizon are
  /// what turned it up.
  ///
  /// `year` and `pools` stay verbatim: a year is the same four digits in every locale here,
  /// and `pools` is a list of proper nouns the exporter already joined.
  public func message(_ format: Format) -> Message {
    switch code {
    case Self.calendarCoverage:
      return Message("warning.calendar_coverage", ["year": params["year"] ?? ""])
    case Self.holidayHoursUnverified:
      return Message(
        "warning.holiday_hours_unverified",
        [
          "date": format.storeDate(params["date"] ?? ""),
          "pools": params["pools"] ?? "",
        ])
    default:
      return Message("warning.unknown", ["code": code])
    }
  }
}

/// One day's answer for one person — the `QueryResult` shape.
public struct Answer: Equatable, Sendable {
  /// The Zurich calendar day this answers for, as the store's key (`yyyy-MM-dd`).
  public let day: String
  public let options: [SwimOption]
  public let statuses: [PoolDayStatus]
  public let notices: [DayNotice]
  public let warnings: [DayWarning]

  public init(
    day: String,
    options: [SwimOption],
    statuses: [PoolDayStatus],
    notices: [DayNotice],
    warnings: [DayWarning]
  ) {
    self.day = day
    self.options = options
    self.statuses = statuses
    self.notices = notices
    self.warnings = warnings
  }
}
