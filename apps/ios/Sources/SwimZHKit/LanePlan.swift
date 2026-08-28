// LanePlan.swift — the port of the seven query-time derivations in `domain/lane_plan.py`.
//
// A Belegungsplan is a WEEKLY grid (7 days × N lanes × 30-min slots), so the export bakes it
// per weekday rather than per date — `lane_day(basin_id, weekday, …)`, ~400× smaller than a
// date-keyed table for exactly the same information. What it does NOT bake is the derivation
// at an instant: "how many lanes are public at 07:15" is a clock question, and invariant E1
// puts clock questions on the client. So these seven functions live here:
//
//   _active_reservations · _public_run_end · lane_availability_at · lane_availability_timeline
//   lane_day_view · best_public_time · club_roster
//
// ONE SHAPE DIFFERENCE, and it is the reason the port is not a transliteration. Python holds
// a `LanePlan` as RLE `LaneReservation`s — one row per (weekday-set × time × LANE-SET) — while
// the export writes what `lane_day_view` already produced: one strip per lane, each carrying
// its own holds. The lane-set axis is therefore already exploded when it reaches this file, so
// every derivation is written over lanes rather than over reservations. Two places where that
// distinction is visible are called out below (`owners` ordering and `clubRoster`'s regrouping),
// because both are equalities the generated fixture has to prove rather than assume.
//
// WHAT IS NOT INVENTED. A blank slot is never public: `publicLanes` counts only lanes an
// explicit `PublicSwim` hold covers, exactly as Python does. And `partial` is derived from
// `unresolved_lanes` — a lane the parser could not read is a lane we know nothing about, so a
// count that touches one says so instead of quietly under-reporting.

import Foundation

/// One owner's hold on one lane for one time range — a cell of a lane's day strip.
public struct LaneHold: Equatable, Sendable {
  public let window: TimeWindow
  /// The reservation's access class name, as the export writes it. The parser only ever
  /// emits `PublicSwim`, `SchoolReserved` and `ClubReserved`.
  public let accessKind: String
  /// `owner_label(access)` — the club's name, or "Schools". Nil for a public hold, which is
  /// nobody's reservation.
  public let owner: String?

  public init(window: TimeWindow, accessKind: String, owner: String?) {
    self.window = window
    self.accessKind = accessKind
    self.owner = owner
  }

  public var isPublic: Bool { accessKind == publicSwimKind }
}

/// The access class name a public block carries. A constant rather than a literal at four
/// comparison sites: it is the token that decides whether a lane reads as open to you.
public let publicSwimKind = "PublicSwim"

/// One lane's whole weekday: its holds, in start order. Gaps stay implicit.
public struct LaneStrip: Equatable, Sendable, Identifiable {
  public let lane: Int
  public let holds: [LaneHold]

  public init(lane: Int, holds: [LaneHold]) {
    self.lane = lane
    self.holds = holds
  }

  public var id: Int { lane }
}

/// One `lane_day` row: a basin's parsed plan for one weekday, plus the two honesty fields.
public struct LaneDay: Equatable, Sendable {
  public let basinID: String
  /// Monday == 0, matching `domain/schedule.Weekday` and `date.weekday()`.
  public let weekday: Int
  public let laneCount: Int
  public let strips: [LaneStrip]
  /// Lane indices the parser could not resolve. LOAD-BEARING: `LaneAvailability.partial` is
  /// derived from these, and `partial` is a rendered field.
  public let unresolvedLanes: Set<Int>
  /// `complete` | `partial` — the plan-level `PlanConfidence`.
  public let confidence: String

  public init(
    basinID: String,
    weekday: Int,
    laneCount: Int,
    strips: [LaneStrip],
    unresolvedLanes: Set<Int>,
    confidence: String
  ) {
    self.basinID = basinID
    self.weekday = weekday
    self.laneCount = laneCount
    self.strips = strips
    self.unresolvedLanes = unresolvedLanes
    self.confidence = confidence
  }

