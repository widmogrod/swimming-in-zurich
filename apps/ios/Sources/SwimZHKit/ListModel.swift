// ListModel.swift — one day's answer, filtered, tiered, ordered and worded.
//
// This is the whole primary screen as a value. The view walks it and lays it out; it decides
// nothing. That split is the plan's governing constraint (`SwimZHKit` is this plan's
// `appdata.ts`) and it is not stylistic: there is no first-party way to unit-test a SwiftUI
// view body, and the app target is outside the CRAP gate, so a rule placed in a `body` is a
// rule nothing measures.
//
// The tiering mirrors the web's `blocks/poolrank.ts`, with one deliberate difference. The web
// has four tiers and files a pool whose sessions have all finished under "Closed"; here that
// is its own tier, `past`, worded "Done for today". A pool that opened at 06:00 and shut at
// 09:00 is not CLOSED in the sense the data means by it, and this screen's one inviolable rule
// is that "closed" is only ever said when the source said it.

import Foundation

/// The buckets the list groups into, in display order.
public enum Tier: String, CaseIterable, Equatable, Hashable, Sendable {
  /// A session is running at the queried time. TODAY ONLY — see `Tier.scheduled`.
  case now
  /// A session starts later today. TODAY ONLY.
  case soon
  /// Today's sessions are over. TODAY ONLY.
  case past
  /// The pool has sessions on a day that is NOT today, so no wall-clock claim can be made
  /// about it at all. See `listModel`'s header for why this tier exists.
  case scheduled
  /// We do not know this pool's hours — the three ghost states.
  case unknown
  /// The source says it is shut, and why.
  case closed

  /// The section heading. Note `unknown` never says "closed": that is the invariant the whole
  /// four-state vocabulary exists to protect.
  public var title: Message {
    switch self {
    case .now: return Message("mobile.tier.now")
    case .soon: return Message("mobile.tier.soon")
    case .past: return Message("mobile.verdict.doneForToday")
    case .scheduled: return Message("tier.scheduled")
    case .unknown: return Message("mobile.tier.unknown")
    case .closed: return Message("mobile.tier.closed")
    }
  }

  /// Whether this tier is a claim about the CURRENT moment. The three that are may only ever
  /// appear on today's answer; `listModel` enforces that, and a test drives it.
  public var isWallClockClaim: Bool {
    switch self {
    case .now, .soon, .past: return true
    case .scheduled, .unknown, .closed: return false
    }
  }
}

/// The reference moment used for a day that is NOT today.
///
/// The web pins the identical constant (`apps/web/static/js/api.ts`, `DAY_MOMENT = "T12:00"`)
/// for exactly this reason: asking a future date "is it open NOW" leaks the wall clock across
/// days. At 07:30 it would put a 06:00–09:00 session four months out into "Open now"; at 22:00
/// it would declare every future day already over. Both are present-tense claims about a date
/// nobody is standing in.
///
/// `listModel` does not tier by the clock at all off-today (see `Tier.scheduled`); this exists
/// so the STORE is asked at the same fixed moment the web asks at, which keeps
/// `SwimOption.openAtQueryTime` from carrying a wall-clock answer for another date.
public let dayMoment = TimeOfDay(hour: 12, minute: 0)

/// How many of a pool's sessions the list row shows inline.
///
/// A threshold that decides what a swimmer sees, so it lives here with a test rather than as a
/// `prefix(3)` in a view body: a pool with fourteen sessions would otherwise turn one row into
/// a screenful, and the number would be duplicated at every site that had to agree with it.
public let inlineSessionLimit = 3

/// The `session.weather` token meaning "published for fair weather only".
///
/// The web keeps the same constant in its MEASURED module (`appdata.ts`, `FAIR_ONLY`). Compared
/// in a view body it would be a domain token nothing tests: if the export's spelling changed,
/// the badge would silently stop appearing and every gate would stay green.
public let fairOnlyWeather = "fair_only"

