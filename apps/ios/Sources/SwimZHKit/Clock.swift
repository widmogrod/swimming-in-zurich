// Clock.swift — the ONLY date/time reasoning the client is allowed to do.
//
// Invariant E1 (the plan's seam): no date-dependent RULE runs on the client. Weekday scope,
// school-term scope, seasons, holiday policy, exceptions and closures are all resolved in
// Python and baked into the export. What stays here is comparing the wall clock against a
// window that was ALREADY baked — which is not a date rule, and which baking per minute
// would be absurd. `openAtQueryTime` is exactly that comparison.
//
// Everything is `Europe/Zurich`, matching the project-wide rule that all datetimes are
// tz-aware in that zone. A `Date` is an instant; the store is keyed by Zurich calendar day,
// so the conversion lives in one place here rather than at each call site.

import Foundation

/// A wall-clock time of day at minute resolution — the shape the export stores (`"HH:MM"`).
///
/// Minute resolution is the source's own: every baked `session.start` / `session.end` is
/// `%H:%M`. Storing minutes-since-midnight makes the comparison total and cheap and makes
/// `Comparable` conformance trivially correct.
public struct TimeOfDay: Comparable, Hashable, Sendable {
  public let minutesSinceMidnight: Int

  public init(hour: Int, minute: Int) {
    self.minutesSinceMidnight = hour * 60 + minute
  }

  /// Parses the export's `"HH:MM"`. Returns nil for anything else — a malformed row is a
  /// decode failure the store reports, never a silently coerced midnight.
  public init?(hhmm: String) {
    let parts = hhmm.split(separator: ":", omittingEmptySubsequences: false)
    guard parts.count == 2, let hour = Int(parts[0]), let minute = Int(parts[1]) else {
      return nil
    }
    guard (0...24).contains(hour), (0..<60).contains(minute) else { return nil }
    self.minutesSinceMidnight = hour * 60 + minute
  }

  public var hhmm: String {
    String(format: "%02d:%02d", minutesSinceMidnight / 60, minutesSinceMidnight % 60)
  }

  public static func < (lhs: TimeOfDay, rhs: TimeOfDay) -> Bool {
    lhs.minutesSinceMidnight < rhs.minutesSinceMidnight
  }
}

/// A half-open `[start, end)` window, exactly like `domain/schedule.TimeRange`.
public struct TimeWindow: Equatable, Hashable, Sendable {
  public let start: TimeOfDay
  public let end: TimeOfDay

  public init(start: TimeOfDay, end: TimeOfDay) {
    self.start = start
    self.end = end
  }

  /// `start <= t < end` — the half-open rule from `domain/schedule.TimeRange.contains`.
  /// Half-open matters: a session ending at 22:00 is NOT open at 22:00.
  public func contains(_ time: TimeOfDay) -> Bool {
    start <= time && time < end
  }
}

/// `SwimOption.open_at_query_time` (`query.py:552`) — the one clock-dependent field on an
/// option, and the reason the golden fixture asks its questions at a fixed 12:00.
public func openAtQueryTime(_ window: TimeWindow, at time: TimeOfDay) -> Bool {
  window.contains(time)
}

/// The project's single time zone. All baked dates are Zurich calendar days.
public enum ZurichClock {
  public static let timeZone = TimeZone(identifier: "Europe/Zurich") ?? .gmt

  private static var calendar: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = timeZone
    return calendar
  }

  /// The Zurich calendar day of an instant, as the export's `date` key (`yyyy-MM-dd`).
  ///
  /// Formatted from the date components rather than a `DateFormatter` so it can never pick
  /// up the device locale (a Japanese or Buddhist calendar locale would produce a key that
  /// matches no row, and the app would look empty rather than broken).
  public static func day(of instant: Date) -> String {
    let parts = calendar.dateComponents([.year, .month, .day], from: instant)
    return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
  }

  /// The Zurich wall-clock time of day of an instant.
  public static func timeOfDay(of instant: Date) -> TimeOfDay {
    let parts = calendar.dateComponents([.hour, .minute], from: instant)
    return TimeOfDay(hour: parts.hour ?? 0, minute: parts.minute ?? 0)
  }

  /// The instant at `time` on the Zurich day `yyyy-MM-dd`. Used by tests and by the app's
  /// day strip; nil for a malformed day key.
  public static func instant(day: String, at time: TimeOfDay) -> Date? {
    let parts = day.split(separator: "-")
    guard parts.count == 3, let year = Int(parts[0]), let month = Int(parts[1]),
      let dayOfMonth = Int(parts[2])
    else { return nil }
    var components = DateComponents()
    components.year = year
    components.month = month
    components.day = dayOfMonth
    components.hour = time.minutesSinceMidnight / 60
    components.minute = time.minutesSinceMidnight % 60
    components.timeZone = timeZone
    return calendar.date(from: components)
  }

  /// The Zurich calendar day `days` after `day`, as the store's key. Nil for a malformed key.
  ///
  /// This is date ARITHMETIC, not a date rule (invariant E1): it answers "which key comes
  /// next", never "is that day a school holiday". Going through `Calendar` rather than adding
  /// 86_400 seconds is what keeps it right across the two days a year Zurich changes offset,
  /// and the anchor is midday so a DST jump can never land the result on the wrong date.
  public static func day(_ day: String, plus days: Int) -> String? {
    guard let start = instant(day: day, at: TimeOfDay(hour: 12, minute: 0)) else { return nil }
    guard let moved = calendar.date(byAdding: .day, value: days, to: start) else { return nil }
    return self.day(of: moved)
  }

  /// The weekday of a store day key, MONDAY == 0 — matching `domain/schedule.Weekday` and
  /// `date.weekday()`, which is how the export keys its `lane_day` rows.
  ///
  /// `Calendar` numbers Sunday as 1, so the shift is not cosmetic: off by one here would read
  /// every basin's lane plan from the wrong day of the week, and would be invisible to every
  /// test that did not check a specific club's hours.
  public static func weekday(of day: String) -> Int? {
    guard let instant = instant(day: day, at: TimeOfDay(hour: 12, minute: 0)) else { return nil }
    guard let sundayFirst = calendar.dateComponents([.weekday], from: instant).weekday else {
      return nil
    }
    return (sundayFirst + 5) % 7
  }

  /// Every day key from `start` through `end` inclusive, in order.
  ///
  /// `limit` is a hard stop, not a preference: this walks a horizon read from a store the app
  /// did not write (S5 downloads them), and a corrupt `horizon_end` far in the future must not
  /// turn the day strip into an unbounded allocation. The published horizon is ~400 days.
  public static func days(
    from start: String,
    through end: String,
    limit: Int = 1_000
  ) -> [String] {
    guard start <= end, instant(day: start, at: TimeOfDay(hour: 12, minute: 0)) != nil else {
      return []
    }
    var days: [String] = [start]
    while days.count < limit, let next = day(days[days.count - 1], plus: 1), next <= end {
      days.append(next)
    }
    return days
  }
}
