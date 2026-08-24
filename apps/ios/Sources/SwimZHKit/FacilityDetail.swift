// FacilityDetail.swift — the facility sheet, as a value.
//
// This is the port of `blocks/detailpanel.ts` and the whole of `FacilityDetailOut`, and it is
// built the same way the list is: the KIT decides every sentence and the view lays rows out. The
// reason is sharper here than anywhere else in the app. The sheet is where the honesty caveats
// live — a basin dimension "read from prose", a feature that is closed for a stated reason, a
// tariff that was accurate on a date now past — and a caveat rendered by a `body` is a caveat
// nothing can test.
//
// IT IS ALSO WHAT MAKES S3b ACCEPTANCE 4 TRUE RATHER THAN DECLARED. The field-coverage mechanism
// can only prove a field is CLASSIFIED, never that a "rendered" claim is honest — S3a declared
// five fields rendered that the phone structurally could not draw. So every `FacilityDetailOut`
// field is turned into a `DetailRow` here, and `renderedClaimsAreNotAspirational` asserts, by
// name and against a real pool from the committed store, that the row exists.
//
// EVERY SENTENCE IS DAY-AGNOSTIC unless it is explicitly about the selected day. The sheet is
// reachable from any day in the ~400-day horizon, so "closed today" would be wrong on ninety-odd
// dates — the same bug this app has already shipped twice.

import Foundation

/// One basin's physical facts — all 11 `BasinOut` fields plus its facility key.
public struct BasinDetail: Equatable, Sendable, Identifiable {
  public let basinID: String
  public let name: String
  public let kind: String
  public let lengthM: Double?
  public let widthM: Double?
  public let lanes: Int?
  public let nominalTempC: Double?
  public let measuredTempC: Double?
  public let divingPlatformsM: [Double]
  /// `curated` or `parsed_prose` — the honesty caveat on the dimensions. It is rendered, not
  /// swallowed: a length read out of a sentence is not the same fact as a published one.
  public let physicalSource: String
  public let lanePlanURL: String?

  public var id: String { basinID }
}

/// A locker or wardrobe entry.
public struct LockerDetail: Equatable, Sendable, Identifiable {
  public let ordinal: Int
  public let category: String
  public let feeCHF: Double?
  public let depositCHF: Double?
  public let period: String?
  public let mechanism: String?
  /// The pool's own line. Kept because the parsed fields are a lossy reading of it, and where
  /// they disagree the source's words win.
  public let raw: String?

  public var id: Int { ordinal }
}

/// A rental entry. The fee is a CLOSED union on the wire: a stated-gratis rental is not the
/// same fact as an unstated one, and the two must not collapse into "free".
public struct RentalDetail: Equatable, Sendable, Identifiable {
  public let ordinal: Int
  public let kind: String
  public let fee: String
  public let feeCHF: Double?
  public let depositCHF: Double?
  public let period: String?
  public let raw: String?

  public var id: Int { ordinal }
}

/// A feature (sauna, restaurant, terrace…) and, when it publishes hours, what they resolve to
/// on one date.
public struct FeatureDetail: Equatable, Sendable, Identifiable {
  public let key: String
  public let kind: String
  public let name: String?
  public let surchargeCHF: Double?
  public let tempC: Double?
  public let note: String?
  /// Resolved windows per date, from the export's `doc.days`. Empty when the feature publishes
  /// no hours of its own — which, measured, is every feature in the city today.
  public let days: [String: FeatureDay]

  public var id: String { key }

  /// This feature on one date: its windows, or the reason it is shut.
  public func day(_ date: String) -> FeatureDay? { days[date] }
}

public struct FeatureDay: Equatable, Sendable {
  public let windows: [TimeWindow]
  /// `FacilityDetailOut.features[].closed_reason` — named explicitly by acceptance 4, and it is
  /// nil for a feature that is simply unscheduled. Absent hours are NOT a closure.
  public let closedReason: String?
}

/// The page-stated season. Days are named ONLY at DAY precision: a MONTH window is whole months
/// inclusive, and rendering it day-precise would overstate what the page said.
public struct OperatingSeason: Equatable, Sendable {
  public let startMonth: Int
  public let endMonth: Int
  public let startDay: Int?
  public let endDay: Int?
  public let precision: String
  public let weather: String
}