extension SwimOption {
  /// Whether this SESSION is published only for fair weather.
  ///
  /// Per session, never per day: on a summer day Heuried is certainly open 09:00–14:00 and
  /// conditionally open after, so a day-level flag would launder a known fact into an unknown.
  public var isFairWeatherOnly: Bool { weather == fairOnlyWeather }
}

/// The radius choices the filter bar offers, in kilometres.
///
/// Here rather than in the view for the same reason `AgeBand.all` and `Places.presets` are: it
/// is a value domain, and a value domain in a `ForEach` literal is one nothing can pin.
public enum RadiusOption {
  /// `nil` — no limit — is deliberately NOT in this list: it is the absence of a radius, and
  /// the picker adds it as its own row so it can never be confused with a very large one.
  public static let all: [Double] = [1, 2, 5, 10]
}

/// A row's headline, split so the view can weight the two halves differently — the same
/// bold-head / muted-tail shape the web's `verdictFor` produces.
public struct Verdict: Equatable, Sendable {
  public let head: Message
  public let tail: Message?

  public init(head: Message, tail: Message? = nil) {
    self.head = head
    self.tail = tail
  }
}

/// One pool's row for one day.
public struct PoolRow: Equatable, Sendable, Identifiable {
  public let poolID: String
  public let poolName: String
  public let poolKind: String
  public let distanceKm: Double?
  public let tier: Tier
  /// The row badge: ✓ / ? / ✕, aggregated by `dayEligibility` — a row of only "check" sessions
  /// is ?, never ✕.
  public let mark: UIMark
  public let verdict: Verdict
  /// This pool's sessions on this day, in start order. Empty for a ghost or closed row.
  public let options: [SwimOption]
  /// The sessions the row shows inline — `options` capped at `inlineSessionLimit`.
  public let inlineOptions: [SwimOption]
  /// How many sessions the row does NOT show. Zero, never negative: a row that says
  /// "+0 more" is worse than one that says nothing.
  public let hiddenSessionCount: Int
  /// The sentence for `hiddenSessionCount`, or nil when there is nothing to say.
  ///
  /// It is built HERE rather than in the view because its wording depends on `isToday`, which is
  /// a `ListModel` fact a row does not carry — so a view had no honest way to branch on it and
  /// said "more today" on every day. It is also what S4 will localise: a wrong sentence left in
  /// a `body` would have been carried into five catalogs where no test on either side could
  /// see it.
  public let moreSessionsLabel: Message?
  /// Why there are no sessions; nil when there are. Carries the fifth (horizon) state too.
  public let state: DayState?
  public let isFavourite: Bool
  /// Whether a session is running now AND this person may attend it — what "open to you"
  /// counts, and what the row's accent keys off.
  public let openToYou: Bool

  public var id: String { poolID }
}

/// One section of the list.
public struct ListSection: Equatable, Sendable, Identifiable {
  public let tier: Tier
  public let rows: [PoolRow]

  public var id: String { tier.rawValue }
  public var title: Message { tier.title }
}

/// The whole screen.
public struct ListModel: Equatable, Sendable {
  public let day: String
  public let sections: [ListSection]
  public let banners: [BannerModel]
  /// Distinct pools with a session running now that this person may attend — the summary
  /// headline's number. Counted over POOLS, not sessions, so a pool with three concurrent
  /// basins counts once. ALWAYS 0 when `isToday` is false: "open to you" is present tense.
  public let openToYouCount: Int
  /// Distinct pools with any session on this day — the off-today headline's number.
  public let scheduledPoolCount: Int
  /// Whether this answer is for the day the user is standing in. False turns off every
  /// wall-clock claim in the model, which is the whole of finding B1.
  public let isToday: Bool
  /// The date is past the store's `horizon_end` (E2). The whole screen says so; it is not a
  /// per-pool state and it is emphatically not "closed".
  public let beyondHorizon: Bool

  public var isEmpty: Bool { sections.isEmpty }

