// Located.swift — what the app knows about where the reader is, and what it may claim from it.
//
// WHY THIS EXISTS AT ALL, AND WHY IT DID NOT. `Filters.swift` carried this note since S3a:
//
//     There is deliberately NO device location in S3a. Core Location would be the slice's only
//     new framework dependency and the plan rules out MapKit precisely to keep the offline
//     property, so "use my location" is left unbuilt rather than half-built.
//
// That reasoning was sound and its premise is now gone: the map mode links MapKit, so Core
// Location is no longer "the only new framework", and the offline property was never actually
// at stake — GNSS is a RECEIVER, and a fix needs no network at all. What remained was a phone
// app measuring every distance from Zürich Hauptbahnhof and calling the result "nearest first".
//
// THE INVARIANT THIS FILE PROTECTS, and it is the app's oldest one wearing new clothes. A pool
// whose schedule we do not have must never render as "closed"; a POSITION we do not have must
// never render as a distance. Quietly measuring from the station while the reader believes they
// are being measured from their phone is the same class of lie — an unknown presented as a
// fact — and it is the more dangerous one, because a wrong distance still looks like a distance.
//
// So `Filters.place` is only ever assigned a REAL coordinate (`devicePlace`), the way a fix was
// obtained rides along with it (`PlaceSource`), and every state that is not a fix has a sentence
// of its own rather than a silent fallback (`locationNote`).
//
// The web solved the same problem first and this is a port of its shape, not an invention:
// `components/placetypeahead.ts` emits `source: 'geolocation' | 'preset' | 'fallback'` with a
// `reason`, commented "so the UI never implies a precision it does not have". ONE DELIBERATE
// DIVERGENCE, noted at `locationNote`: the web falls back to a preset when geolocation is
// refused, and this does not.

import Foundation

/// How a `Place`'s coordinates were arrived at.
///
/// It is on the `Place` rather than beside it because the pair travels: a label saying "My
/// location" over a point that came from the station would be exactly the claim this file
/// exists to prevent, and keeping them in one value makes that combination unconstructible.
public enum PlaceSource: String, Equatable, Hashable, Sendable {
  /// One of the three curated points. Its coordinates are ours and always available.
  case preset
  /// The phone's own position, as of the moment it was taken.
  case device
}

/// Why the phone's position is not available.
///
/// THREE CAUSES, NOT ONE, because the remedy differs and a reader who is told the wrong one is
/// sent somewhere that cannot help. `denied` is fixed in Settings by this reader; `restricted`
/// cannot be fixed by them at all (Screen Time, or a managed device); `unavailable` is not about
/// permission — Location Services is off device-wide, or no fix arrived — and Settings for this
/// app would show nothing wrong.
///
/// `CaseIterable` IS LOAD-BEARING, not a convenience. Three tests sweep "every refusal" — that
/// each has its own sentence, that none installs a place, that each sentence is really in the
/// catalog — and they used to sweep a hand-written array literal. A fourth cause added here
/// (`precise-only`, say) would have compiled, shipped, and rendered `place.refused.preciseOnly`
/// as itself on screen, where a raw catalog key reads as a design choice rather than as a
/// missing string — with every gate green, because the literal did not know about it.
public enum LocationRefusal: String, Equatable, Hashable, Sendable, CaseIterable {
  case denied
  case restricted
  case unavailable
}

/// What the app knows about where the reader is.
public enum LocationState: Equatable, Sendable {
  /// Never asked. The reader has not requested it and iOS has shown no prompt.
  case idle
  /// Asked, and waiting. A REAL state rather than a gap between two others: a first fix can
  /// take seconds indoors, and the screen must be able to say so.
  case locating
  case fixed(GeoPoint)
  case refused(LocationRefusal)

  /// Every state, for the sweeps that must hold across all of them.
  ///
  /// A hand-maintained list because `fixed` carries a coordinate, so the compiler cannot
  /// synthesise `CaseIterable` here. It is still better than the literals it replaces, for two
  /// reasons: it is ONE list rather than one per test, so a new state is added in a single
  /// place; and it fans out over `LocationRefusal.allCases`, which is the arm that actually
  /// grows — a fourth refusal reaches every sweep with no edit at all.
  ///
  /// `fixed` needs a coordinate, and the caller supplies it: any point will do, since no rule
  /// in this file reads the value.
  public static func allStates(fixedAt point: GeoPoint) -> [LocationState] {
    [.idle, .locating, .fixed(point)] + LocationRefusal.allCases.map(LocationState.refused)
  }
}

extension Places {
  /// The reader's own position as a `Place`.
  ///
  /// A fixed id rather than one derived from the coordinates. It is the SAME place each time —
  /// "where I am" — and an id that changed with every metre walked would make `Filters`
  /// unequal on every fix, reloading an answer that has not changed.
  public static func me(at point: GeoPoint) -> Place {
    Place(id: devicePlaceID, label: .key("place.myLocation"), point: point, source: .device)
  }
}

/// The id `Places.me` uses. Public so the app can tell "the reader is on their own location"
/// from "the reader is on a preset" without reaching for the label, which is localised.
public let devicePlaceID = "me"

/// The place a location state should install, or nil when there is nothing honest to install.
///
/// NIL ON EVERY STATE BUT `.fixed`, and that is the whole invariant. It is tempting to install
/// something while `.locating` — a spinner needs somewhere to live, and the reader has just
/// asked — but there is no coordinate yet, so anything installed would be a position we do not
/// have. Leaving the previous place is not a compromise: it is still correctly LABELLED (the
/// station says "Zürich HB"), so nothing on screen is false while the fix is on its way.
public func devicePlace(_ state: LocationState) -> Place? {
  guard case .fixed(let point) = state else { return nil }
  return Places.me(at: point)
}