  /// The only spelling of "the parser read this plan in full" — `PlanConfidence.COMPLETE`.
  public static let completeConfidence = "complete"

  /// Whether the parser resolved every cell of this basin's sheet.
  ///
  /// Written as `!= complete`, and the polarity is the whole point. Two call sites tested this
  /// token independently and disagreed: the Gantt asked `confidence != "complete"`, the sheet
  /// asked `confidence == "partial"`, so a third value the export might one day write — or a
  /// misspelling — made one surface shout and the other stay silent about the same basin. Only
  /// a known-complete plan may be presented as complete; anything else is caveated.
  public var isComplete: Bool { confidence == Self.completeConfidence }

  /// The sentence shown beside a lane view the parser could not read in full, or nil.
  ///
  /// It lives here, not in the two views that show it, for the reason every sentence in this
  /// package does: the app target is outside the CRAP gate and a SwiftUI body cannot be driven
  /// by a test, so a sentence written there is one nothing checks. It had already been written
  /// twice, in two wordings, with two polarities.
  ///
  /// Never an empty lane row and no caveat: an unread lane drawn as empty says "nobody has
  /// booked it", which is the opposite of "we could not tell".
  public var incompleteLanesCaveat: Message? {
    isComplete ? nil : Message("lane.incompleteCaveat")
  }
}

/// How a basin's lanes are split at one instant — the port of `LaneAvailability`.
public struct LaneAvailability: Equatable, Sendable {
  public let laneCount: Int
  public let publicLanes: Int
  public let reservedLanes: Int
  /// Distinct owners holding a lane at this instant, ordered by their lowest held lane.
  public let owners: [String]
  /// The end of the contiguous public run covering this instant, nil when no lane is public.
  public let publicUntil: TimeOfDay?
  /// The slot touches a lane the parser could not read, so the counts may be incomplete.
  public let partial: Bool
}

/// One sub-window over which the split is constant.
public struct LaneSlot: Equatable, Sendable {
  public let window: TimeWindow
  public let availability: LaneAvailability
}

/// A session's split as it evolves — the port of `LaneAvailabilityTimeline`.
public struct LaneTimeline: Equatable, Sendable {
  public let weekday: Int
  public let segments: [LaneSlot]
}

/// A window during which `publicLanes` lanes are open to the public.
public struct PublicWindow: Equatable, Sendable {
  public let window: TimeWindow
  public let publicLanes: Int
}

/// One owner's standing reservation on one weekday — the port of `ClubSlot`.
public struct ClubSlot: Equatable, Sendable, Identifiable {
  public let club: String
  public let weekday: Int
  public let window: TimeWindow
  public let lanes: [Int]

  public var id: String {
    "\(club)|\(weekday)|\(window.start.hhmm)|\(window.end.hhmm)|\(lanes.map(String.init).joined(separator: ","))"
  }
}

extension LaneDay {
  /// `_active_reservations` — every (lane, hold) covering `time`.
  ///
  /// Half-open, like everything else that compares against a baked window: a hold ending at
  /// 09:00 is not active at 09:00, so two adjacent holds never both answer for one instant.
  func activeHolds(at time: TimeOfDay) -> [(lane: Int, hold: LaneHold)] {
    strips.flatMap { strip in
      strip.holds.filter { $0.window.contains(time) }.map { (strip.lane, $0) }
    }
  }

  /// `_public_run_end` — the end of the maximal contiguous public window covering `time`.
  ///
  /// Adjacent public blocks are MERGED (`prev.end == next.start`), which is what lets a plan
  /// stored as four half-hour rows say "public until 18:00" rather than "until 06:30". The
  /// same range appears once per lane here where Python sees it once per reservation; merging
  /// is idempotent over the duplicates, so both arrive at the same runs.
  func publicRunEnd(at time: TimeOfDay) -> TimeOfDay? {
    var merged: [TimeWindow] = []
    for window in publicWindows().sorted(by: windowOrder) {
      if let last = merged.last, window.start <= last.end {
        merged[merged.count - 1] = TimeWindow(start: last.start, end: max(last.end, window.end))
      } else {
        merged.append(window)
      }
    }
    return merged.first { $0.contains(time) }?.end
  }