  /// The one line the filter bar shows above its summary.
  ///
  /// It changes tense with the day, because the count does: "3 open to you" is a claim about
  /// this minute and may only be made about today. On any other day the honest statement is how
  /// many pools have sessions at all.
  public var headline: Message {
    // The horizon state FIRST. Past `horizon_end` both counts are structurally zero — there are
    // no rows to count — so either sentence would report a false zero ("0 pools with sessions")
    // beside a screen that correctly says we have not resolved this day yet.
    if beyondHorizon { return dayStateLabel(.beyondHorizon) }
    // Both are PLURAL entries, so the count reaches Foundation as a number and the reader's own
    // rules pick the form. English needs one/other here and Polish four; hard-coding "pools"
    // with an interpolated number is precisely the broken grammar `plurals.ts` exists to stop.
    return isToday
      ? Message("mobile.openToYou", count: openToYouCount)
      : Message("headline.poolsWithSessions", count: scheduledPoolCount)
  }
}

/// Build the screen.
///
/// `time` supplies only the wall-clock time of day — the one clock input the client may reason
/// about (invariant E1). Everything date-dependent was resolved in Python and is already in
/// `answer`.
///
/// `today` IS LOAD-BEARING, and its absence was a real bug. The day strip spans the store's
/// whole ~400-day horizon, so `answer.day` is usually NOT the day the user is standing in — and
/// a model that tiered by the wall clock regardless would say "Open now · until 09:00" about a
/// session four months out at 07:30, and "Done for today" about every future day at 22:00. Both
/// are present-tense claims about a date nobody is in, and the second is the same family of
/// harm the four-state vocabulary exists to prevent: a false "done" instead of a false "closed".
///
/// So the clock tiers ONLY when `answer.day == today`. On any other day every pool with
/// sessions lands in `Tier.scheduled`, whose verdict states the day's hours and claims nothing
/// about the present.
public func listModel(
  answer: Answer,
  filters: Filters,
  favourites: Favourites,
  horizon: StoreMetadata,
  today: String,
  at time: TimeOfDay,
  format: Format
) -> ListModel {
  let isToday = answer.day == today
  guard horizon.covers(day: answer.day) else {
    return ListModel(
      day: answer.day,
      sections: [],
      banners: banners(for: answer, format: format),
      openToYouCount: 0,
      scheduledPoolCount: 0,
      isToday: isToday,
      beyondHorizon: true
    )
  }
  let rows = poolRows(
    answer: answer, filters: filters, favourites: favourites, isToday: isToday, at: time,
    format: format)
  let model = ListModel(
    day: answer.day,
    sections: sections(from: rows),
    banners: banners(for: answer, poolNames: poolNames(in: answer), format: format),
    openToYouCount: rows.filter(\.openToYou).count,
    scheduledPoolCount: rows.filter { !$0.options.isEmpty }.count,
    isToday: isToday,
    beyondHorizon: false
  )
  return filters.favouritesOnly ? model.keepingOnlyFavourites() : model
}

/// Pool id to display name, from the answer itself. The notice banners need it, and taking it
/// from the answer rather than from a second read keeps the two consistent by construction.
private func poolNames(in answer: Answer) -> [String: String] {
  var names: [String: String] = [:]
  for option in answer.options { names[option.poolID] = option.poolName }
  for status in answer.statuses { names[status.poolID] = status.poolName }
  return names
}

// MARK: - Rows

private func poolRows(
  answer: Answer,
  filters: Filters,
  favourites: Favourites,
  isToday: Bool,
  at time: TimeOfDay,
  format: Format
) -> [PoolRow] {
  var rows = sessionRows(
    answer: answer, filters: filters, favourites: favourites, isToday: isToday, at: time,
    format: format)
  rows += ghostRows(answer: answer, filters: filters, favourites: favourites)
  return rows.sorted(by: rowOrder)
}

private func sessionRows(
  answer: Answer,
  filters: Filters,
  favourites: Favourites,
  isToday: Bool,
  at time: TimeOfDay,
  format: Format
) -> [PoolRow] {
  var byPool: [String: [SwimOption]] = [:]
  for option in answer.options where admits(option, filters) {
    byPool[option.poolID, default: []].append(option)
  }
  return byPool.values.compactMap { options in
    sessionRow(
      options.sorted(by: startOrder), favourites: favourites, isToday: isToday, at: time,
      format: format)
  }
}

