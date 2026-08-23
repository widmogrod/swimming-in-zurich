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
  var body: some Scene {
    WindowGroup {
      TodayView()
    }
  }
}