  private func publicWindows() -> [TimeWindow] {
    strips.flatMap { $0.holds.filter(\.isPublic).map(\.window) }
  }

  /// `lane_availability_at` — the split at one instant. Pure, and meaningful for any time,
  /// including on a future date: the plan is recurring, not live.
  public func availability(at time: TimeOfDay) -> LaneAvailability {
    let active = activeHolds(at: time)
    let publicLanes = Set(active.filter { $0.hold.isPublic }.map(\.lane))
    let reservedLanes = Set(active.filter { !$0.hold.isPublic }.map(\.lane))
    let covered = publicLanes.union(reservedLanes)
    return LaneAvailability(
      laneCount: laneCount,
      publicLanes: publicLanes.count,
      reservedLanes: reservedLanes.count,
      owners: ownerOrder(active),
      publicUntil: publicRunEnd(at: time),
      // An unresolved lane that some hold DOES cover at this instant is resolved after all,
      // which is why this asks about `covered` rather than about the lane list alone.
      partial: unresolvedLanes.contains { !covered.contains($0) }
    )
  }

  /// Distinct owners, ordered by their lowest held lane.
  ///
  /// Python sorts the active RESERVATIONS by `min(lanes)` and keeps first appearance; the
  /// export has already exploded each reservation into one hold per lane, so the equivalent
  /// is to order by lane and keep first appearance — the reservation's minimum lane is simply
  /// the first lane at which its owner appears.
  private func ownerOrder(_ active: [(lane: Int, hold: LaneHold)]) -> [String] {
    var owners: [String] = []
    for entry in active.sorted(by: { $0.lane < $1.lane }) where !entry.hold.isPublic {
      let label = entry.hold.owner ?? entry.hold.accessKind
      if !owners.contains(label) { owners.append(label) }
    }
    return owners
  }

  /// `lane_availability_timeline` — `within`, cut at every hold boundary strictly inside it.
  ///
  /// Holds are half-open, so no boundary falls strictly inside a sub-window and the split at
  /// the sub-window's START holds across the whole of it. That is what makes one evaluation
  /// per cut correct rather than a sample.
  public func availabilityTimeline(within: TimeWindow) -> LaneTimeline {
    var bounds: Set<Int> = [within.start.minutesSinceMidnight, within.end.minutesSinceMidnight]
    for strip in strips {
      for hold in strip.holds {
        for edge in [hold.window.start, hold.window.end] where within.contains(edge) {
          bounds.insert(edge.minutesSinceMidnight)
        }
      }
    }
    let cuts = bounds.sorted().map(TimeOfDay.init(minutesSinceMidnight:))
    let segments = zip(cuts, cuts.dropFirst()).map { lower, upper in
      LaneSlot(
        window: TimeWindow(start: lower, end: upper),
        availability: availability(at: lower)
      )
    }
    return LaneTimeline(weekday: weekday, segments: segments)
  }