/// Whether the filters admit one session.
///
/// `eligibleOnly` filters SESSIONS, and a pool left with none then has no row at all. It does
/// NOT fall through to a ghost or a closed row: "nothing here for you" and "we do not know its
/// hours" are different sentences, and turning one into the other is the exact harm the
/// four-state vocabulary exists to prevent.
private func admits(_ option: SwimOption, _ filters: Filters) -> Bool {
  guard filters.admits(kind: option.poolKind) else { return false }
  guard option.poolName.matchesSearch(filters.search) else { return false }
  guard !filters.eligibleOnly || option.mark == .attend else { return false }
  return true
}

private func sessionRow(
  _ options: [SwimOption],
  favourites: Favourites,
  isToday: Bool,
  at time: TimeOfDay,
  format: Format
) -> PoolRow? {
  guard let first = options.first else { return nil }
  let hidden = max(0, options.count - inlineSessionLimit)
  // The clock is consulted ONLY for today. See `listModel`'s header: on any other day
  // `covering` and `next` would be answers to a question nobody asked.
  let covering = isToday ? options.first(where: { $0.window.contains(time) }) : nil
  let next = isToday ? options.first(where: { time < $0.window.start }) : nil
  return PoolRow(
    poolID: first.poolID,
    poolName: first.poolName,
    poolKind: first.poolKind,
    distanceKm: first.distanceKm,
    tier: isToday ? sessionTier(covering: covering, next: next) : .scheduled,
    mark: dayEligibility(options.map(\.mark)),
    verdict: isToday
      ? sessionVerdict(covering: covering, next: next)
      : scheduledVerdict(options),
    options: options,
    inlineOptions: Array(options.prefix(inlineSessionLimit)),
    hiddenSessionCount: hidden,
    moreSessionsLabel: moreSessionsLabel(hidden: hidden, isToday: isToday, format: format),
    state: nil,
    isFavourite: favourites.contains(first.poolID),
    // "Open to you" is present tense, so it can only ever be true for today.
    openToYou: isToday && covering?.mark == .attend
  )
}

/// "+2 more today" — but ONLY on today.
///
/// "today" is a temporal claim like any other, and on a `.scheduled` row it was the last one the
/// app could still make about a day nobody is standing in: a pool with five sessions on a date
/// four months out said "Opens 06:00 · until 22:00" and, two lines below, "+2 more today".
/// The wording depends on `isToday`, which is a `ListModel` fact a row does not carry, so it is
/// decided here rather than branched on in a view.
///
/// Deliberately NOT a plural catalog entry: there is no noun in it to inflect, so all four
/// Polish forms would be identical — which the web's own "Polish never uses `other` as a
/// fallback" test then reads as a copy-paste. The number goes in as an already-formatted
/// string, so it still carries the reader's own grouping.
func moreSessionsLabel(hidden: Int, isToday: Bool, format: Format) -> Message? {
  guard hidden > 0 else { return nil }
  let params = ["count": format.integer(hidden)]
  return isToday ? Message("row.moreToday", params) : Message("row.moreThatDay", params)
}

private func sessionTier(covering: SwimOption?, next: SwimOption?) -> Tier {
  if covering != nil { return .now }
  return next != nil ? .soon : .past
}

private func sessionVerdict(covering: SwimOption?, next: SwimOption?) -> Verdict {
  if let covering {
    let until = Message("mobile.verdict.untilTime", ["hhmm": covering.window.end.hhmm])
    // "Open now" is a claim about THIS person: a lane hour reserved for a club is running, but
    // it is not open to them, and saying so is the difference between a useful answer and a
    // wasted trip.
    return covering.mark == .attend
      ? Verdict(head: Message("mobile.verdict.openNow"), tail: until)
      : Verdict(head: Message("verdict.notOpenToYou"), tail: until)
  }
  if let next {
    return Verdict(head: Message("mobile.verdict.opensAt", ["hhmm": next.window.start.hhmm]))
  }
  return Verdict(head: Message("mobile.verdict.doneForToday"))
}

