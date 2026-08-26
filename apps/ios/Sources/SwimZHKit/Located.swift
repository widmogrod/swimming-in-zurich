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
public enum LocationRefusal: String, Equatable, Hashable, Sendable {
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
