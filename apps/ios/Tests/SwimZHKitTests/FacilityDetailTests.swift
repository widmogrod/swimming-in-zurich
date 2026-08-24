// The facility sheet, as a value (S3b acceptance 4).
//
// The sheet is where this app's honesty caveats live, and a caveat rendered inside a `body` is a
// caveat nothing can test. So every sentence it shows is decided here, and these are the ones
// that would do real harm if they were wrong: an unstated admission rendered as "free" sends
// somebody to a turnstile with no money; a `no_source` schedule rendered as "closed" is the one
// thing the whole four-state vocabulary exists to forbid; a dimension read out of prose stated
// as flatly as a published one overstates what the city said.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The facility detail sheet")
struct FacilityDetailTests {
  static let day = "2026-08-24"

  static func detail(
    admission: Admission = .unknown,
    basins: [BasinDetail] = [],
    lockers: [LockerDetail] = [],
    rentals: [RentalDetail] = [],
    features: [FeatureDetail] = [],
    season: OperatingSeason? = nil,
    lastAdmission: Int? = nil,
    freshness: String = "scraped",
    panels: [LanePanel] = []
  ) -> FacilityDetail {
    FacilityDetail(
      poolID: "p", name: "Hallenbad Test", kind: "indoor", address: "Teststrasse 1",
      description: nil, phone: nil, url: nil, freshness: freshness, admission: admission,
      basins: basins, lockers: lockers, rentals: rentals, features: features,
      operatingSeason: season, lastAdmissionBeforeSeconds: lastAdmission,
      provenance: Provenance(source: "stadt-zuerich.ch", curated: false, validAsOf: "2026-08-24"),
      lanePanels: panels)
  }

  static func rows(_ detail: FacilityDetail) -> [DetailRow] {
    detailSections(detail, on: day, for: Person(age: 30)).flatMap(\.rows)
  }

  @Test("an unstated admission is never rendered as free")
  func unknownAdmissionIsNotFree() {
    let said = admissionLabel(.unknown).lowercased()
    #expect(said.contains("not published"))
    #expect(!said.contains("free"))
    #expect(admissionLabel(.free) == "Free")
  }

  @Test("an unstated rental price is never rendered as free either")
  func unstatedRentalIsNotFree() {
    // The wire keeps the fee union CLOSED for exactly this reason: a stated-gratis rental and
    // an unstated one are different facts.
    let unstated = RentalDetail(
      ordinal: 0, kind: "towel", fee: "unstated", feeCHF: nil, depositCHF: nil, period: nil,
      raw: nil)
    let gratis = RentalDetail(
      ordinal: 1, kind: "towel", fee: "gratis", feeCHF: nil, depositCHF: nil, period: nil,
      raw: nil)
    #expect(rentalFeeLabel(unstated) == "Price not published")
    #expect(rentalFeeLabel(gratis) == "Free")
  }