/// Where this pool's facts came from and when they were true.
public struct Provenance: Equatable, Sendable {
  public let source: String?
  public let curated: Bool
  public let validAsOf: String?
}

/// One basin's lane panel for one weekday — the per-day projection of its Belegungsplan.
public struct LanePanel: Equatable, Sendable, Identifiable {
  public let basinID: String
  public let basinName: String
  public let day: LaneDay
  public let bestPublic: PublicWindow?
  public let roster: [ClubSlot]

  public var id: String { basinID }
}

/// Everything the facility sheet shows about one pool.
public struct FacilityDetail: Equatable, Sendable, Identifiable {
  public let poolID: String
  public let name: String
  public let kind: String
  public let address: String?
  public let description: String?
  public let phone: String?
  public let url: String?
  public let freshness: String
  public let admission: Admission
  public let basins: [BasinDetail]
  public let lockers: [LockerDetail]
  public let rentals: [RentalDetail]
  public let features: [FeatureDetail]
  public let operatingSeason: OperatingSeason?
  /// Seconds before closing after which nobody is admitted (`last_admission_before_min` on the
  /// wire, in minutes — the export stores seconds).
  public let lastAdmissionBeforeSeconds: Int?
  public let provenance: Provenance
  public let lanePanels: [LanePanel]

  public var id: String { poolID }
}

// MARK: - The rendered sheet

/// One line of the sheet: a label, a value, and — where the source is uncertain — the caveat
/// that says so.
public struct DetailRow: Equatable, Sendable, Identifiable {
  public let id: String
  public let label: String
  public let value: String
  public let caveat: String?

  public init(id: String, label: String, value: String, caveat: String? = nil) {
    self.id = id
    self.label = label
    self.value = value
    self.caveat = caveat
  }
}

public struct DetailSection: Equatable, Sendable, Identifiable {
  public let id: String
  public let title: String
  public let rows: [DetailRow]
}

/// The whole sheet, for one pool, one date and one person.
///
/// `day` is the date the list was showing, and only the two genuinely date-dependent parts use
/// it: a feature's resolved hours, and which weekday's lane plan to show. Everything else is a
/// standing fact about the pool and is worded without reference to any day.
public func detailSections(
  _ detail: FacilityDetail,
  on day: String,
  for person: Person
) -> [DetailSection] {
  [
    section("where", "Where", whereRows(detail)),
    section("admission", "Admission", admissionRows(detail, person)),
    section("season", "Season", seasonRows(detail)),
    section("basins", "Basins", detail.basins.flatMap(basinRows)),
    section("features", "Features", detail.features.flatMap { featureRows($0, on: day) }),
    section("lockers", "Lockers", detail.lockers.map(lockerRow)),
    section("rentals", "Rentals", detail.rentals.map(rentalRow)),
    section("lanes", "Lane plans", detail.lanePanels.flatMap(lanePanelRows)),
    section("source", "Where this came from", provenanceRows(detail)),
  ].compactMap { $0 }
}

/// A section with no rows is omitted entirely rather than shown empty: an empty "Lockers"
/// heading reads as "this pool has no lockers", which is a claim the data does not make.
private func section(_ id: String, _ title: String, _ rows: [DetailRow]) -> DetailSection? {
  rows.isEmpty ? nil : DetailSection(id: id, title: title, rows: rows)
}

private func whereRows(_ detail: FacilityDetail) -> [DetailRow] {
  var rows: [DetailRow] = []
  if let address = detail.address, !address.isEmpty {
    rows.append(DetailRow(id: "address", label: "Address", value: address))
  }
  if let phone = detail.phone, !phone.isEmpty {
    rows.append(DetailRow(id: "phone", label: "Phone", value: phone))
  }
  if let url = detail.url, !url.isEmpty {
    rows.append(DetailRow(id: "url", label: "Website", value: url))
  }
  if let description = detail.description, !description.isEmpty {
    rows.append(DetailRow(id: "description", label: "About", value: description))
  }
  rows.append(
    DetailRow(
      id: "freshness", label: "Schedule", value: freshnessLabel(detail.freshness),
      caveat: freshnessCaveat(detail.freshness)))
  return rows
}