  /// `best_public_time` — the window with the MOST public lanes free, ties to the earliest.
  ///
  /// `within` BOUNDS the search, and the two callers differ deliberately, exactly as they do
  /// in Python: a SESSION's "best time to come" is bounded by that session's own hours (a
  /// 09:00 answer is no use to a row whose hours end at 08:00), while a basin's day panel
  /// passes nothing, because a `LanePanel` is a per-day object.
  public func bestPublicTime(within: TimeWindow? = nil) -> PublicWindow? {
    let publics = clippedPublicHolds(within: within)
    guard !publics.isEmpty else { return nil }
    var windows: [PublicWindow] = []
    let bounds = Set(publics.flatMap { [$0.window.start, $0.window.end] }).sorted()
    for (lower, upper) in zip(bounds, bounds.dropFirst()) {
      let lanes = Set(
        publics.filter { $0.window.start <= lower && upper <= $0.window.end }.map(\.lane))
      // A gap with no public lane is never a "best time" — it is the absence of one.
      guard !lanes.isEmpty else { continue }
      windows = merged(
        windows,
        PublicWindow(window: TimeWindow(start: lower, end: upper), publicLanes: lanes.count))
    }
    // `max(by:)` keeps the LAST maximal element and Python's `max` keeps the FIRST, so the
    // comparison is strict and the scan is written out: `windows` is chronological, so a
    // strict `>` gives the earliest of a tie without a second sort key.
    var best: PublicWindow?
    for window in windows where window.publicLanes > (best?.publicLanes ?? 0) { best = window }
    return best
  }

  private func clippedPublicHolds(within: TimeWindow?) -> [(lane: Int, window: TimeWindow)] {
    strips.flatMap { strip in
      strip.holds.filter(\.isPublic).compactMap { hold in
        clip(hold.window, to: within).map { (strip.lane, $0) }
      }
    }
  }

  /// Append `window`, merging it into the previous one when the count is equal and the two
  /// touch — otherwise a plan stored in half-hour rows would report a best time of 30 minutes.
  private func merged(_ windows: [PublicWindow], _ window: PublicWindow) -> [PublicWindow] {
    guard let last = windows.last, last.publicLanes == window.publicLanes,
      last.window.end == window.window.start
    else { return windows + [window] }
    return Array(windows.dropLast()) + [
      PublicWindow(
        window: TimeWindow(start: last.window.start, end: window.window.end),
        publicLanes: window.publicLanes
      )
    ]
  }

  /// `club_roster`, for THIS weekday.
  ///
  /// Python's roster spans the whole plan because a `LanePlan` carries every weekday; a
  /// `lane_day` row is one weekday by construction, so this is Python's roster filtered to
  /// `weekday` — the generated fixture asserts exactly that equality. Holds are regrouped by
  /// (owner, window) to undo the export's per-lane explosion, which reconstitutes the lane
  /// SET the reservation was stored with.
  public func clubRoster() -> [ClubSlot] {
    var lanesByHold: [String: (club: String, window: TimeWindow, lanes: [Int])] = [:]
    for strip in strips {
      for hold in strip.holds where !hold.isPublic {
        let club = hold.owner ?? hold.accessKind
        let key = "\(club)|\(hold.window.start.hhmm)|\(hold.window.end.hhmm)"
        var entry = lanesByHold[key] ?? (club, hold.window, [])
        entry.lanes.append(strip.lane)
        lanesByHold[key] = entry
      }
    }
    return lanesByHold.values
      .map {
        ClubSlot(club: $0.club, weekday: weekday, window: $0.window, lanes: $0.lanes.sorted())
      }
      .sorted(by: clubSlotOrder)
  }
}

/// `span` intersected with `within` (all of `span` when there is no bound), or nil when the
/// two do not overlap. Half-open at both ends, so a touching pair yields nil rather than an
/// empty window that would then be drawn.
private func clip(_ span: TimeWindow, to within: TimeWindow?) -> TimeWindow? {
  guard let within else { return span }
  let lower = max(span.start, within.start)
  let upper = min(span.end, within.end)
  return lower < upper ? TimeWindow(start: lower, end: upper) : nil
}

private func windowOrder(_ lhs: TimeWindow, _ rhs: TimeWindow) -> Bool {
  (lhs.start, lhs.end) < (rhs.start, rhs.end)
}

/// The roster's order: owner, then weekday, then time, then the lane set — Python's exact
/// sort key. The lane tiebreak is LEXICOGRAPHIC (`[1, 3]` before `[2]`), which is what
/// comparing the tuples does in Python and what comparing counts would not.
private func clubSlotOrder(_ lhs: ClubSlot, _ rhs: ClubSlot) -> Bool {
  let left = (lhs.club, lhs.weekday, lhs.window.start, lhs.window.end)
  let right = (rhs.club, rhs.weekday, rhs.window.start, rhs.window.end)
  if left != right { return left < right }
  return lhs.lanes.lexicographicallyPrecedes(rhs.lanes)
}