/// The sentence the place picker shows under its "my location" row, or nil when there is
/// nothing to explain.
///
/// Nil for `.idle` (nothing has happened yet) and for `.fixed` (it worked; the row's own label
/// says so). Every other state gets words, which is THE DIVERGENCE FROM THE WEB. `placetypeahead
/// .ts` responds to a refusal by moving the reader to a preset and attaching a `reason`; here a
/// refusal moves nothing at all. On the web there may be no place selected, so a fallback is the
/// difference between an answer and a dead end. This app always has one — the station by
/// default — so silently swapping the reader's chosen place for another would be a surprise
/// where saying "that did not work, and here is why" is an explanation.
public func locationNote(_ state: LocationState) -> Message? {
  switch state {
  case .idle, .fixed: return nil
  case .locating: return Message("place.locating")
  case .refused(let refusal): return Message("place.refused.\(refusal.rawValue)")
  }
}

/// How old a fix may be before the app must say so, out loud, wherever it is presented.
///
/// TEN MINUTES, and the number is a judgement rather than a measurement, so here is the
/// reasoning it has to survive. The defect it guards is real and not hypothetical:
/// `refreshIfUsing` re-fixes on every return to the foreground, and when that refresh is
/// refused or times out the PREVIOUS fix stays installed — correctly, because a position that
/// was true half an hour ago beats no position and beats silently reverting to the station.
/// What was missing is that nothing anywhere said it was old, so a coordinate taken before a
/// tram ride went on labelling itself "My location" and every distance drawn from it read as
/// current.
///
/// Ten minutes is roughly 800 m at a walking pace and around 3 km on a tram — both larger than
/// the gaps between the central pools, so both are enough to reorder a nearest-first list and
/// to change the answer to "within 1 km". Under ten minutes the error is smaller than the
/// distances themselves are rendered to, and a caption would be pedantry.
///
/// It is deliberately far shorter than `TempReading.stalenessLimit` (six hours) and matches the
/// web's OCCUPANCY limit instead: water temperature is measured a few times a day and a reader
/// does not move it, whereas a position is invalidated by the reader themselves. Different
/// speeds, not different standards.
///
/// A phone on a desk is not nagged by this: the sentence appears ONLY in the place picker's
/// "use my location" row, which is the one screen whose whole subject is where distances are
/// measured from. Nothing in the list, and no badge, grows out of it.
public let positionStalenessLimit: TimeInterval = 10 * 60

/// How old the installed fix is — but ONLY when that age has to be shown. Nil means say nothing.
///
/// KEYED ON WHEN THE FIX WAS TAKEN, never on `LocationState`, and that is the whole rule. The
/// case this exists for is precisely the one where the state is NOT `.fixed`: a foreground
/// refresh that is refused leaves `state == .refused(.unavailable)` while the place installed
/// from the earlier fix stays on screen. A staleness test gated on `.fixed` would go quiet in
/// exactly the situation it was written for.
///
/// Nil for a fix in the FUTURE, on the same principle as `liveWaterCaveat`: our clock and the
/// one that stamped it disagree, and "taken -3 min ago" is worse than saying less. Nil for no
/// fix at all — there is no position, so there is no age to report and no claim to correct.
///
/// Strictly greater than the limit, matching `TempReading.isStale`: at exactly ten minutes the
/// fix is still inside the window this file calls current.
public func stalePositionAge(fixedAt: Date?, at now: Date) -> TimeInterval? {
  guard let fixedAt else { return nil }
  let age = now.timeIntervalSince(fixedAt)
  guard age > positionStalenessLimit else { return nil }
  return age
}

/// The sentence for an old fix — "taken 25 min ago" — or nil while it is still current.
///
/// It reuses the app's EXISTING age vocabulary rather than inventing a second one: the same
/// `humanizedAge` that renders `detail.liveMeasuredAgo` for the live water temperature, which
/// is the identical problem (a measurement presented long after it was taken) already solved
/// once. Only the verb differs — a temperature is measured, a position is taken — so the
/// catalog gains one key and no new grammar.
public func stalePositionNote(fixedAt: Date?, at now: Date, in localized: Localized) -> Message? {
  guard let age = stalePositionAge(fixedAt: fixedAt, at: now),
    let rendered = humanizedAge(age, localized)
  else { return nil }
  return Message("place.fixedAgo", ["age": rendered])
}

/// Whether the reader can usefully be sent to Settings about this.
///
/// Only `denied`, and the distinction is the point of `LocationRefusal` having three cases.
/// Offering "Open Settings" for `restricted` sends someone to a switch they are not allowed to
/// move, and for `unavailable` to a page that will look entirely correct.
public func settingsCanFix(_ state: LocationState) -> Bool {
  state == .refused(.denied)
}

/// Whether a fix should be taken WITHOUT the reader asking again.
///
/// The rule that keeps the choice sticky across launches without ever prompting at launch. A
/// cold-start permission dialog, before the reader has asked this app for anything, is the
/// pattern that teaches people to press Don't Allow — and this app's whole promise is an answer
/// the moment it opens.
///
/// So: only if they chose their location before (`preferred`), and only if iOS will not prompt
/// (`alreadyAuthorised`). Either one alone is not enough — the first without the second is the
/// cold-start prompt, and the second without the first is taking a fix nobody asked for.
public func shouldLocateOnLaunch(preferred: Bool, alreadyAuthorised: Bool) -> Bool {
  preferred && alreadyAuthorised
}