/// The three-state `ScheduleFreshness`, said in words. `no_source` is NEVER "closed" — that is
/// the invariant the whole vocabulary exists to protect.
public func freshnessLabel(_ freshness: String) -> String {
  switch freshness {
  case "scraped": return "Published by the pool"
  case "awaiting_scrape": return "Not published yet"
  case "no_source": return "No timetable to read"
  default: return "Unrecognised state: \(freshness)"
  }
}

func freshnessCaveat(_ freshness: String) -> String? {
  switch freshness {
  case "scraped": return nil
  case "awaiting_scrape":
    return "This pool has a timetable page, but it has not been read into this app yet."
  case "no_source":
    return "This pool publishes no timetable of its own. That is not the same as being closed."
  default:
    // A store built by a newer export can carry a state this binary has never seen.
    return "This app does not recognise this state; check with the pool."
  }
}

private func admissionRows(_ detail: FacilityDetail, _ person: Person) -> [DetailRow] {
  var rows = [
    DetailRow(id: "admission", label: "Entry", value: admissionLabel(detail.admission))
  ]
  if case .tariff(let prices) = detail.admission {
    rows += prices.entries.enumerated().map { index, entry in
      DetailRow(
        id: "price-\(index)",
        label: entry.category.rawValue.capitalized,
        value: entry.display,
        caveat: entry.minAge.map { "Published for ages \($0) and over." })
    }
    if let bracket = priceFor(prices, person) {
      rows.append(
        DetailRow(id: "your-price", label: "Your rate", value: bracket.display))
    }
    if let validAsOf = prices.validAsOf {
      rows.append(
        DetailRow(
          id: "price-valid", label: "Prices read", value: validAsOf,
          caveat: "Prices come from the pool's own page and can change without notice."))
    }
    if let source = prices.sourceURL {
      rows.append(DetailRow(id: "price-source", label: "Tariff page", value: source))
    }
  }
  if let seconds = detail.lastAdmissionBeforeSeconds {
    rows.append(
      DetailRow(
        id: "last-admission", label: "Last admission",
        value: "\(seconds / 60) minutes before closing"))
  }
  return rows
}

public func admissionLabel(_ admission: Admission) -> String {
  switch admission {
  case .free: return "Free"
  case .tariff: return "Paid — see the rates below"
  // NOT "free": an unstated admission is unknown, and printing "free" would send somebody to a
  // turnstile with no money.
  case .unknown: return "Not published — check with the pool"
  }
}

private func seasonRows(_ detail: FacilityDetail) -> [DetailRow] {
  guard let season = detail.operatingSeason else { return [] }
  return [
    DetailRow(
      id: "season", label: "Open season", value: seasonLabel(season),
      caveat: season.weather == fairOnlyWeather
        ? "Published for fair weather; the pool may not open in poor weather." : nil)
  ]
}

/// "May to September", or "1 May to 15 September" — but only when the page said days.
public func seasonLabel(_ season: OperatingSeason) -> String {
  let from = monthName(season.startMonth)
  let to = monthName(season.endMonth)
  guard season.precision == "day", let startDay = season.startDay, let endDay = season.endDay
  else { return "\(from) to \(to)" }
  return "\(startDay) \(from) to \(endDay) \(to)"
}

func monthName(_ month: Int) -> String {
  let names = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
  ]
  return names.indices.contains(month - 1) ? names[month - 1] : "month \(month)"
}

private func basinRows(_ basin: BasinDetail) -> [DetailRow] {
  var rows = [
    DetailRow(
      id: "basin-\(basin.basinID)", label: basin.name, value: basinKindLabel(basin.kind))
  ]
  if let size = basinSize(basin) {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-size", label: "Size", value: size,
        caveat: physicalSourceCaveat(basin.physicalSource)))
  }
  if let lanes = basin.lanes {
    rows.append(
      DetailRow(id: "basin-\(basin.basinID)-lanes", label: "Lanes", value: "\(lanes)"))
  }
  if let temp = basin.measuredTempC ?? basin.nominalTempC {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-temp", label: "Water", value: "\(temp) °C",
        caveat: basin.measuredTempC == nil ? "The pool's stated temperature, not a reading." : nil
      ))
  }
  if !basin.divingPlatformsM.isEmpty {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-diving", label: "Diving",
        value: basin.divingPlatformsM.map { "\($0) m" }.joined(separator: ", ")))
  }
  if let plan = basin.lanePlanURL {
    rows.append(
      DetailRow(id: "basin-\(basin.basinID)-plan", label: "Lane plan", value: plan))
  }
  return rows
}

