// RepoFixtures.swift — where the generated contracts live.
//
// The Swift suites replay the SAME files the Python and browser suites do, read from the
// repository rather than copied into the package. A copy is a third place for the contract
// to live and therefore a third place for it to go stale; reading the original means a
// regenerated fixture reaches all three clients at once, which is the entire point of
// generating it.
//
// `#filePath` is the only anchor that survives `swift test` being run from any directory.
// The store, by contrast, is a package RESOURCE (`Bundle.module`): it has to be readable
// from an app bundle on a device where no repository exists.

import Foundation
import Testing

@testable import SwimZHKit

enum RepoFixtures {
  /// The repository root, from this file's own path:
  /// `<root>/apps/ios/Tests/SwimZHKitTests/RepoFixtures.swift`.
  static let root: URL = {
    var url = URL(fileURLWithPath: #filePath)
    for _ in 0..<5 { url = url.deletingLastPathComponent() }
    return url
  }()

  /// The eligibility contract the browser replays too
  /// (`apps/web/tests/test_eligibility_ui_contract.py`).
  static let eligibilityContract =
    root
    .appending(path: "apps/web/tests/fixtures/eligibility_contract.json")

  /// The golden answers generated from `find_swim_options` (`tests/etl/test_ios_export.py`).
  static let parityAnswers = root.appending(path: "tests/fixtures/ios_parity/answers.json")

  /// The haversine pairs generated from `domain/geo.haversine_km` (`scripts/ios_fixtures.py`).
  static let haversine: URL = {
    var url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    return url.appending(path: "Fixtures/haversine.json")
  }()

  static func json(at url: URL) throws -> [String: Any] {
    let data = try Data(contentsOf: url)
    guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
      throw StoreError.malformedRow(table: url.lastPathComponent, detail: "not a JSON object")
    }
    return object
  }

  static func cases(at url: URL) throws -> [[String: Any]] {
    guard let cases = try json(at: url)["cases"] as? [[String: Any]] else {
      throw StoreError.malformedRow(table: url.lastPathComponent, detail: "no `cases` array")
    }
    return cases
  }
}
