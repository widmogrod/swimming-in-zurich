// The app target: SwiftUI views and nothing else.
//
// Every rule lives in `SwimZHKit`, which is measured by tests and (from S2b) by the CRAP
// gate. This target is kept deliberately too thin to hide one — the same stance
// `vitest.config.ts` takes when it excludes the browser entrypoints while `appdata.ts`
// carries the rules.

import SwiftUI
import SwimZHKit

@main
struct SwimZHApp: App {
  init() {
    // As early as the app can. Apple measures launch as time-to-first-frame, so without
    // this the official number would stop when the empty shell is drawn and the store
    // load — the slow part, and the part the user is actually waiting for — would fall
    // outside it. `LaunchSignpost` extends the measurement over it; `TodayView` closes it
    // when real data is on screen. See `Sources/SwimZHKit/LaunchSignpost.swift`.
    LaunchSignpost.shared.start()
  }

  /// The reader's language and regional formatting, resolved ONCE from the system's preference
  /// list and injected. One `Localized` for the whole app: a view that built its own would be a
  /// second answer to "which language is this", and the two would eventually differ.
  private let localized = Localized.current

  var body: some Scene {
    WindowGroup {
      TodayView()
        .environment(\.localized, localized)
    }
  }
}
