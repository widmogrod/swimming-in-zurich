// FieldCoverage.swift — what the phone renders of the web's response models, and what it
// deliberately does not.
//
// The two clients answer the same question and nothing about them makes either notice when the
// other grows a field: the web adds `OptionOut.foo`, the phone silently keeps not showing it,
// and the gap is found by a user rather than by a gate. So the field list is GENERATED from the
// pydantic models (`scripts/field_coverage.py`), committed, and asserted from both sides:
//
//   * PYTHON, the staleness gate: `apps/web/tests/test_field_coverage_contract.py` asserts the
//     committed JSON still equals what the models generate. Adding a field fails there. Without
//     that half the whole mechanism is decorative — it is exactly the teeth
//     `test_eligibility_ui_contract.py` gives its own fixture.
//   * SWIFT, here: `renderedFields ∪ deliberatelyOmitted` must equal the file's fields, and the
//     two sets must be DISJOINT. So a new field cannot be green until it is classified —
//     rendered, or omitted with a stated reason.
//
// WHAT THIS PROVES, precisely: drift detection against the web models. `renderedFields` is a
// hand-maintained declaration, so it does not prove any pixel is drawn — it proves that nobody
// added a field the phone has never considered. The reasons below are the mechanism the plan
// asks for; prose in a markdown table is not, which is the finding this replaced.
//
// Names are QUALIFIED (`OptionOut.facility`) because `OptionOut` and `StatusOut` both declare
// `facility` and an unqualified union would collapse two different obligations into one.

import Foundation

/// The S3a/S3b handover, mechanised.
public enum FieldCoverage {
  /// Fields the phone surfaces to the user. Derived facts count: `lat`/`lon` are rendered as
  /// the distance and the radius filter, which is the only form in which a coordinate is
  /// useful to a swimmer.
  public static let renderedFields: Set<String> = [
    // --- /swim options: the list row and its sessions -------------------------------
    "OptionOut.facility",
    "OptionOut.facility_id",
    "OptionOut.kind",
    "OptionOut.basin",
    "OptionOut.basin_id",
    "OptionOut.length_m",
    "OptionOut.lanes",
    "OptionOut.start",
    "OptionOut.end",
    "OptionOut.access",
    "OptionOut.weather",
    "OptionOut.eligible",
    "OptionOut.reason_code",
    "OptionOut.price",
    "OptionOut.distance_km",
    "OptionOut.open_now",
    // --- /swim statuses: the four ghost states --------------------------------------
    "StatusOut.facility",
    "StatusOut.status",
    "StatusOut.closure_code",
    "StatusOut.detail_params",
    "StatusOut.distance_km",
    // --- /pools rows -----------------------------------------------------------------
    "PoolOut.pool_id",
    "PoolOut.name",
    "PoolOut.kind",
    "PoolOut.address",
    "PoolOut.lat",
    "PoolOut.lon",
    "PoolOut.freshness",
  ]