// MARK: - Decoding the stored row

extension LaneDay {
  /// Decodes one `lane_day` row's `strips` / `unresolved_lanes` documents.
  ///
  /// Returns nil for a malformed document rather than an empty plan: an empty plan reads as
  /// "no lane is reserved", which is a claim, while a decode failure is the absence of one —
  /// and the caller degrades to the ribbon that says the split is not published.
  public static func decode(
    basinID: String,
    weekday: Int,
    laneCount: Int,
    strips: String,
    unresolvedLanes: String,
    confidence: String
  ) -> LaneDay? {
    guard let stripData = strips.data(using: .utf8),
      let wire = try? JSONDecoder().decode([WireStrip].self, from: stripData),
      let laneData = unresolvedLanes.data(using: .utf8),
      let lanes = try? JSONDecoder().decode([Int].self, from: laneData)
    else { return nil }
    var decoded: [LaneStrip] = []
    for strip in wire {
      guard let holds = strip.decodedHolds() else { return nil }
      decoded.append(LaneStrip(lane: strip.lane, holds: holds))
    }
    return LaneDay(
      basinID: basinID,
      weekday: weekday,
      laneCount: laneCount,
      strips: decoded.sorted { $0.lane < $1.lane },
      unresolvedLanes: Set(lanes),
      confidence: confidence
    )
  }

  private struct WireStrip: Decodable {
    struct Segment: Decodable {
      let start: String
      let end: String
      let access: String
      let owner: String?
    }

    let lane: Int
    let segments: [Segment]

    func decodedHolds() -> [LaneHold]? {
      var holds: [LaneHold] = []
      for segment in segments {
        guard let start = TimeOfDay(hhmm: segment.start), let end = TimeOfDay(hhmm: segment.end)
        else { return nil }
        holds.append(
          LaneHold(
            window: TimeWindow(start: start, end: end),
            accessKind: segment.access,
            owner: segment.owner
          )
        )
      }
      return holds
    }
  }
}

extension TimeOfDay {
  /// Minutes since midnight, as the boundary sets in this file carry them.
  public init(minutesSinceMidnight: Int) {
    self.init(hour: minutesSinceMidnight / 60, minute: minutesSinceMidnight % 60)
  }
}

// MARK: - What a session line says about its lanes

extension LaneAvailability {
  /// "5 of 8 lanes open" — the one line a session row shows about its lane split.
  ///
  /// It lives here rather than in the view for the reason every other sentence in this package
  /// does: it is a rule with an edge case that matters. Zero public lanes is NOT rendered as
  /// "0 of 8 open", which reads as a measurement; it is rendered as "no lanes open to the
  /// public", which is what the plan actually says. And a `partial` count says so, because a
  /// count drawn from a plan with unreadable lanes is a floor, not a number.
  ///
  /// FOUR KEYS, NOT TWO PLUS A SUFFIX. S3b built the partial variant by appending "— some
  /// lanes unreadable" to a finished sentence, which is a sentence glued onto a sentence: the
  /// clause lands in a different place in German and cannot be appended at all in Polish
  /// without re-inflecting what precedes it. Each of the four is a whole translatable unit.
  public func summary(_ format: Format) -> Message {
    if publicLanes == 0 {
      return Message(partial ? "lane.nonePublic.partial" : "lane.nonePublic")
    }
    return Message(
      partial ? "lane.publicOfTotal.partial" : "lane.publicOfTotal",
      ["public": format.integer(publicLanes)],
      count: laneCount)
  }
}

