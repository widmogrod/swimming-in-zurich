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
}
