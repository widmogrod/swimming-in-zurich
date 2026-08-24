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
    // --- /pools: the facts the detail sheet adds (S3b) --------------------------------
    "PoolOut.description",
    "PoolOut.phone",
    "PoolOut.url",
    // --- the lane quartet: derived on the client, drawn by the ribbon (S3b) ----------
    //
    // All four are rendered by the day-tail canvas and its VoiceOver layer, and each by a
    // DIFFERENT part of it — which is why they are four fields and not one. Each is named by
    // the path that ACTUALLY EXECUTES against the committed store, because two of them used to
    // cite paths that never run:
    //   * `lane_availability` — the session line's "5 of 8 lanes open"
    //     (`SwimOption.laneSummary(isToday:)`), on today while the session is running.
    //   * `lane_timeline`     — the same line's OFF-TODAY and not-yet-open answer: its first
    //     segment is the split the session opens with, which is the only lane claim a row may
    //     make when there is no wall clock to read. (It also feeds the ribbon's thickness, via
    //     the `lanes` variant — see `RibbonCanvas.drawLanes`, which no store row reaches today.)
    //   * `lane_day_view`     — the lane stack's sub-rows, and the expanded Gantt.
    //   * `lane_best_public`  — the "Most lanes free" spoken fact on the ribbon, and the
    //     "Most lanes free" row in the detail sheet's lane panel. NOT a drawn band: nothing
    //     paints one, and the earlier comment saying so was describing the web.
    "OptionOut.lane_availability",
    "OptionOut.lane_timeline",
    "OptionOut.lane_day_view",
    "OptionOut.lane_best_public",
    // --- the provenance stamp, now that there is a sheet to put it on (S3b) ----------
    //
    // `SwimOption.provenance` is the FACILITY's (`query.py:544`), so all three are read from
    // the `pool` row and rendered in the sheet's "Where this came from" section.
    "OptionOut.source",
    "OptionOut.curated",
    "OptionOut.valid_as_of",
    // --- FacilityDetailOut: the sheet (S3b) -------------------------------------------
    "FacilityDetailOut.facility_name",
    "FacilityDetailOut.address",
    "FacilityDetailOut.freshness",
    "FacilityDetailOut.basins",
    "FacilityDetailOut.features",
    "FacilityDetailOut.lockers",
    "FacilityDetailOut.rentals",
    "FacilityDetailOut.admission",
    "FacilityDetailOut.prices",
    "FacilityDetailOut.operating_season",
    "FacilityDetailOut.provenance",
    "FacilityDetailOut.lane_panels",
    "FacilityDetailOut.last_admission_before_min",
  ]

  /// Fields the phone knowingly does not render, each with the reason it does not.
  ///
  /// Every reason is asserted NON-EMPTY by the test, which is the whole difference between a
  /// mechanism and a checklist: an entry added to silence the union check has to state why.
  /// The lane quartet and every `FacilityDetailOut` field move into `renderedFields` in S3b,
  /// and the disjointness assertion is what forces the move to be a real edit here.
  public static let deliberatelyOmitted: [String: String] = [
    // --- what S4 still does NOT render, and why -------------------------------------
    //
    // Two of these were labelled "S4 OWNS IT". S4 has now landed the message catalog, and
    // NEITHER became rendered — so the reasons are rewritten to say what is actually true
    // rather than left pointing at a slice that has been and gone. That is the whole point of
    // this file having reasons at all: a stale "a later slice will do it" is how an omission
    // becomes permanent without anyone deciding it should be.
    "OptionOut.reason_params":
      "STILL NOT RENDERED after S4, and not for want of a catalog. The phone renders an "
      + "eligibility OUTCOME as a mark (uiMark, from reason_code) rather than as a sentence, "
      + "so there is no message for min_age or club to interpolate into. Rendering them needs "
      + "a per-session eligibility sentence on the row — a UI decision, not a translation one, "
      + "and one no acceptance criterion in S1-S4 asks for. The web shows the same outcome the "
      + "same way (`elig.in`/`elig.chk`/`elig.no` are marks too).",
    "StatusOut.detail_code":
      "STILL NOT RENDERED after S4: it is an i18n KEY, and now that this app HAS a catalog the "
      + "distinction is sharper, not softer. The state is rendered from `status` + "
      + "`closure_code` + the pool's own `detail_params[\"text\"]`, which is what a swimmer can "
      + "act on; the raw code beside it would be an identifier on screen.",
    "FacilityDetailOut.facility_id":
      "NOT A FACT FOR A SWIMMER: it is the key the sheet is addressed BY, not something the "
      + "sheet says. `facility_name` is the rendered identity. Declaring an id `rendered` "
      + "because the code passes it around is exactly the aspirational claim this file's own "
      + "history warns about.",
    "FacilityDetailOut.live_water_temp":
      "S5 OWNS IT: it is a NETWORK read, and `SourceLintTests.noNetwork` bans networking in "
      + "both targets — so this slice structurally cannot render it, nor the explicit "
      + "unavailable state that must come with it. S5 narrows the lint and adds both.",
  ]

  /// Every field the phone has classified. Equality with the generated file is the test.
  public static var classifiedFields: Set<String> {
    renderedFields.union(deliberatelyOmitted.keys)
  }
}
