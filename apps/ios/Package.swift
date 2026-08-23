// swift-tools-version: 6.2
//
// SwimZHKit — the whole rule layer of the iOS app, testable headlessly by `swift test`
// with no simulator and no network. The Xcode app target (App/SwimZH.xcodeproj) owns only
// SwiftUI views and depends on this package, so every measured rule lives here: this
// package is the plan's `appdata.ts`.
//
// The bundled pre-resolved store rides as a PACKAGE resource, so `Bundle.module` finds it
// under `swift test` on the host AND inside the app bundle on device. There is no
// third-party runtime dependency: SQLite is Apple's own `libsqlite3` via `import SQLite3`.

import PackageDescription

let package = Package(
  name: "SwimZHKit",
  defaultLocalization: "en",
  // macOS is here only so `swift test` can run the rule layer headlessly on the host.
  // 15.4 rather than 15.0 because `isolated deinit` — which the SQLite handle REQUIRES,
  // since `OpaquePointer` is not `Sendable` and a nonisolated deinit therefore cannot
  // touch it — is available from 15.4.
  platforms: [.iOS(.v26), .macOS("15.4")],
  products: [
    .library(name: "SwimZHKit", targets: ["SwimZHKit"])
  ],
  targets: [
    .target(
      name: "SwimZHKit",
      resources: [.copy("Resources/ios.sqlite")]
    ),
    .testTarget(
      name: "SwimZHKitTests",
      dependencies: ["SwimZHKit"],
      // Read from disk by path (see RepoFixtures), not bundled — the generated contracts
      // must be the repository's originals, never a copy that can go stale.
      exclude: ["Fixtures"]
    ),
  ]
)
