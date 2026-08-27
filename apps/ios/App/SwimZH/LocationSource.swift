// LocationSource.swift — the phone's own position, as a state the screen can render.
//
// I/O, so it lives in the app target and NOT in `SwimZHKit`: a `CLLocationManager` is a device,
// and the package is the part that has to be answerable to a test without one. Every DECISION
// this file could have made lives in `Located.swift` instead — what a fix may be turned into,
// what each refusal says, whether Settings can help, whether to locate at launch — and what is
// left here is the part that genuinely cannot be tested off a device: asking, and waiting.
//
// WHY THIS IS NOT A NETWORK CALL, since the app's central promise is that it answers offline
// and a source lint fails the build if `URLSession` or `Network` appears in either target.
// GNSS is a RECEIVER: the phone listens to satellites and computes a position locally. Wi-Fi
// and cell databases make a first fix faster when they are available, and their absence makes
// it slower, never wrong. Nothing here reaches the internet, and nothing leaves the device —
// the fix becomes a `Place` in memory and is never written anywhere.
//
// IT ALWAYS ANSWERS, and that took a review to notice. The first version returned only on a
// denial, a restriction, a fix, or the sequence ending — and `CLLocationUpdate.liveUpdates()`
// ends on none of those indoors, in airplane mode, or on a simulator with no position set. It
// simply keeps emitting updates that carry no location. Every consequence of that compounds:
// `state` stays `.locating` so the row stays disabled forever, `isListening` stays true so no
// later attempt can recover it, GNSS stays powered, and — worst — `locate()` never returns,
// which starved the store refresh that awaited it at launch. A control that can wedge is worse
// than one that fails, because the reader has no way to learn that it did.
//
// ONE FIX, NOT A STREAM. `CLLocationUpdate.liveUpdates()` is a continuous sequence and this
// takes the first usable element and stops. A list that re-sorted itself while the reader
// walked would move a row out from under a finger already reaching for it — Apple Maps does not
// reorder search results as you move either — and a continuous listener is also the difference
// between a negligible battery cost and a visible one. The fix is refreshed when the reader
// asks again, and on returning to the foreground, which is when a stale one is most likely.

import CoreLocation
import Foundation
import SwiftUI
import SwimZHKit

/// How long the reader waits before the app admits it cannot place them.
///
/// Long enough for a cold GNSS fix outdoors, short enough that a control which is going to fail
/// says so while the reader is still looking at it. It is a ceiling, not a delay: an ordinary
/// fix arrives in well under a second and is not made to wait for this.
let locationDeadlineSeconds: Double = 12

/// What `TodayModel` needs from the phone's position — the seam that makes the ordering rules
/// around it testable.
///
/// IT EXISTS BECAUSE A TEST COULD NOT FAIL. `TodayModelTests.aLaterNamedPlaceBeatsAnEarlierFix`
/// drives the race the `placeGeneration` counter was added for: a fix that lands AFTER the
/// reader has chosen a named place must not overwrite it. Against a real `LocationSource` in a
/// simulator the fix comes back refused in milliseconds, so the test passed because
/// `devicePlace(.refused)` is nil — the neighbouring invariant — and never because the counter
/// held. Deleting `placeGeneration` left it green, which makes it a green gate for a rule it
/// does not exercise.
///
/// A double can hold the fix open across the reader's second tap, which is the only way to put
/// a REAL fix on the far side of that suspension. The pattern is this codebase's own, twice
/// over: `HTTPFetching` is injected into `StoreHost.refresh` so every refusal path is driven
/// without a network, and `LaunchMeasurement` exists so `LaunchSignpost`'s state machine is
/// provable with no MetricKit daemon. `LocationSource` already had every one of these members
/// in this shape; conforming cost it nothing.
@MainActor
protocol LocationFixing: AnyObject {
  var state: LocationState { get }
  /// When the held fix was taken, for `stalePositionNote`. Nil when there is none.
  var fixedAt: Date? { get }
  var preferred: Bool { get set }
  var isAuthorised: Bool { get }
  func locate() async
  func refreshIfUsing() async
  func stopUsing()
}

@MainActor
@Observable
final class LocationSource: LocationFixing {
  /// What the app knows about where the reader is. The rules that read this are the kit's.
  private(set) var state: LocationState = .idle

  /// When the fix the app is currently MEASURING FROM was taken, or nil if there has been none.
  ///
  /// It survives a failed refresh on purpose, and that is the whole reason it exists.
  /// `refreshIfUsing` runs on every return to the foreground; when it is refused or times out,
  /// `state` becomes a refusal but the `Place` installed from the earlier fix stays — a
  /// position that was true is better than none, and better than silently reverting to the
  /// station. What was missing is that nothing said it was old, so this timestamp is what
  /// `stalePositionAge` reads to decide whether the age has to be shown. Clearing it here on a
  /// refusal would throw away the only fact that makes the honest caption possible.
  ///
  /// An instant, never a coordinate: nothing about where the reader was is written down.
  private(set) var fixedAt: Date?

