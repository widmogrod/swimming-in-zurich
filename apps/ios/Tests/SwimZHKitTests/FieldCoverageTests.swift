// The Swift half of the field-coverage contract (S3a acceptance 0 and 1).
//
// The Python half — `apps/web/tests/test_field_coverage_contract.py` — asserts the committed
// JSON still equals what the pydantic models generate, so a field ADDED to `OptionOut` fails
// there. This half asserts the phone has CLASSIFIED every field in that file: rendered, or
// omitted with a reason. Neither half is sufficient alone. Without the Python one the JSON
// silently rots; without this one a field can exist that the phone has never considered.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Field coverage against the web response models")
struct FieldCoverageTests {
  static func generatedFields() throws -> Set<String> {
    let object = try RepoFixtures.json(at: RepoFixtures.fieldCoverage)
    let fields = try #require(object["fields"] as? [String])
    return Set(fields)
  }

  @Test("the fixture is really there and really populated")
  func fixtureIsPresent() throws {
    let fields = try Self.generatedFields()
    // Four models with 55 fields between them at the time of writing. The floor guards against
    // the one failure that would make every other assertion here vacuously true: an empty or
    // truncated file, which `==` against an equally empty declaration would happily accept.
    #expect(fields.count >= 50, "only \(fields.count) fields — is the generator broken?")
    #expect(fields.contains("OptionOut.facility"))
    #expect(fields.contains("StatusOut.status"))
    #expect(fields.contains("PoolOut.freshness"))
    #expect(fields.contains("FacilityDetailOut.basins"))
  }

  @Test("every field is classified: rendered ∪ omitted == the generated set")
  func everyFieldIsClassified() throws {
    let generated = try Self.generatedFields()
    let classified = FieldCoverage.classifiedFields
    #expect(
      classified.subtracting(generated).isEmpty,
      "classified fields the models do not declare: \(classified.subtracting(generated).sorted())"
    )
    let unclassified = generated.subtracting(classified).sorted()
    #expect(
      unclassified.isEmpty,
      "unclassified fields — render them, or omit them WITH A REASON: \(unclassified)"
    )
  }

  @Test("rendered and omitted are disjoint")
  func renderedAndOmittedAreDisjoint() {
    let both = FieldCoverage.renderedFields.intersection(FieldCoverage.deliberatelyOmitted.keys)
    #expect(both.isEmpty, "a field cannot be both rendered and deliberately omitted: \(both)")
  }

  @Test("every omission states a reason")
  func everyOmissionStatesAReason() {
    // Acceptance 0. The reason string is the mechanism; a markdown checklist was the finding
    // this replaced. An entry added merely to silence the union check has to say why.
    for (field, reason) in FieldCoverage.deliberatelyOmitted {
      let trimmed = reason.trimmingCharacters(in: .whitespacesAndNewlines)
      #expect(!trimmed.isEmpty, "\(field) is omitted with no reason")
      #expect(trimmed.count >= 20, "\(field)'s reason says nothing: \(trimmed)")
    }
  }

  @Test("the lane quartet is omitted NOW and must move in S3b")
  func laneQuartetStartsOmitted() {
    // The handover, mechanised: S3b acceptance 2 moves these four into `renderedFields`, and
    // the disjointness assertion above makes that a real edit rather than an addition.
    for field in [
      "OptionOut.lane_availability",
      "OptionOut.lane_timeline",
      "OptionOut.lane_day_view",
      "OptionOut.lane_best_public",
    ] {
      #expect(FieldCoverage.deliberatelyOmitted[field] != nil, "\(field) lost its S3b reason")
      #expect(!FieldCoverage.renderedFields.contains(field))
    }
  }

  @Test("FacilityDetailOut is governed by the mechanism from this slice on")
  func facilityDetailIsGoverned() throws {
    let generated = try Self.generatedFields().filter { $0.hasPrefix("FacilityDetailOut.") }
    #expect(generated.count >= 15)
    for field in generated {
      #expect(
        FieldCoverage.deliberatelyOmitted[field] != nil,
        "\(field) is not classified — S3b's detail sheet is governed by this file, not by prose"
      )
    }
  }

  @Test("the fields that tell the ghost states apart are all declared rendered")
  func theGhostStateFieldsAreRendered() {
    // `status` + `closure_code` + `detail_params` are what tell the states apart. Omitting any
    // one would collapse two of them into one, which is the failure the whole vocabulary exists
    // to prevent — so they are named here, not just counted. `detail_params` in particular is
    // rendered for real: `dayStateLabel` quotes `detail_params["text"]` on an unmapped closure.
    for field in [
      "StatusOut.status", "StatusOut.closure_code", "StatusOut.detail_params",
    ] {
      #expect(FieldCoverage.renderedFields.contains(field))
    }
    // `detail_code` is an i18n KEY, not a sentence, and S3a shows the state instead.
    #expect(FieldCoverage.deliberatelyOmitted["StatusOut.detail_code"] != nil)
  }

  @Test("a `rendered` claim is backed by something the kit can actually reach")
  func renderedClaimsAreNotAspirational() {
    // The hole the union/disjointness test cannot see: it checks that every field is
    // CLASSIFIED, not that a "rendered" claim is TRUE. Three provenance fields were declared
    // rendered while `SwimOption` had no such property and `Store` never selected the columns —
    // no view could have drawn them. There is no general mechanism for this, so the three that
    // were wrong are pinned by name, beside the reason they are now omitted.
    for field in [
      "OptionOut.source", "OptionOut.curated", "OptionOut.valid_as_of",
      // Same category, found one round later: only `reason_code` reaches a pixel (through
      // `uiMark`). The params are interpolation VALUES for a message S4 has not shipped.
      "OptionOut.reason_params",
    ] {
      #expect(
        FieldCoverage.deliberatelyOmitted[field] != nil,
        "\(field) is declared rendered, but nothing renders it"
      )
      #expect(!FieldCoverage.renderedFields.contains(field))
    }
  }
}