  @Test("`no_source` is never worded as closed — the invariant, one layer up")
  func noSourceIsNotClosed() {
    for freshness in ["scraped", "awaiting_scrape", "no_source", "something_new"] {
      let said = (freshnessLabel(freshness) + " " + (freshnessCaveat(freshness) ?? "")).lowercased()
      #expect(
        !said.contains("closed") || said.contains("not the same as being closed"), "\(freshness)")
    }
    #expect(freshnessCaveat("no_source")?.contains("not the same as being closed") == true)
    #expect(freshnessCaveat("scraped") == nil)
  }

  @Test("a season is only stated day-precise when the page said days")
  func seasonPrecisionIsRespected() {
    let months = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "month",
      weather: "any")
    #expect(seasonLabel(months) == "May to September")
    let days = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: 1, endDay: 15, precision: "day", weather: "any")
    #expect(seasonLabel(days) == "1 May to 15 September")
    // A DAY-precision claim with no days is a contradiction in the store, and the honest
    // rendering is the weaker one — never an invented day.
    let broken = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "day", weather: "any")
    #expect(seasonLabel(broken) == "May to September")
  }

  @Test("a fair-weather season carries its caveat")
  func fairWeatherSeasonSaysSo() {
    let season = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "month",
      weather: fairOnlyWeather)
    let row = Self.rows(Self.detail(season: season)).first { $0.id == "season" }
    #expect(row?.caveat?.contains("fair weather") == true)
  }

  @Test("a dimension read from prose says so; a published one does not")
  func physicalSourceCaveatIsRendered() {
    let parsed = BasinDetail(
      basinID: "b1", name: "25m", kind: "swimmer", lengthM: 25, widthM: 12.5, lanes: 6,
      nominalTempC: 28, measuredTempC: nil, divingPlatformsM: [1, 3],
      physicalSource:
        "parsed_prose", lanePlanURL: nil)
    let published = BasinDetail(
      basinID: "b2", name: "Lehrbecken", kind: "learner", lengthM: 12, widthM: nil, lanes: nil,
      nominalTempC: nil, measuredTempC: 31, divingPlatformsM: [], physicalSource: "curated",
      lanePlanURL: "https://example.invalid/plan.pdf")
    let rows = Self.rows(Self.detail(basins: [parsed, published]))
    #expect(rows.first { $0.id == "basin-b1-size" }?.caveat?.contains("approximate") == true)
    #expect(rows.first { $0.id == "basin-b2-size" }?.caveat == nil)
    // A nominal temperature is a STATEMENT, a measured one is a reading; the two are not
    // rendered with the same confidence.
    #expect(rows.first { $0.id == "basin-b1-temp" }?.caveat?.contains("not a reading") == true)
    #expect(rows.first { $0.id == "basin-b2-temp" }?.caveat == nil)
    #expect(rows.contains { $0.id == "basin-b2-plan" })
  }

  @Test("a feature with no hours is unscheduled, not closed")
  func featureWithoutHoursIsNotClosed() {
    #expect(
      featureHours(FeatureDay(windows: [], closedReason: nil)) == "Hours not listed for this date")
    #expect(featureHours(FeatureDay(windows: [], closedReason: "out_of_season")).contains("season"))
    let open = FeatureDay(
      windows: [
        TimeWindow(start: TimeOfDay(hour: 9, minute: 0), end: TimeOfDay(hour: 17, minute: 0))
      ], closedReason: nil)
    #expect(featureHours(open) == "09:00–17:00")
  }

  @Test("a feature states its surcharge, its temperature and its hours for THIS date")
  func featureRowsAreComplete() throws {
    // Measured, every feature in the city today has `hours=()` and no surcharge, so the real
    // store exercises only the empty arms of this rendering. A feature that publishes all of
    // them is a case the data does not yet have and the schema explicitly allows — the export
    // resolves per-date windows into the feature's own `doc` when it has hours — so it is
    // built here rather than left untested until the day a sauna publishes its times.
    let feature = try #require(
      FeatureDetail.decode(
        key: "sauna",
        json: #"""
          {"kind":"sauna","name":"Saunalandschaft","surcharge_chf":9.0,"temp_c":90.0,
           "note":"Textilfrei am Dienstag","hours":[],
           "days":{"2026-08-24":{"windows":[["10:00","21:00"]],"closed_reason":null},
                   "2026-08-25":{"windows":[],"closed_reason":"out_of_season"}}}
          """#))
    let rows = Self.rows(Self.detail(features: [feature]))
    #expect(rows.first { $0.id == "feature-sauna" }?.label == "Saunalandschaft")
    #expect(rows.first { $0.id == "feature-sauna" }?.caveat == "Textilfrei am Dienstag")
    #expect(rows.first { $0.id == "feature-sauna-fee" }?.value == "CHF 9.00")
    #expect(rows.first { $0.id == "feature-sauna-temp" }?.value == "90.0 °C")
    #expect(rows.first { $0.id == "feature-sauna-hours" }?.value == "10:00–21:00")
    // The NEXT day is closed for a stated reason, and that reason is rendered rather than
    // flattened into a bare "closed".
    let tomorrow = detailSections(
      Self.detail(features: [feature]), on: "2026-08-25", for: Person()
    ).flatMap(\.rows)
    #expect(tomorrow.first { $0.id == "feature-sauna-hours" }?.value.contains("season") == true)
    // A date the feature says nothing about gets no hours row at all — never an invented one.
    let far = detailSections(
      Self.detail(features: [feature]), on: "2027-01-01", for: Person()
    ).flatMap(\.rows)
    #expect(!far.contains { $0.id == "feature-sauna-hours" })
    // A feature with no name falls back to its KIND, so a row is never blank.
    let unnamed = try #require(
      FeatureDetail.decode(key: "rest", json: #"{"kind":"gastronomy","name":null}"#))
    #expect(
      Self.rows(Self.detail(features: [unnamed])).first { $0.id == "feature-rest" }?.label
        == "Restaurant or kiosk")
  }

  @Test("an empty section is omitted, never shown empty")
  func emptySectionsAreOmitted() {
    // An empty "Lockers" heading reads as "this pool has no lockers", which is a claim the
    // data does not make.
    let sections = detailSections(Self.detail(), on: Self.day, for: Person())
    #expect(!sections.contains { $0.id == "lockers" })
    #expect(!sections.contains { $0.id == "features" })
    #expect(!sections.contains { $0.id == "season" })
    // ...and the sections that always have something are always there.
    #expect(sections.contains { $0.id == "where" })
    #expect(sections.contains { $0.id == "source" })
  }

  @Test("the person's own price bracket is stated beside the table")
  func personalBracketIsShown() {
    let prices = PriceDoc(
      entries: [
        PriceEntry(category: .child, amountCHF: 4, display: "Kinder CHF 4.00", minAge: 6),
        PriceEntry(category: .adult, amountCHF: 8, display: "Erwachsene CHF 8.00", minAge: 20),
      ], validAsOf: "2026-07-18", sourceURL: "https://example.invalid/tarife")
    let rows = Self.rows(Self.detail(admission: .tariff(prices)))
    #expect(rows.first { $0.id == "your-price" }?.value == "Erwachsene CHF 8.00")
    #expect(rows.first { $0.id == "price-valid" }?.caveat?.contains("can change") == true)
    // Each published band states the bound it was printed under, so a swimmer can see WHY
    // theirs was chosen.
    #expect(rows.first { $0.id == "price-0" }?.caveat?.contains("6") == true)
  }

  @Test("last admission is stated in minutes, from the store's seconds")
  func lastAdmissionIsRendered() {
    let row = Self.rows(Self.detail(lastAdmission: 1800)).first { $0.id == "last-admission" }
    #expect(row?.value == "30 minutes before closing")
  }

  @Test("a partial lane plan says its counts may be incomplete")
  func partialPanelSaysSo() throws {
    let day = try #require(
      LaneDay.decode(
        basinID: "b", weekday: 1, laneCount: 4,
        strips:
          #"[{"lane":1,"segments":[{"start":"06:00","end":"12:00","access":"PublicSwim","owner":null}]}]"#,
        unresolvedLanes: "[4]", confidence: "partial"))
    let panel = LanePanel(basinID: "b", basinName: "25m", day: day)
    let rows = Self.rows(Self.detail(panels: [panel]))
    #expect(rows.first { $0.id == "panel-b" }?.caveat?.contains("incomplete") == true)
    #expect(rows.contains { $0.id == "panel-b-best" })
  }

  @Test("a malformed document decodes to nil, never to a zero-franc fact")
  func malformedDocumentsAreNotZeroes() {
    #expect(LockerDetail.decode(ordinal: 0, json: "not json") == nil)
    #expect(RentalDetail.decode(ordinal: 0, json: "{}") == nil)
    #expect(FeatureDetail.decode(key: "k", json: "[]") == nil)
    #expect(OperatingSeason.decode(json: "{\"start_month\": 5}") == nil)
    // ...and a well-formed one really does decode, so the assertions above are not passing
    // because everything returns nil.
    #expect(
      LockerDetail.decode(
        ordinal: 0,
        json:
          #"{"category":"wardrobe","fee_chf":null,"deposit_chf":null,"period":null,"mechanism":null,"raw":"Garderobenkasten"}"#
      )?.category == "wardrobe")
  }

  @Test("every sentence the sheet can say is DAY-AGNOSTIC, except the one about this date")
  func sheetSentencesAreDayAgnostic() {
    // The sheet is reachable from any day in the ~400-day horizon. The one line allowed to be
    // about a date says so explicitly ("Hours on this date"), and the rest must claim nothing
    // about when they are read. This app has shipped that bug twice.
    var said: [String] = [
      admissionLabel(.unknown), admissionLabel(.free),
      admissionLabel(.tariff(PriceDoc(entries: []))),
      seasonLabel(
        OperatingSeason(
          startMonth: 1, endMonth: 12, startDay: nil, endDay: nil, precision: "month",
          weather: "any")),
      featureHours(FeatureDay(windows: [], closedReason: nil)),
      featureHours(FeatureDay(windows: [], closedReason: "out_of_season")),
    ]
    for freshness in ["scraped", "awaiting_scrape", "no_source", "zzz"] {
      said.append(freshnessLabel(freshness))
      said.append(freshnessCaveat(freshness) ?? "")
    }
    for kind in ["swimmer", "paddling", "zzz"] { said.append(basinKindLabel(kind)) }
    for kind in ["sauna", "gastronomy", "zzz"] { said.append(featureKindLabel(kind)) }
    for kind in ["towel", "zzz"] { said.append(rentalKindLabel(kind)) }
    for kind in ["wardrobe", "zzz"] { said.append(lockerCategoryLabel(kind)) }
    for sentence in said {
      let lowered = sentence.lowercased()
      for temporal in ["today", "tonight", "right now", " now", "tomorrow", "this week"] {
        #expect(!lowered.contains(temporal), "\"\(sentence)\" claims \"\(temporal)\"")
      }
    }
  }

  @Test("an unrecognised code is shown as itself, never guessed at")
  func unrecognisedCodesAreShownAsThemselves() {
    // A store built by a newer export can carry a kind, a category or a freshness this binary
    // has never seen. Every fallback here degrades to the raw token or to an explicit "check
    // with the pool" — none of them invents a category.
    #expect(basinKindLabel("wave_pool") == "Wave Pool")
    #expect(featureKindLabel("ice_rink") == "Ice Rink")
    #expect(freshnessLabel("brand_new").contains("brand_new"))
    #expect(closedReasonLabel("mystery") == "mystery")
  }
}
