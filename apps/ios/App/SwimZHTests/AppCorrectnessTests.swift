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

import SwimZHKit

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

    // S3a's favourites are one string in `UserDefaults.standard` (`TodayModel`). Declaring the
    // category
    // without a valid reason code is its own rejection (ITMS-91055), so both halves are
    // asserted, not just the presence of the array.
    let types = manifest["NSPrivacyAccessedAPITypes"] as? [[String: Any]] ?? []
    let userDefaults = types.first {
      $0["NSPrivacyAccessedAPIType"] as? String == "NSPrivacyAccessedAPICategoryUserDefaults"
    }
    let reasons = try #require(userDefaults)["NSPrivacyAccessedAPITypeReasons"] as? [String]
    #expect(reasons == ["CA92.1"], "CA92.1 is the app's-own-defaults reason; 1C8F.1 is App Groups")

    // The three claims the app can still keep now that S5 has opened a network seam. The app
    // reaches exactly two things — the city's public Baditicker feed and, if one is configured,
    // a store manifest — and sends NOTHING about the reader to either: no identifier, no
    // location, no query, not even which pool is on screen. Neither host is a tracking domain,
    // and nothing is collected. A source lint keeps the seam to two named files.
    #expect(manifest["NSPrivacyTracking"] as? Bool == false)
    #expect((manifest["NSPrivacyTrackingDomains"] as? [String])?.isEmpty == true)
    #expect((manifest["NSPrivacyCollectedDataTypes"] as? [Any])?.isEmpty == true)
  }

  @Test("the shipped app configures no store manifest, so it downloads nothing by default")
  func noManifestIsConfigured() {
    // Where a published store is HOSTED is out of this repo's scope, so the URL is
    // configuration and the shipped build carries none: this app fetches a live water
    // temperature when a sheet is opened and otherwise reaches nothing at all. Turning the
    // weekly refresh on is a deliberate `Info.plist` edit, and this test is what makes that
    // edit visible rather than incidental.
    //
    // `Bundle.main` matters here: the same assertion in the package's own suite would be about
    // the TEST RUNNER's plist, which is nobody's app.
    #expect(Self.info[RefreshConfiguration.infoKey] == nil)
    #expect(RefreshConfiguration.manifestURL(Self.info) == nil)
  }
}
