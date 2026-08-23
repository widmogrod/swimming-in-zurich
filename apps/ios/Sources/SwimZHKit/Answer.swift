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

  /// The warning as `find_swim_options` renders it today, reproduced verbatim from
  /// `etl/ios_export.render_warning` — FOR THE TWO KNOWN CODES.
  ///
  /// Outside those two the renderers deliberately differ, and this one is the better
  /// behaviour: `render_warning` has no unknown-code arm, so it falls into the holiday
  /// branch and raises `KeyError` on the missing params. That is defensible in Python, where
  /// the export writes the code and the renderer in the same commit; it is not defensible
  /// here, where a client reads a store that S5 downloads and that can be built by a newer
  /// export. So an unrecognised code renders as itself (see `default:` below) rather than
  /// crashing or fabricating a sentence about pools it never named. The golden fixture only
  /// ever exercises the two known codes, so parity is unaffected.
  ///
  /// English is deliberate and temporary: it is what makes the decomposition provable
  /// against the golden fixture, which carries `QueryResult.warnings` as rendered strings.
  /// S4 localises the client by keying off `code` + `params`; this stays as the parity
  /// witness.
  public var rendered: String {
    switch code {
    case Self.calendarCoverage:
      return
        "calendar data not available for \(params["year"] ?? ""); "
        + "holiday-dependent schedules may be inaccurate"
    case Self.holidayHoursUnverified:
      return
        "\(params["date"] ?? "") is a public holiday and these pools do not publish their "
        + "holiday hours; the times shown are their usual weekday hours and are "
        + "unconfirmed: \(params["pools"] ?? "")"
    default:
      // A store built by a newer export can carry a code this binary has never seen, and
      // S5 downloads exactly such stores. Falling through to the holiday sentence would
      // have rendered it as " is a public holiday ... : " — a fabricated claim about pools
      // it never named. The code itself is the honest minimum: it is also the i18n key S4
      // renders from, so a client that knows the key says the sentence and one that does
      // not says the key, and neither invents a fact.
      return code
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