func basinSize(_ basin: BasinDetail) -> String? {
  switch (basin.lengthM, basin.widthM) {
  case (let length?, let width?): return "\(length) × \(width) m"
  case (let length?, nil): return "\(length) m"
  case (nil, let width?): return "\(width) m wide"
  default: return nil
  }
}

public func basinKindLabel(_ kind: String) -> String {
  switch kind {
  case "swimmer": return "Swimmers' pool"
  case "non_swimmer": return "Non-swimmers' pool"
  case "diving": return "Diving pool"
  case "learner": return "Learner pool"
  case "paddling": return "Paddling pool"
  case "multi_purpose": return "Multi-purpose pool"
  case "thermal": return "Thermal pool"
  case "outdoor": return "Outdoor pool"
  default: return kind.replacingOccurrences(of: "_", with: " ").capitalized
  }
}

/// The `physical_source` caveat, and it is the reason that field is exported at all: a
/// dimension read out of a sentence is a weaker fact than a published one, and the sheet says
/// which it is holding.
func physicalSourceCaveat(_ source: String) -> String? {
  source == "parsed_prose" ? "Read from the pool's prose, so it may be approximate." : nil
}

private func featureRows(_ feature: FeatureDetail, on day: String) -> [DetailRow] {
  let name = feature.name ?? featureKindLabel(feature.kind)
  var rows = [
    DetailRow(
      id: "feature-\(feature.key)", label: name, value: featureKindLabel(feature.kind),
      caveat: feature.note)
  ]
  if let surcharge = feature.surchargeCHF {
    rows.append(
      DetailRow(
        id: "feature-\(feature.key)-fee", label: "Surcharge",
        value: "CHF \(String(format: "%.2f", surcharge))"))
  }
  if let temp = feature.tempC {
    rows.append(
      DetailRow(id: "feature-\(feature.key)-temp", label: "Temperature", value: "\(temp) °C"))
  }
  if let resolved = feature.day(day) {
    rows.append(
      DetailRow(
        id: "feature-\(feature.key)-hours", label: "Hours on this date",
        value: featureHours(resolved)))
  }
  return rows
}

/// A feature's hours for one date. "Not listed for this date" is deliberately NOT "closed": a
/// feature with no windows and no stated reason is unscheduled, not shut.
func featureHours(_ day: FeatureDay) -> String {
  if !day.windows.isEmpty {
    return day.windows.map { "\($0.start.hhmm)–\($0.end.hhmm)" }.joined(separator: ", ")
  }
  if let reason = day.closedReason {
    return "Closed — \(closedReasonLabel(reason))"
  }
  return "Hours not listed for this date"
}

func closedReasonLabel(_ reason: String) -> String {
  switch reason {
  case "out_of_season": return "outside its season"
  case "no_sessions": return "no hours published for this date"
  case "closure": return "the pool states a closure"
  default: return reason.replacingOccurrences(of: "_", with: " ")
  }
}

public func featureKindLabel(_ kind: String) -> String {
  switch kind {
  case "sauna": return "Sauna"
  case "gastronomy": return "Restaurant or kiosk"
  case "sunbathing": return "Sunbathing lawn"
  case "playground": return "Playground"
  case "slide": return "Water slide"
  case "wellness": return "Wellness area"
  case "sport": return "Sports facility"
  default: return kind.replacingOccurrences(of: "_", with: " ").capitalized
  }
}

private func lockerRow(_ locker: LockerDetail) -> DetailRow {
  DetailRow(
    id: "locker-\(locker.ordinal)",
    label: lockerCategoryLabel(locker.category),
    value: feeLabel(amount: locker.feeCHF, deposit: locker.depositCHF, period: locker.period),
    // The pool's own line, kept beside the parsed fields: the parse is lossy, and where the
    // two disagree the source's words are the fact.
    caveat: locker.raw)
}

