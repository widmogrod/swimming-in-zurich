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

@MainActor
@Observable
final class LocationSource {
  /// What the app knows about where the reader is. The rules that read this are the kit's.
  private(set) var state: LocationState = .idle

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

  /// Wait for the first usable update, then stop.
  ///
  /// The order of the checks is the contract. `authorizationDenied` and `authorizationRestricted`
  /// are asked BEFORE `location`, because a denied update can still carry a stale coordinate and
  /// using it would be reporting a position the reader has just refused to give.
  private func listen() async {
    do {
      for try await update in CLLocationUpdate.liveUpdates(.default) {
        if update.authorizationDenied || update.authorizationDeniedGlobally {
          return finish(.refused(.denied))
        }
        if update.authorizationRestricted { return finish(.refused(.restricted)) }
        if let location = update.location {
          return finish(
            .fixed(
              GeoPoint(
                lat: location.coordinate.latitude, lon: location.coordinate.longitude)))
        }
        // `locationUnavailable` is not fatal on its own — it is how the sequence reports "no
        // fix YET", and it arrives routinely before the first one. Only a sequence that ENDS
        // without a fix is an answer, which is the `unavailable` below.
        if update.authorizationRequestInProgress { continue }
      }
      finish(.refused(.unavailable))
    } catch {
      // The sequence itself failed. It is not a denial and must not be worded as one: the
      // reader would be sent to a Settings page showing nothing wrong.
      finish(.refused(.unavailable))
    }
  }

  private func finish(_ outcome: LocationState) {
    state = outcome
  }

  /// Stop using the device's position, without forgetting that permission was granted.
  func stopUsing() {
    preferred = false
    state = .idle
  }
}
