// DayChip.swift — what one day chip says.
//
// Two lines and a flag is not much, but every part of it is a decision a test should be able
// to drive: whether this chip is today (and therefore says so rather than naming a weekday),
// what the weekday abbreviation is in the reader's locale, and what the legend says when the
// accessibility layout has collapsed the inline labels. In a `body` none of that is reachable.
//
// The formatting goes through `Format`, which is the ONE module allowed to hold a format
// result — with the reader's regional locale and the Zurich time zone, both explicit. Two facts
// the web pinned by test and that are easy to get wrong: a device in a Buddhist or Japanese
// calendar locale would otherwise produce a day number that belongs to no row in the store, and
// a formatter left on the system zone would name the wrong weekday for anyone reading from
// another continent. A third, added here: the weekday and the day number are read off the
// formatter's own `DateFieldAttribute` runs (`Format.dayParts`), never split out of a rendered
// string — Polish alone would defeat that, since it lower-cases its weekday names and takes a
// genitive month.

import Foundation

/// One chip's content.
public struct DayChip: Equatable, Sendable, Identifiable {
  /// The store's key (`yyyy-MM-dd`) — also the chip's scroll-position id.
  public let day: String
  /// The short weekday (the FORMATTER's words, so verbatim), or the today word (OURS, so a
  /// message). The two are different kinds of string and `Wording` keeps them apart.
  public let caption: Wording
  /// The day of the month, without a leading zero.
  public let number: String
  public let isToday: Bool
  /// The full date, for VoiceOver and for the legend the accessibility layout shows instead of
  /// the inline captions.
  public let accessibilityLabel: String

  public var id: String { day }
}

/// The chip for one day.
///
/// A malformed key yields a chip that shows the key itself rather than nothing: the strip is
/// built from the store's own horizon, so an unparseable day means the store is wrong, and a
/// blank chip would hide that while a visible one reports it.
public func dayChip(for day: String, today: String, format: Format) -> DayChip {
  guard let instant = ZurichClock.instant(day: day, at: TimeOfDay(hour: 12, minute: 0)) else {
    return DayChip(
      day: day, caption: .verbatim(day), number: day, isToday: false, accessibilityLabel: day)
  }
  let isToday = day == today
  let parts = format.dayParts(instant)
  return DayChip(
    day: day,
    // "Today" beats the weekday: it is the one chip a user looks for, and it is the only
    // caption that is not derivable from the number beside it.
    caption: isToday ? .key("common.today") : .verbatim(parts.weekday),
    number: parts.dayOfMonth,
    isToday: isToday,
    accessibilityLabel: parts.full
  )
}

/// Every chip of a horizon, in order.
public func dayChips(
  from start: String,
  through end: String,
  today: String,
  format: Format
) -> [DayChip] {
  ZurichClock.days(from: start, through: end).map { dayChip(for: $0, today: today, format: format) }
}