  /// Whether the reader has chosen to be measured from their own position.
  ///
  /// Persisted, because a choice that had to be remade on every launch is a choice most people
  /// make once and then stop using. One `Bool` in `UserDefaults.standard`, which the privacy
  /// manifest already declares (`CA92.1`, the app's own defaults in its own container) — the
  /// POSITION itself is never stored, only the preference.
  var preferred: Bool {
    didSet { UserDefaults.standard.set(preferred, forKey: Self.preferredKey) }
  }

  static let preferredKey = "swimzh.useMyLocation"

  /// Whether a fix is already being waited for, so a second tap cannot start a second listener.
  private var isListening = false

  private let manager = CLLocationManager()

  init() {
    preferred = UserDefaults.standard.bool(forKey: Self.preferredKey)
  }

  /// Whether iOS will show no prompt — the second half of `shouldLocateOnLaunch`.
  var isAuthorised: Bool {
    switch manager.authorizationStatus {
    case .authorizedWhenInUse, .authorizedAlways: return true
    default: return false
    }
  }

  /// Take a fix. Safe to call again; a second call while one is in flight is ignored.
  ///
  /// `.locating` is published FIRST and deliberately: the first fix indoors can take seconds,
  /// and a control that looks inert for three seconds is a control the reader presses twice.
  func locate() async {
    guard !isListening else { return }
    isListening = true
    state = .locating
    await listen()
    isListening = false
  }

  /// Called when the app comes back to the foreground: refresh a fix we already have, and never
  /// start one we do not. Coming back from the background is exactly when a position taken
  /// before a tram ride is most likely to be wrong — and also exactly the wrong moment to put a
  /// permission dialog in front of someone who has not asked for one.
  func refreshIfUsing() async {
    guard preferred, isAuthorised, case .fixed = state else { return }
    await locate()
  }

  /// Wait for the first usable update or for the deadline, whichever comes first.
  ///
  /// A RACE rather than a deadline checked inside the loop, because the loop is not guaranteed
  /// to spin: a sequence that emits nothing at all would never reach an `if Date() > deadline`
  /// on any iteration. Two children, first answer wins, the loser cancelled.
  private func listen() async {
    let outcome = await withTaskGroup(of: LocationState.self) { group in
      group.addTask { await Self.firstUpdate() }
      group.addTask {
        try? await Task.sleep(for: .seconds(locationDeadlineSeconds))
        return .refused(.unavailable)
      }
      let first = await group.next() ?? .refused(.unavailable)
      group.cancelAll()
      return first
    }
    // Stamped only on a fix, and only from the answer we are about to install — so the
    // timestamp and the coordinate it dates always come from the same update.
    if case .fixed = outcome { fixedAt = Date() }
    state = outcome
  }

  /// The first update that settles the question, or `unavailable` when the sequence ends
  /// without one.
  ///
  /// `nonisolated` and `static` so the task group's children need no hop back to the main actor
  /// and touch no mutable state — the only thing that crosses back is the `LocationState`.
  ///
  /// The order of the checks is the contract. `authorizationDenied` and `authorizationRestricted`
  /// are asked BEFORE `location`, because a denied update can still carry a stale coordinate and
  /// using it would be reporting a position the reader has just refused to give.
  private nonisolated static func firstUpdate() async -> LocationState {
    do {
      for try await update in CLLocationUpdate.liveUpdates(.default) {
        if update.authorizationDenied || update.authorizationDeniedGlobally {
          return .refused(.denied)
        }
        if update.authorizationRestricted { return .refused(.restricted) }
        if let location = update.location {
          return .fixed(
            GeoPoint(lat: location.coordinate.latitude, lon: location.coordinate.longitude))
        }
        // `locationUnavailable` is not fatal on its own — it is how the sequence reports "no
        // fix YET", and it arrives routinely before the first one. What ends the wait is a fix,
        // an authorisation answer, the sequence ending, or the deadline in `listen`.
      }
      return .refused(.unavailable)
    } catch {
      // The sequence itself failed. It is not a denial and must not be worded as one: the
      // reader would be sent to a Settings page showing nothing wrong.
      return .refused(.unavailable)
    }
  }

  /// Stop using the device's position, without forgetting that permission was granted.
  func stopUsing() {
    preferred = false
    state = .idle
    // The fix is no longer being measured from, so its age is no longer anything to report.
    // (Unlike a refusal, which leaves the place installed — see `fixedAt`.)
    fixedAt = nil
  }
}