extension SwimOption {
  /// The lane line for this session, or nil when the basin publishes no plan.
  ///
  /// Nil is a state, not an empty string: a pool with no Belegungsplan must never render as a
  /// pool with no free lanes, which is the invariant the whole ribbon vocabulary protects.
  ///
  /// IT IS NOT `laneAvailability.summary`, and the difference is a temporal-claim bug caught on
  /// a real screen. `lane_availability` is the split AT THE QUERIED INSTANT — that is what the
  /// web's field means and the golden parity depends on it — so at 04:00 it reports zero public
  /// lanes for a session that starts at 06:00, and the row printed "no lanes open to the
  /// public" beside "Opens 06:00". The instant is a fact about the clock; the row's line is a
  /// fact about the SESSION. So the summary uses the live split only while the session is
  /// actually RUNNING, and otherwise the split the session OPENS with, which is true whenever
  /// it is read.
  ///
  /// `isToday` IS REQUIRED, and leaving it out was the half-fix. `openAtQueryTime` is pure
  /// time-of-day containment (`Clock.openAtQueryTime`), and off today the app queries the store
  /// at the fixed `DAY_MOMENT` of 12:00 — so off today `openAtQueryTime` means "covers midday",
  /// not "is running now", which is true of essentially every long session. Traced against the
  /// committed store: `hallenbad-city`/`city-50m` on 2026-09-07 runs 06:00–22:00 with 5 of 6
  /// public lanes at 12:00 and 6 of 6 at its 06:00 opening, so a row two weeks out printed
  /// "5 of 6 lanes open" where this rule says "6 of 6". A wall-clock split is only ever a
  /// claim about the day the user is standing in (invariant E1).
  public func laneSummary(isToday: Bool, format: Format) -> Message? {
    guard laneAvailability != nil || laneTimeline != nil else { return nil }
    if isToday, openAtQueryTime, let live = laneAvailability { return live.summary(format) }
    guard let opening = laneTimeline?.segments.first?.availability else {
      return laneAvailability?.summary(format)
    }
    return opening.summary(format)
  }

  /// Whether this session has anything to say BELOW its time and basin.
  ///
  /// A `SessionLine` is two ranks: when and where on the first line, what it costs and what is
  /// left on the second. The second line is absent entirely when the source published none of
  /// it — an always-present row would still cost its spacing, which showed up as a ragged
  /// rhythm down the card.
  ///
  /// IT LIVES HERE RATHER THAN IN THE VIEW, and that is the whole reason this function exists:
  /// the app target is outside the CRAP gate and a SwiftUI body cannot be unit-tested, so the
  /// predicate deciding whether a whole line of a row appears was a rule nothing measured. It
  /// reads the same three facts in the same order, and `laneSummary` above is one of them —
  /// which is also why `isToday` and `format` are threaded in rather than assumed.
  public func hasSupportingFacts(isToday: Bool, format: Format) -> Bool {
    laneSummary(isToday: isToday, format: format) != nil || price != nil || isFairWeatherOnly
  }
}

extension LaneHold {
  /// What VoiceOver reads for this hold, on this lane.
  ///
  /// In the PACKAGE rather than in the chart that draws it, for the reason every other sentence
  /// in this app is: the app target is outside the CRAP gate and a SwiftUI body cannot be
  /// driven by a test, so a sentence written there is a sentence nothing checks — and this one
  /// has to be day-agnostic (the lane panel is reachable from any date in the horizon), which
  /// is exactly the property this project has already got wrong twice.
  ///
  /// The HOLDER is the one part that is not ours: a club's name is a proper noun and rides
  /// through verbatim, while "open to the public" — the fallback for an unheld lane — is our
  /// sentence and comes from the catalog. Composing them in Swift would put an English clause
  /// inside a translated one.
  public func spoken(lane: Int, in localized: Localized) -> Message {
    Message(
      "lane.spoken",
      [
        "lane": localized.format.integer(lane),
        "start": window.start.hhmm,
        "end": window.end.hhmm,
        "holder": owner ?? localized(Message("lane.openToPublic")),
      ])
  }
}