/// The verdict for a day that is not today: the day's hours, and no claim about the present.
///
/// `max()` over the ends rather than the last session's end — sessions are sorted by START, and
/// an early basin can run later than a late one.
private func scheduledVerdict(_ options: [SwimOption]) -> Verdict {
  guard let first = options.first,
    let last = options.map(\.window.end).max()
  else { return Verdict(head: Message("verdict.hasSessions")) }
  return Verdict(
    head: Message("mobile.verdict.opensAt", ["hhmm": first.window.start.hhmm]),
    tail: Message("mobile.verdict.untilTime", ["hhmm": last.hhmm]))
}

private func ghostRows(
  answer: Answer,
  filters: Filters,
  favourites: Favourites
) -> [PoolRow] {
  answer.statuses.compactMap { status in
    guard filters.admits(kind: status.poolKind) else { return nil }
    guard status.poolName.matchesSearch(filters.search) else { return nil }
    let state = dayState(
      status: status.status,
      closureCode: status.closureCode,
      // The pool's own words for an unclassified closure. Without them the row would say
      // "closed" with nothing behind the claim.
      detailParams: status.detailParams
    )
    return PoolRow(
      poolID: status.poolID,
      poolName: status.poolName,
      poolKind: status.poolKind,
      distanceKm: status.distanceKm,
      tier: state.isClosureClaim ? .closed : .unknown,
      // Never ✕: nobody was excluded from anything. A pool whose hours we do not know is a
      // "check", and a closed one has no session to be eligible for either.
      mark: .check,
      verdict: Verdict(head: dayStateLabel(state)),  // a state's own sentence, never "closed"
      options: [],
      inlineOptions: [],
      hiddenSessionCount: 0,
      moreSessionsLabel: nil,
      state: state,
      isFavourite: favourites.contains(status.poolID),
      openToYou: false
    )
  }
}

// MARK: - Order

private func startOrder(_ lhs: SwimOption, _ rhs: SwimOption) -> Bool {
  (lhs.window.start.minutesSinceMidnight, lhs.basinName, lhs.access.kind)
    < (rhs.window.start.minutesSinceMidnight, rhs.basinName, rhs.access.kind)
}

/// Favourites first, then nearest first, then by name.
///
/// An UNKNOWN distance sorts LAST, never as zero: a pool that publishes no coordinates is not
/// the closest one. The name tiebreak makes the order total, so the list is stable between
/// rebuilds of the same day and SwiftUI does not reshuffle rows under the user's thumb.
private func rowOrder(_ lhs: PoolRow, _ rhs: PoolRow) -> Bool {
  if lhs.isFavourite != rhs.isFavourite { return lhs.isFavourite }
  let left = lhs.distanceKm ?? .infinity
  let right = rhs.distanceKm ?? .infinity
  if left != right { return left < right }
  return lhs.poolName < rhs.poolName
}

private func sections(from rows: [PoolRow]) -> [ListSection] {
  Tier.allCases.compactMap { tier in
    let inTier = rows.filter { $0.tier == tier }
    return inTier.isEmpty ? nil : ListSection(tier: tier, rows: inTier)
  }
}

// MARK: - The favourites-only filter

extension ListModel {
  /// The same model with non-favourite rows removed.
  ///
  /// Applied AFTER tiering rather than inside `admits` so the counts and sections a test drives
  /// are the same objects either way, and so the toggle can never change which tier a pool is
  /// in — only whether it is shown.
  public func keepingOnlyFavourites() -> ListModel {
    ListModel(
      day: day,
      sections: sections.compactMap { section in
        let kept = section.rows.filter(\.isFavourite)
        return kept.isEmpty ? nil : ListSection(tier: section.tier, rows: kept)
      },
      banners: banners,
      openToYouCount: sections.flatMap(\.rows).filter { $0.isFavourite && $0.openToYou }.count,
      scheduledPoolCount: sections.flatMap(\.rows)
        .filter { $0.isFavourite && !$0.options.isEmpty }.count,
      isToday: isToday,
      beyondHorizon: beyondHorizon
    )
  }
}