public func lockerCategoryLabel(_ category: String) -> String {
  switch category {
  case "wardrobe": return "Wardrobe locker"
  case "valuables": return "Valuables locker"
  case "cabin": return "Changing cabin"
  default: return category.replacingOccurrences(of: "_", with: " ").capitalized
  }
}

private func rentalRow(_ rental: RentalDetail) -> DetailRow {
  DetailRow(
    id: "rental-\(rental.ordinal)",
    label: rentalKindLabel(rental.kind),
    value: rentalFeeLabel(rental),
    caveat: rental.raw)
}

public func rentalKindLabel(_ kind: String) -> String {
  switch kind {
  case "towel": return "Towel"
  case "locker": return "Locker"
  case "deck_chair": return "Deck chair"
  case "swim_aid": return "Swimming aid"
  default: return kind.replacingOccurrences(of: "_", with: " ").capitalized
  }
}

/// The rental fee union, kept CLOSED: a stated-gratis rental and an unstated one are different
/// facts, and rendering both as "free" would invent a price for the second.
func rentalFeeLabel(_ rental: RentalDetail) -> String {
  switch rental.fee {
  case "gratis": return "Free"
  case "priced":
    return feeLabel(amount: rental.feeCHF, deposit: rental.depositCHF, period: rental.period)
  case "unstated": return "Price not published"
  default: return "Price not published"
  }
}

func feeLabel(amount: Double?, deposit: Double?, period: String?) -> String {
  var parts: [String] = []
  if let amount { parts.append("CHF \(String(format: "%.2f", amount))") }
  if let period, !period.isEmpty { parts.append("per \(period)") }
  if let deposit {
    parts.append("deposit CHF \(String(format: "%.2f", deposit))")
  }
  return parts.isEmpty ? "Price not published" : parts.joined(separator: ", ")
}

private func lanePanelRows(_ panel: LanePanel) -> [DetailRow] {
  var rows = [
    DetailRow(
      id: "panel-\(panel.basinID)", label: panel.basinName,
      value: "\(panel.day.laneCount) lanes",
      // ONE function, one polarity, one sentence — see `LaneDay.incompleteLanesCaveat`. This
      // used to test `confidence == "partial"` while the Gantt tested `!= "complete"`, so the
      // two surfaces disagreed about the same basin for any other token.
      caveat: panel.day.incompleteLanesCaveat)
  ]
  if let best = panel.bestPublic {
    rows.append(
      DetailRow(
        id: "panel-\(panel.basinID)-best", label: "Most lanes free",
        value: "\(best.window.start.hhmm)–\(best.window.end.hhmm), \(best.publicLanes) lanes"))
  }
  rows += panel.roster.map { slot in
    DetailRow(
      id: "panel-\(panel.basinID)-\(slot.id)", label: slot.club,
      value: "\(slot.window.start.hhmm)–\(slot.window.end.hhmm), "
        + "lane\(slot.lanes.count == 1 ? "" : "s") \(slot.lanes.map(String.init).joined(separator: ", "))"
    )
  }
  return rows
}

private func provenanceRows(_ detail: FacilityDetail) -> [DetailRow] {
  var rows: [DetailRow] = []
  if let source = detail.provenance.source {
    rows.append(DetailRow(id: "source", label: "Read from", value: source))
  }
  if let validAsOf = detail.provenance.validAsOf {
    rows.append(DetailRow(id: "valid-as-of", label: "Accurate as of", value: validAsOf))
  }
  rows.append(
    DetailRow(
      id: "curated", label: "Curation",
      value: detail.provenance.curated
        ? "Hand-checked" : "Read straight from the pool's own page"))
  return rows
}

// MARK: - Decoding the stored documents
//
// Every one of these returns nil for a malformed document rather than a zero value. A locker
// with no fee is a fact; a locker decoded to "CHF 0.00" because its JSON was unreadable is a
// fabrication, and the sheet would state it with the same confidence as everything else.

extension LockerDetail {
  struct Wire: Decodable {
    let category: String
    let feeCHF: Double?
    let depositCHF: Double?
    let period: String?
    let mechanism: String?
    let raw: String?

