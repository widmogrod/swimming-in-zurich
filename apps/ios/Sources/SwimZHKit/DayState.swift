// DayState.swift — the five ways a pool-day can have no sessions, each said as itself.
//
// The invariant this file exists to keep: A SCHEDULE-LESS POOL IS NEVER "CLOSED". `closed` is
// a claim the source made; `awaiting_scrape`, `no_source` and `open_unscheduled` are three
// different admissions that we do not know its hours. Collapsing any of them into "closed"
// tells a swimmer a pool is shut when it may well be open — the one thing the data model
// forbids, and the reason the four-state vocabulary exists at all.
//
// The FIFTH state is the client's own and has no `day` row behind it: a date past the store's
// `horizon_end` (invariant E2). It is distinct from all four, because "we have not published
// answers that far ahead" is not "closed" either.
//
// S2 put this mapping in `TodayView.statusLabel`. It moves here — extended, not duplicated —
// for the reason the whole plan is built on: a rule in the app target is a rule outside the
// CRAP gate, unreachable by `swift test`, and untestable through a view body. `TodayView`
// now reads this.

import Foundation

/// Why a pool has no sessions on a day — the four-state `StatusOut` vocabulary plus the
/// client-side horizon state.
public enum DayState: Equatable, Hashable, Sendable {
  /// The source says it is shut, and `reason` says which kind of shut.
  case closed(ClosureReason)
  /// A scrapeable pool whose schedule has not been fetched yet.
  case awaitingScrape
  /// Not scrapeable at all — there is no timetable source to fetch.
  case noSource
  /// Its page states a season it is inside, but publishes no hours.
  case openUnscheduled
  /// Past `meta.horizon_end` — we have simply not published answers this far ahead (E2).
  case beyondHorizon
  /// A status string this binary has never seen. A store built by a newer export can carry
  /// one, and the honest answer is to say so rather than to pick the nearest known state —
  /// which, given the vocabulary, would mean guessing "closed".
  case unrecognised(String)
}

/// The classified reasons a `closed` day carries (`StatusOut.closure_code`).
public enum ClosureReason: Equatable, Hashable, Sendable {
  case outOfSeason
  case noSessions
  /// The source stated a closure we could not classify. It carries the pool's OWN WORDS —
  /// `detail_params["text"]`, verbatim and untranslated — because a paraphrase of a closure
  /// nobody classified is a fact we would be inventing. `dayStateLabel` quotes it.
  case unmapped(text: String)
  /// A classified code this binary does not know (again: a newer store).
  case other(String)
  /// `closure_code` was absent on a `closed` row — the export always writes one, so this is
  /// a malformed row, not a state to render as an ordinary closure.
  case unstated
}

/// The `(status, closure_code, detail_params)` triple the store carries, as a state.
///
/// `detailParams` is not decoration: an `unmapped` closure has no classified reason, so the
/// pool's own sentence in `detail_params["text"]` is the ONLY thing that can be said about it.
/// Dropping it would leave the UI asserting "closed" with nothing behind the claim.
public func dayState(
  status: String,
  closureCode: String?,
  detailParams: [String: String] = [:]
) -> DayState {
  switch status {
  case "closed": return .closed(closureReason(closureCode, detailParams))
  case "awaiting_scrape": return .awaitingScrape
  case "no_source": return .noSource
  case "open_unscheduled": return .openUnscheduled
  default: return .unrecognised(status)
  }
}

private func closureReason(_ code: String?, _ params: [String: String]) -> ClosureReason {
  switch code {
  case "out_of_season": return .outOfSeason
  case "no_sessions": return .noSessions
  case "unmapped":
    return .unmapped(text: params["text"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "")
  case .some(let other) where !other.isEmpty: return .other(other)
  default: return .unstated
  }
}

/// The state of one pool-day, horizon included.
///
/// The horizon check comes FIRST and applies to the whole day, not to one pool: past
/// `horizon_end` there are no rows at all, so a per-pool status could only ever be an absence
/// misread as a closure.
public func dayState(
  status: PoolDayStatus?,
  on day: String,
  horizon: StoreMetadata
) -> DayState {
  guard horizon.covers(day: day) else { return .beyondHorizon }
  guard let status else { return .unrecognised("") }
  return dayState(
    status: status.status,
    closureCode: status.closureCode,
    detailParams: status.detailParams
  )
}

/// The English sentence for a state.
///
/// English is temporary and deliberate, exactly as `DayWarning.rendered` is: it makes the
/// distinctness assertable now, and S4 replaces it with a catalog lookup keyed off the state.
/// What must survive that replacement is the property the test asserts — no state that is not
/// `closed` may render a sentence that says the pool is closed.
public func dayStateLabel(_ state: DayState) -> String {
  switch state {
  case .closed(let reason): return closedLabel(reason)
  case .awaitingScrape: return "Hours not published yet"
  case .noSource: return "No schedule source for this pool"
  case .openUnscheduled: return "Open, but hours are not listed"
  case .beyondHorizon: return "Beyond the published horizon"
  case .unrecognised(let status):
    // Not "closed", and not a fabricated sentence either: the raw status is the honest
    // minimum, and it is also the i18n key S4 renders from.
    return status.isEmpty ? "State not stated" : status
  }
}

private func closedLabel(_ reason: ClosureReason) -> String {
  switch reason {
  case .outOfSeason: return "Closed — outside its season"
  // NOT "Closed today". A `day` row exists for every date in the horizon, and ghost/closed rows
  // are built without reference to which day is today — so "today" here was a temporal claim
  // rendered on every future date the strip can reach. The closure code says "no sessions"; that
  // is what this says, and it is true on whatever day the row belongs to.
  case .noSessions: return "Closed — no sessions"
  case .unmapped(let text):
    // The pool's own sentence, quoted rather than paraphrased — which is what makes the
    // `unmapped` arm's promise true instead of merely stated. A row that carries none says so
    // plainly; it never borrows a classified-sounding reason we do not have.
    return text.isEmpty ? "Closed — reason not classified" : "Closed — “\(text)”"
  case .other(let code): return "Closed — \(code)"
  case .unstated: return "Closed — reason not stated"
  }
}

extension DayState {
  /// Whether this state is a CLAIM that the pool is shut. False for every schedule-less state
  /// and for the horizon state — which is what the UI keys its wording, its icon and its
  /// grouping off, so the distinction cannot be lost in a view.
  public var isClosureClaim: Bool {
    if case .closed = self { return true }
    return false
  }

  /// The three ghost states: we do not know this pool's hours. Distinct from a closure, and
  /// distinct from the horizon state (which is about the DATE, not the pool).
  public var isUnknownHours: Bool {
    switch self {
    case .awaitingScrape, .noSource, .openUnscheduled, .unrecognised: return true
    case .closed, .beyondHorizon: return false
    }
  }
}
