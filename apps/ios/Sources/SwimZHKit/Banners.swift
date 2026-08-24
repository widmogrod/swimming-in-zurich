// Banners.swift — the day-level caveats, as models a view only has to draw.
//
// `QueryResult` carries two things beside options and statuses, and the web UI renders
// NEITHER of them (measured: `AnswerOut.warnings` / `notices` are typed in `api.ts` and never
// read). Both are date-resolved and both are honesty:
//
//  * a WARNING is ours — "the calendar is not seeded for 2027, holiday-dependent schedules may
//    be inaccurate", "these pools do not publish their holiday hours, the times shown are
//    their usual weekday ones". Suppressing it would make the answer look more certain than
//    it is.
//  * a NOTICE is the POOL's own words, in the pool's own language ("Geschlossen bis 23. August
//    (Revision)"). It is passed through untranslated, because translating a closure notice is
//    how a client invents a fact.
//
// The banner MODEL is built here so the two are ordered, identified and worded by something a
// test can drive; the view only lays them out.

import Foundation

/// One banner above the list.
public struct BannerModel: Equatable, Sendable, Identifiable {
  public enum Kind: String, Equatable, Sendable {
    /// Our caveat about the answer's certainty.
    case warning
    /// The pool's own announcement, verbatim.
    case notice
  }

  public let kind: Kind
  /// Stable across a rebuild of the same day, so SwiftUI does not re-animate an unchanged
  /// banner: kind + code + the pool it names.
  public let id: String
  /// `DayWarning.code` for a warning; the pool id for a notice.
  public let code: String
  /// A warning's title is ours (a catalog message); a notice's is the pool's NAME, which is a
  /// proper noun and never translated. `Wording` is what makes that difference a type rather
  /// than a comment.
  public let title: Wording
  /// A warning's body is ours. A NOTICE's is the pool's own sentence in the pool's own
  /// language, passed through untranslated — translating a closure announcement is how a
  /// client invents a fact.
  public let text: Wording
  /// The pool a notice speaks for; nil on a warning, which is day-level.
  public let poolName: String?

  public init(
    kind: Kind,
    id: String,
    code: String,
    title: Wording,
    text: Wording,
    poolName: String?
  ) {
    self.kind = kind
    self.id = id
    self.code = code
    self.title = title
    self.text = text
    self.poolName = poolName
  }
}

/// Every banner for one day's answer: our warnings first, then the pools' own notices.
///
/// Warnings lead because they qualify the WHOLE answer — including the notices below them —
/// while a notice speaks for one pool. Within each group the order is the answer's own, which
/// `Store` has already made total, so the list is stable across rebuilds.
///
/// `poolNames` maps pool id to display name. A notice whose pool is not in the map still gets
/// a banner: its text is the pool's own and is the part that matters; dropping the banner
/// because a name lookup missed would suppress a closure announcement over a cosmetic gap.
public func banners(
  for answer: Answer, poolNames: [String: String] = [:], format: Format
) -> [BannerModel] {
  answer.warnings.map { warningBanner($0, format) }
    + answer.notices.map { notice in
      noticeBanner(notice, poolName: poolNames[notice.poolID])
    }
}

private func warningBanner(_ warning: DayWarning, _ format: Format) -> BannerModel {
  BannerModel(
    kind: .warning,
    id: "warning|\(warning.code)",
    code: warning.code,
    title: .message(warningTitle(warning.code)),
    text: .message(warning.message(format)),
    poolName: nil
  )
}

/// A short title per known code. An unknown code takes the generic one rather than a sentence
/// about pools it never named — the same stance `DayWarning.message` takes for the same
/// reason: S5 downloads stores a newer export built.
private func warningTitle(_ code: String) -> Message {
  switch code {
  case DayWarning.calendarCoverage: return Message("banner.calendarCoverage.title")
  case DayWarning.holidayHoursUnverified: return Message("banner.holidayHoursUnverified.title")
  default: return Message("banner.generic.title")
  }
}

private func noticeBanner(_ notice: DayNotice, poolName: String?) -> BannerModel {
  BannerModel(
    kind: .notice,
    id: "notice|\(notice.poolID)|\(notice.text)",
    code: notice.poolID,
    title: .verbatim(poolName ?? notice.poolID),
    // The pool's own words, untranslated and unedited.
    text: .verbatim(notice.text),
    poolName: poolName
  )
}