    enum CodingKeys: String, CodingKey {
      case category
      case feeCHF = "fee_chf"
      case depositCHF = "deposit_chf"
      case period
      case mechanism
      case raw
    }
  }

  static func decode(ordinal: Int, json: String) -> LockerDetail? {
    guard let wire: Wire = decodeDoc(json) else { return nil }
    return LockerDetail(
      ordinal: ordinal, category: wire.category, feeCHF: wire.feeCHF,
      depositCHF: wire.depositCHF, period: wire.period, mechanism: wire.mechanism, raw: wire.raw)
  }
}

extension RentalDetail {
  struct Wire: Decodable {
    let kind: String
    let fee: String
    let feeCHF: Double?
    let depositCHF: Double?
    let period: String?
    let raw: String?

    enum CodingKeys: String, CodingKey {
      case kind
      case fee
      case feeCHF = "fee_chf"
      case depositCHF = "deposit_chf"
      case period
      case raw
    }
  }

  static func decode(ordinal: Int, json: String) -> RentalDetail? {
    guard let wire: Wire = decodeDoc(json) else { return nil }
    return RentalDetail(
      ordinal: ordinal, kind: wire.kind, fee: wire.fee, feeCHF: wire.feeCHF,
      depositCHF: wire.depositCHF, period: wire.period, raw: wire.raw)
  }
}

extension FeatureDetail {
  struct Wire: Decodable {
    struct Day: Decodable {
      let windows: [[String]]
      let closedReason: String?

      enum CodingKeys: String, CodingKey {
        case windows
        case closedReason = "closed_reason"
      }
    }

    let kind: String
    let name: String?
    let surchargeCHF: Double?
    let tempC: Double?
    let note: String?
    let days: [String: Day]?

    enum CodingKeys: String, CodingKey {
      case kind
      case name
      case surchargeCHF = "surcharge_chf"
      case tempC = "temp_c"
      case note
      case days
    }
  }

  static func decode(key: String, json: String) -> FeatureDetail? {
    guard let wire: Wire = decodeDoc(json) else { return nil }
    var days: [String: FeatureDay] = [:]
    for (date, day) in wire.days ?? [:] {
      days[date] = FeatureDay(
        windows: day.windows.compactMap(window(from:)), closedReason: day.closedReason)
    }
    return FeatureDetail(
      key: key, kind: wire.kind, name: wire.name, surchargeCHF: wire.surchargeCHF,
      tempC: wire.tempC, note: wire.note, days: days)
  }

  private static func window(from pair: [String]) -> TimeWindow? {
    guard pair.count == 2, let start = TimeOfDay(hhmm: pair[0]), let end = TimeOfDay(hhmm: pair[1])
    else { return nil }
    return TimeWindow(start: start, end: end)
  }
}

extension OperatingSeason {
  struct Wire: Decodable {
    let startMonth: Int
    let endMonth: Int
    let startDay: Int?
    let endDay: Int?
    let precision: String
    let weather: String

    enum CodingKeys: String, CodingKey {
      case startMonth = "start_month"
      case endMonth = "end_month"
      case startDay = "start_day"
      case endDay = "end_day"
      case precision
      case weather
    }
  }

  static func decode(json: String) -> OperatingSeason? {
    guard let wire: Wire = decodeDoc(json) else { return nil }
    return OperatingSeason(
      startMonth: wire.startMonth, endMonth: wire.endMonth, startDay: wire.startDay,
      endDay: wire.endDay, precision: wire.precision, weather: wire.weather)
  }
}

/// The one JSON entry point for the sheet's documents.
func decodeDoc<T: Decodable>(_ json: String) -> T? {
  guard let data = json.data(using: .utf8) else { return nil }
  return try? JSONDecoder().decode(T.self, from: data)
}

extension LanePanel {
  /// The panel for one basin's weekday. `bestPublic` is UNBOUNDED here on purpose: a panel is a
  /// per-DAY object, so the whole weekday is its correct scope — where a session's own
  /// best-public window is bounded by that session's hours. Collapsing the two would make one
  /// of them lie.
  public init(basinID: String, basinName: String, day: LaneDay) {
    self.init(
      basinID: basinID,
      basinName: basinName,
      day: day,
      bestPublic: day.bestPublicTime(),
      roster: day.clubRoster()
    )
  }
}