  /// Fields the phone knowingly does not render, each with the reason it does not.
  ///
  /// Every reason is asserted NON-EMPTY by the test, which is the whole difference between a
  /// mechanism and a checklist: an entry added to silence the union check has to state why.
  /// The lane quartet and every `FacilityDetailOut` field move into `renderedFields` in S3b,
  /// and the disjointness assertion is what forces the move to be a real edit here.
  public static let deliberatelyOmitted: [String: String] = [
    // --- provenance: carried by the store, read by nothing yet ------------------------
    //
    // These three were briefly declared RENDERED, which was false: `SwimOption` has no
    // `source`, `curated` or `validAsOf` property, `Store` never selects the columns, and no
    // view could draw them. That is the one hole the union/disjointness test cannot see — it
    // checks that every field is CLASSIFIED, not that a "rendered" claim is true — so the
    // reasons below are the only thing standing behind it.
    "OptionOut.valid_as_of":
      "S3b: the detail sheet's source stamp. The `pool` table carries `valid_as_of`, but "
      + "`PoolRecord` does not read it and no S3a surface shows it. The list already states "
      + "the store-wide `gold_valid_as_of` in its provenance footer.",
    "OptionOut.source":
      "S3b: the detail sheet's source stamp. Not on `SwimOption` and not selected by `Store`.",
    "OptionOut.curated":
      "S3b: the detail sheet's source stamp. Note CLAUDE.md's caveat — every schedule is "
      + "scraped, so `curated` is False everywhere and `freshness` is the signal the list "
      + "row actually renders.",
    // --- /swim statuses ----------------------------------------------------------------
    "OptionOut.reason_params":
      "S4 OWNS IT: the params (min_age, club) are interpolation VALUES for a message this app "
      + "does not yet render. S3a renders the outcome as a mark via reason_code (uiMark); the "
      + "sentence they fill in arrives with the message catalog.",
    "StatusOut.detail_code":
      "S4: it is an i18n KEY, not a sentence. S3a renders the state itself (`status` + "
      + "`closure_code` + the pool's own `detail_params[\"text\"]`); rendering the raw code "
      + "beside it would show a swimmer an identifier.",
    // --- the lane quartet: S3b's per-lane stack --------------------------------------
    "OptionOut.lane_availability":
      "S3b: the per-lane stack. Only 7 basins carry a parsed Belegungsplan, and the derivation "
      + "is 7 functions of lane_plan.py that S3b ports against a generated fixture.",
    "OptionOut.lane_timeline":
      "S3b: the per-lane stack — the boundary-by-boundary split the ribbon paints.",
    "OptionOut.lane_day_view":
      "S3b: the per-lane stack — which lane and whose, across the whole weekday.",
    "OptionOut.lane_best_public":
      "S3b: the per-lane stack — the best-time-to-come window inside one session.",
    // --- /pools: detail-sheet facts ---------------------------------------------------
    "PoolOut.description":
      "S3b: the facility detail sheet. A paragraph of prose has no place in a scannable list "
      + "row, and truncating it there would be worse than omitting it.",
    "PoolOut.phone":
      "S3b: the facility detail sheet, where a tappable number belongs beside the address.",
    "PoolOut.url":
      "S3b: the facility detail sheet. A link out of an offline app is a considered action, "
      + "not a list-row affordance.",
    // --- FacilityDetailOut: the whole sheet is S3b ------------------------------------
    "FacilityDetailOut.facility_id":
      "S3b: the facility detail sheet, governed by this mechanism from S3a on.",
    "FacilityDetailOut.facility_name":
      "S3b: the facility detail sheet's title.",
    "FacilityDetailOut.address":
      "S3b: the facility detail sheet's address block.",
    "FacilityDetailOut.freshness":
      "S3b: the detail sheet's schedule-freshness stamp. The LIST row already renders the same "
      + "derived value (PoolOut.freshness), so no state is hidden meanwhile.",
    "FacilityDetailOut.basins":
      "S3b: the detail sheet's basin table — all 12 BasinOut fields incl. physical_source.",
    "FacilityDetailOut.features":
      "S3b: the detail sheet's features, incl. closed_reason.",
    "FacilityDetailOut.lockers":
      "S3b: the detail sheet's locker table.",
    "FacilityDetailOut.rentals":
      "S3b: the detail sheet's rental table.",
    "FacilityDetailOut.admission":
      "S3b: the detail sheet's admission kind. The row already shows the resolved price for "
      + "the person (OptionOut.price), which is the part a swimmer acts on.",
    "FacilityDetailOut.prices":
      "S3b: the detail sheet's full tariff table.",
    "FacilityDetailOut.operating_season":
      "S3b: the detail sheet's season line. Out of season the LIST already says so, as "
      + "closed + out_of_season, so nothing is concealed in the meantime.",
    "FacilityDetailOut.provenance":
      "S3b: the detail sheet's source stamp — together with the three OptionOut provenance "
      + "fields above, which S3a does not render either. S3a states only the store-wide "
      + "`gold_valid_as_of`, in the list's provenance footer.",
    "FacilityDetailOut.lane_panels":
      "S3b: the per-basin lane panels — the same port as the lane quartet above.",
    "FacilityDetailOut.last_admission_before_min":
      "S3b: the detail sheet's last-admission line.",
    "FacilityDetailOut.live_water_temp":
      "S5 OWNS IT: that slice adds the Baditicker client and requires the badge to show an "
      + "explicit unavailable state offline. S3a renders neither the reading nor that state.",
  ]

  /// Every field the phone has classified. Equality with the generated file is the test.
  public static var classifiedFields: Set<String> {
    renderedFields.union(deliberatelyOmitted.keys)
  }
}
