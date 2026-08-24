// DayChip.swift — what one day chip says.
//
// Two lines and a flag is not much, but every part of it is a decision a test should be able
// to drive: whether this chip is today (and therefore says so rather than naming a weekday),
// what the weekday abbreviation is in the reader's locale, and what the legend says when the
// accessibility layout has collapsed the inline labels. In a `body` none of that is reachable.
//
// The formatting deliberately goes through `DateFormatter` with an EXPLICIT locale and the
// Zurich time zone. The web pinned the same two facts by test and they are easy to get wrong:
// a device in a Buddhist or Japanese calendar locale would otherwise produce a day number that
// belongs to no row in the store, and a formatter left on the system zone would name the wrong
// weekday for anyone reading from another continent.

import Foundation

/// One chip's content.
public struct DayChip: Equatable, Sendable, Identifiable {
  /// The store's key (`yyyy-MM-dd`) — also the chip's scroll-position id.
  public let day: String
  /// The short weekday, or the today word.
  public let caption: String
  /// The day of the month, without a leading zero.
  public let number: String
  public let isToday: Bool
  /// The full date, for VoiceOver and for the legend the accessibility layout shows instead of
  /// the inline captions.
  public let accessibilityLabel: String

  public var id: String { day }
}

private func formatter(_ template: String, locale: Locale) -> DateFormatter {
  let formatter = DateFormatter()
  formatter.locale = locale
  formatter.timeZone = ZurichClock.timeZone
  formatter.setLocalizedDateFormatFromTemplate(template)
  return formatter
}

/// The chip for one day.
///
/// A malformed key yields a chip that shows the key itself rather than nothing: the strip is
/// built from the store's own horizon, so an unparseable day means the store is wrong, and a
/// blank chip would hide that while a visible one reports it.
public func dayChip(
  for day: String,
  today: String,
  locale: Locale = .current
) -> DayChip {
  guard let instant = ZurichClock.instant(day: day, at: TimeOfDay(hour: 12, minute: 0)) else {
    return DayChip(day: day, caption: day, number: day, isToday: false, accessibilityLabel: day)
  }
  let isToday = day == today
  return DayChip(
    day: day,
    // "Today" beats the weekday: it is the one chip a user looks for, and it is the only
    // caption that is not derivable from the number beside it.
    caption: isToday ? "Today" : formatter("EEE", locale: locale).string(from: instant),
    number: formatter("d", locale: locale).string(from: instant),
    isToday: isToday,
    accessibilityLabel: formatter("EEEEdMMMM", locale: locale).string(from: instant)
  )
}

/// Every chip of a horizon, in order.
public func dayChips(
  from start: String,
  through end: String,
  today: String,
  locale: Locale = .current
) -> [DayChip] {
  ZurichClock.days(from: start, through: end).map { dayChip(for: $0, today: today, locale: locale) }
}
