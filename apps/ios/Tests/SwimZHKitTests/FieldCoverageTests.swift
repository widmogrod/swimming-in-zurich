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
  /// The English renderer, and the `Format` the rule layer now needs to turn a value into
  /// words. The evidence assertions below are about which ROW or FACT exists, so one language
  /// is the right resolution for them — a field that reaches a swimmer's eye reaches it in all
  /// five or in none, and `AccessExplainerTests` is where the catalog's coverage is policed.
  static let en = CatalogFixture.english

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

  @Test("the lane quartet MOVED into renderedFields (S3b acceptance 2)")
  func laneQuartetIsRendered() {
    // The handover S3a mechanised, completed. The disjointness assertion above is what made
    // this a real edit rather than an addition — the four could not simply be added.
    for field in [
      "OptionOut.lane_availability",
      "OptionOut.lane_timeline",
      "OptionOut.lane_day_view",
      "OptionOut.lane_best_public",
    ] {
      #expect(FieldCoverage.renderedFields.contains(field), "\(field) has not moved")
      #expect(FieldCoverage.deliberatelyOmitted[field] == nil)
    }
  }

  @Test("every FacilityDetailOut field is rendered, except the identifier it is addressed by")
  func facilityDetailIsRendered() throws {
    let generated = try Self.generatedFields().filter { $0.hasPrefix("FacilityDetailOut.") }
    #expect(generated.count >= 15)
    // `live_water_temp` was the last holdout and S5 moved it: the network lint is now a seam
    // rather than a ban, and the reading — or the honest reason there is none — is the sheet's
    // first basin row. `facility_id` stays out: it is an identifier, not a fact a swimmer reads.
    let stillOmitted = Set(["FacilityDetailOut.facility_id"])
    for field in generated {
      if stillOmitted.contains(field) {
        #expect(FieldCoverage.deliberatelyOmitted[field] != nil, "\(field)")
        continue
      }
      #expect(FieldCoverage.renderedFields.contains(field), "\(field) is still not rendered")
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
    // CLASSIFIED, not that a "rendered" claim is TRUE. Three provenance fields were once
    // declared rendered while `SwimOption` had no such property and `Store` never selected the
    // columns — no view could have drawn them.
    //
    // Those three ARE rendered now, in the detail sheet's source stamp, which is why they have
    // moved out of this list and into `renderedRowsExistForEveryClaimedField` below — where the
    // claim is checked against real rows built from the committed store instead of being
    // restated. What stays here is the one field still declared rendered by nothing.
    for field in ["OptionOut.reason_params"] {
      #expect(
        FieldCoverage.deliberatelyOmitted[field] != nil,
        "\(field) is declared rendered, but nothing renders it"
      )
      #expect(!FieldCoverage.renderedFields.contains(field))
    }
  }

  /// Which `DetailRow` id proves each claimed field reaches a swimmer's eye.
  ///
  /// This is the mechanism S3a said did not exist. It cannot be fully general — a row id is
  /// still a hand-written link between a wire field and a rendered line — but it is far
  /// stronger than a declaration: the rows are built from the REAL committed store, so a field
  /// the store never populates, or one `detailSections` forgets, fails here by name.
  static let rowEvidence: [String: String] = [
    "FacilityDetailOut.address": "address",
    "PoolOut.description": "description",
    "PoolOut.phone": "phone",
    "PoolOut.url": "url",
    "FacilityDetailOut.freshness": "freshness",
    "FacilityDetailOut.admission": "admission",
    "FacilityDetailOut.prices": "price-0",
    "FacilityDetailOut.last_admission_before_min": "last-admission",
    "FacilityDetailOut.operating_season": "season",
    "FacilityDetailOut.basins": "basin-",
    "FacilityDetailOut.features": "feature-",
    "FacilityDetailOut.lockers": "locker-",
    "FacilityDetailOut.rentals": "rental-",
    "FacilityDetailOut.lane_panels": "panel-",
    "FacilityDetailOut.provenance": "source",
    "OptionOut.source": "source",
    "OptionOut.curated": "curated",
    "OptionOut.valid_as_of": "valid-as-of",
    // The live reading (S5). Its evidence row is built for every pool that carries a Baditicker
    // key, from the real store — see the `live` argument in the sweep below.
    "FacilityDetailOut.live_water_temp": "live-water",
  ]

  /// The `FacilityDetailOut` fields whose evidence is NOT a `DetailRow`, and what it is instead.
  ///
  /// This list exists because of a hole found in review: `renderedRowsExistForEveryClaimedField`
  /// iterates `rowEvidence`, so a field claimed rendered with NO entry there is silently
  /// unchecked — which is how `live_water_temp` was first moved into `renderedFields` on
  /// evidence that did not exist. Naming the exceptions turns "has no row" from an invisible
  /// default into a deliberate, justified statement, and `everyClaimedSheetFieldHasEvidence`
  /// fails on anything in neither list.
  static let nonRowEvidence: [String: String] = [
    "FacilityDetailOut.facility_name":
      "the sheet's TITLE, not a row — evidence is UILintTests.detailSheetRendersTheName"
  ]

  @Test("every claimed FacilityDetailOut field carries evidence, row or named exception")
  func everyClaimedSheetFieldHasEvidence() throws {
    // The gap this closes: the sweep below loops over `rowEvidence`, so a field declared
    // rendered and absent from it was checked by NOTHING. That is how a `rendered` claim
    // outran its evidence for the fourth time in this plan — the union test proves a field is
    // CLASSIFIED, never that a rendered claim is TRUE.
    let claimed = FieldCoverage.renderedFields.filter { $0.hasPrefix("FacilityDetailOut.") }
    #expect(claimed.count >= 13)
    for field in claimed {
      let evidence = Self.rowEvidence[field] ?? Self.nonRowEvidence[field]
      #expect(
        evidence?.isEmpty == false,
        "\(field) is declared rendered with no evidence in rowEvidence or nonRowEvidence"
      )
    }
    // ...and the exceptions cannot smuggle a field past the row check: an entry in both lists
    // would let a missing row hide behind a sentence.
    #expect(Set(Self.rowEvidence.keys).isDisjoint(with: Self.nonRowEvidence.keys))
  }

  @Test("every claimed detail field produces a real row, on a real pool, from the real store")
  func renderedRowsExistForEveryClaimedField() async throws {
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    let day = metadata.horizonStart
    var ids: Set<String> = []
    var titles: Set<String> = []
    var rowCount = 0
    // ACROSS the whole roster, not one pool: no single pool in the city has a season AND a
    // feature AND a lane plan, so a one-pool check would have to drop three fields to pass.
    for pool in try await store.pools() {
      guard let detail = try await store.facility(poolID: pool.id, on: day) else { continue }
      // The live reading is threaded in for exactly the pools that publish one, which is what
      // the app does: 23 of the 57 carry a Baditicker key, and a pool with no key gets no row
      // rather than an empty one. The reading stands in for the feed — fetching it is
      // `LiveTests`' business; what is proved HERE is that the field reaches a rendered row
      // built from the real store, which is the standard every other claimed field is held to.
      let live: LiveTemp? = detail.baditickerPOIID.map { _ in
        .reading(TempReading(measuredAt: Date(), celsius: 21.5, isOpen: true))
      }
      for section in detailSections(
        detail, on: day, for: Person(age: 30), in: Self.en, live: live)
      {
        titles.insert(Self.en(section.title))
        rowCount += section.rows.count
        ids.formUnion(section.rows.map(\.id))
      }
    }
    // Distinct row IDS collide across pools by design ("address" is "address" everywhere), so
    // the non-vacuity floor counts ROWS as well: an empty sheet would satisfy neither.
    #expect(rowCount > 400, "only \(rowCount) rows across the roster — did the sheet break?")
    #expect(titles.count >= 7, "only \(titles.sorted()) sections ever appeared")
    for (field, evidence) in Self.rowEvidence {
      #expect(FieldCoverage.renderedFields.contains(field), "\(field) is not claimed rendered")
      #expect(
        ids.contains { $0 == evidence || $0.hasPrefix(evidence) },
        "\(field) is declared rendered, but no `\(evidence)` row exists on any pool"
      )
    }
    // `facility_name` has no row of its own — it is the sheet's TITLE — so its evidence is a
    // lint over the app target (`UILintTests.detailSheetRendersTheName`), not a row here.
    #expect(!FieldCoverage.renderedFields.contains("FacilityDetailOut.facility_id"))
  }

  @Test("the lane quartet reaches a pixel too, on a basin that has a plan")
  func laneQuartetReachesAPixel() async throws {
    // The same standard applied to the four fields acceptance 2 moves: each is claimed rendered
    // by a DIFFERENT part of the ribbon, so each is checked separately against a real option.
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    var checked = 0
    var bestPublicChecked = 0
    for offset in 0..<7 {
      guard let day = ZurichClock.day(metadata.horizonStart, plus: offset) else { continue }
      let answer = try await store.answer(
        onDay: day, at: TimeOfDay(hour: 12, minute: 0), for: Person())
      for option in answer.options where option.laneDayView != nil {
        checked += 1
        let ribbon = optionRibbon(option.ribbonInput)
        let format = Self.en.format
        // lane_availability → the session line's own sentence, on today while it is running.
        #expect(option.laneSummary(isToday: true, format: format) != nil)
        // lane_timeline → the SAME line's off-today answer, which is its first segment's
        // split. (Its other consumer, the ribbon's thickness, is the `lanes` variant, which
        // no store row reaches — see `RibbonCanvas.drawLanes`.)
        let opening = try #require(option.laneTimeline?.segments.first?.availability)
        #expect(option.laneSummary(isToday: false, format: format) == opening.summary(format))
        // lane_day_view → the stack's sub-rows.
        #expect(ribbon.variant == "lanestack", "\(option.poolID)")
        #expect((ribbon.strips?.count ?? 0) > 0)
        // lane_best_public → the "Most public lanes free" spoken fact. Asserted by ITS OWN
        // label (`legend.lane.best`, rendered in English):
        // this used to assert `facts.contains("Lanes")`, which is the lane-stack fact and
        // would have passed unchanged with `lane_best_public` dropped entirely.
        let facts = a11yFacts(for: ribbon, in: Self.en).map { Self.en($0.label) }
        #expect(facts.contains("Lanes"))
        if option.laneBestPublic != nil {
          #expect(facts.contains("Most public lanes free"), "\(option.poolID)")
          bestPublicChecked += 1
        }
      }
    }
    #expect(checked > 5, "only \(checked) options with a lane plan — this proved little")
    #expect(
      bestPublicChecked > 5,
      "only \(bestPublicChecked) options had a best-public window — too few to claim it renders")
  }
}
