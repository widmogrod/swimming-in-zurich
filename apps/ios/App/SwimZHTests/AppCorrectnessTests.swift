// The four submission-correctness items, asserted against the BUILT bundle.
//
// Every one of these is cheap now and forced later, and every one fails in a place that is
// expensive to discover: a missing UIScene manifest means the app does not launch at all on
// iOS 27, a missing launch screen is a submission rejection, `UIRequiresFullScreen` is
// ignored from the iOS 27 SDK and only misleads whoever reads the plist next, and a missing
// `PrivacyInfo.xcprivacy` is an ITMS-91055 rejection that appears only at upload.
//
// They are asserted against `Bundle.main` rather than against the project file on purpose:
// the build settings that generate these keys (`INFOPLIST_KEY_..._Generation`) are one
// indirection away from the artifact, and the artifact is what Apple reads. This is also
// why the checks live in the app-hosted target — `swift test` never builds an app bundle.

import Foundation
import Testing

@testable import SwimZH

@Suite("App correctness, in the built bundle")
struct AppCorrectnessTests {
  static var info: [String: Any] { Bundle.main.infoDictionary ?? [:] }

  @Test("the bundle under test really is the app, so the rest of this suite means something")
  func theBundleIsTheApp() {
    #expect(Bundle.main.bundleIdentifier == "ch.swimzh.SwimZH")
    #expect(!Self.info.isEmpty)
  }

  @Test("the UIScene lifecycle is adopted — without it the app does not launch on iOS 27")
  func sceneLifecycleIsAdopted() {
    let manifest = Self.info["UIApplicationSceneManifest"] as? [String: Any]
    #expect(manifest != nil, "no UIApplicationSceneManifest: \(Self.info.keys.sorted())")
  }

  @Test("a launch screen is declared — a submission requirement from iOS 27")
  func launchScreenIsDeclared() {
    // SwiftUI apps take the generated `UILaunchScreen` dictionary; an empty dictionary is
    // a valid and deliberate declaration (a plain background), so its PRESENCE is the
    // check. `UILaunchStoryboardName` would satisfy Apple too, hence the either/or.
    let modern = Self.info["UILaunchScreen"] != nil
    let storyboard = Self.info["UILaunchStoryboardName"] != nil
    #expect(modern || storyboard, "no launch screen: \(Self.info.keys.sorted())")
  }

  @Test("UIRequiresFullScreen is never set")
  func fullScreenIsNotRequested() {
    // Ignored from the iOS 27 SDK. Setting it would not change behaviour; it would only
    // leave a false statement in the plist for whoever reads it next.
    #expect(Self.info["UIRequiresFullScreen"] == nil)
  }

  @Test("the privacy manifest ships, and declares the UserDefaults required-reason API")
  func privacyManifestIsCompleteAndHonest() throws {
    let url = try #require(
      Bundle.main.url(forResource: "PrivacyInfo", withExtension: "xcprivacy"),
      "PrivacyInfo.xcprivacy is not in the built bundle — ITMS-91055 at upload"
    )
    let manifest =
      try PropertyListSerialization.propertyList(
        from: Data(contentsOf: url), format: nil) as? [String: Any] ?? [:]

    // @AppStorage IS UserDefaults, and S3a's favourites use it. Declaring the category
    // without a valid reason code is its own rejection (ITMS-91055), so both halves are
    // asserted, not just the presence of the array.
    let types = manifest["NSPrivacyAccessedAPITypes"] as? [[String: Any]] ?? []
    let userDefaults = types.first {
      $0["NSPrivacyAccessedAPIType"] as? String == "NSPrivacyAccessedAPICategoryUserDefaults"
    }
    let reasons = try #require(userDefaults)["NSPrivacyAccessedAPITypeReasons"] as? [String]
    #expect(reasons == ["CA92.1"], "CA92.1 is the app's-own-defaults reason; 1C8F.1 is App Groups")

    // The three claims the app can actually keep, because it has no networking code at all
    // (a SwimZHKit source lint fails the build if any appears in either target).
    #expect(manifest["NSPrivacyTracking"] as? Bool == false)
    #expect((manifest["NSPrivacyTrackingDomains"] as? [String])?.isEmpty == true)
    #expect((manifest["NSPrivacyCollectedDataTypes"] as? [Any])?.isEmpty == true)
  }
}
