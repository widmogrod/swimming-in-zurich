// KeyboardWarmup.swift — pay the keyboard's first-show cost before the reader taps search.
//
// The first keyboard a process shows is the expensive one: UIKit loads the input system, the
// layout, the dictionary and the autocorrect machinery, and it does it on the main thread at
// the moment the field takes focus. The search control is the first thing on this screen that
// asks for a keyboard, so the first tap on it used to pay that whole bill as a pause with
// nothing on screen to explain it. Measured on the simulator (Time Profiler, Debug): opening
// search costs the app ~120 ms of main-thread work, and every sample of it is UIKit's
// keyboard bring-up — none of it is this app's code. A phone pays more, and a debug build on a
// phone pays more still.
//
// The trick is the one Apple's own apps use: a field nobody sees becomes first responder and
// resigns it in the same turn of the run loop. The keyboard never appears, but everything it
// needs is loaded, so the reader's first tap gets the keyboard the SECOND time costs. Same
// shape as `MapWarmup`, for the same reason: after the answer is on screen, off its critical
// path, once per process.
//
// Behind `Lab.keyboardWarmup`, so the two can be felt side by side on a phone.

import UIKit

@MainActor
enum KeyboardWarmup {
  private static var warmed = false

  /// Load the keyboard once, after a breath, without showing it.
  static func warm() async {
    guard !warmed else { return }
    try? await Task.sleep(for: .milliseconds(900))
    guard !warmed, let window = keyWindow else { return }
    warmed = true
    let field = UITextField(frame: .zero)
    // Invisible, not hidden: a hidden view refuses first responder, and the whole point is to
    // take it. Zero size and zero alpha keep it off screen and out of the accessibility tree.
    field.alpha = 0
    field.isAccessibilityElement = false
    window.addSubview(field)
    field.becomeFirstResponder()
    field.resignFirstResponder()
    field.removeFromSuperview()
  }

  private static var keyWindow: UIWindow? {
    UIApplication.shared.connectedScenes
      .compactMap { $0 as? UIWindowScene }
      .flatMap(\.windows)
      .first(where: \.isKeyWindow)
  }
}
