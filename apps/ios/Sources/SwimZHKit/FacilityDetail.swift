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
  /// The Baditicker feed key, or nil when this pool publishes no live water temperature.
  ///
  /// The KEY is in the store; the READING never is. A temperature baked into a weekly export
  /// would be presented as current for a week — the exact temporal-claim defect this project
  /// has now found eight times — so the client asks the feed at read time and says so, or says
  /// nothing at all. Nil is a first-class answer here: no key, no row, no invented number.
  public let baditickerPOIID: String?
  public let lanePanels: [LanePanel]

  public var id: String { poolID }
}

// MARK: - The rendered sheet

/// One line of the sheet: a label, a value, and — where the source is uncertain — the caveat
/// that says so.
///
/// All three are `Wording`, and that is the point of the type. A row mixes OUR words with the
/// POOL's in a way no other surface here does: the label "Water" is ours, the value "26 °C" is
/// a formatted number, the basin's name is the pool's own, and a locker's `raw` line is the
/// source's sentence quoted for exactly the reason we do not paraphrase it. Making the
/// distinction a type stops the sheet localising a proper noun or leaving a heading in English.
public struct DetailRow: Equatable, Sendable, Identifiable {
  public let id: String
  public let label: Wording
  public let value: Wording
  public let caveat: Wording?
  /// Whether this row's value should be shown with LESS weight than a plain fact.
  ///
  /// It says nothing new — a muted row's words are already true on their own — it stops a
  /// weaker fact from being read with the confidence of a stronger one. Today exactly one rule
  /// sets it: a live reading that is hours old, or absent altogether, must not sit in the same
  /// visual register as this morning's measurement. The web draws the same distinction
  /// (`detailpanel.ts`'s `muted`/`stale`).
  public let muted: Bool

  public init(
    id: String, label: Wording, value: Wording, caveat: Wording? = nil, muted: Bool = false
  ) {
    self.id = id
    self.label = label
    self.value = value
    self.caveat = caveat
    self.muted = muted
  }
}

public struct DetailSection: Equatable, Sendable, Identifiable {
  public let id: String
  public let title: Message
  public let rows: [DetailRow]
}

/// The whole sheet, for one pool, one date and one person.
///
/// `day` is the date the list was showing, and only the two genuinely date-dependent parts use
/// it: a feature's resolved hours, and which weekday's lane plan to show. Everything else is a
/// standing fact about the pool and is worded without reference to any day.
///
/// `format` is threaded through rather than reached for, because every number on this sheet —
/// a price, a temperature, a length, a lane count — reads differently per region, and a
/// default would quietly format in the device's locale while the words came from the app's.
public func detailSections(
  _ detail: FacilityDetail,
  on day: String,
  for person: Person,
  in localized: Localized,
  live: LiveTemp? = nil,
  at now: Date = Date()
) -> [DetailSection] {
  let format = localized.format
  return [
    section("where", "detail.section.where", whereRows(detail)),
    section("admission", "detail.section.admission", admissionRows(detail, person, format)),
    section("season", "detail.section.season", seasonRows(detail, format)),
    section(
      "basins", "detail.section.basins",
      // The LIVE reading first, then the published physicals. Facility-level rather than
      // per-basin because that is what the feed publishes — one temperature per bath — and
      // pinning it to a basin would be a precision the source does not have.
      (live.map { [liveWaterRow($0, at: now, in: localized).row] } ?? [])
        + detail.basins.flatMap { basinRows($0, format) }),
    section(
      "features", "detail.section.features",
      detail.features.flatMap { featureRows($0, on: day, localized) }),
    section("lockers", "detail.section.lockers", detail.lockers.map { lockerRow($0, format) }),
    section("rentals", "detail.section.rentals", detail.rentals.map { rentalRow($0, format) }),
    section(
      "lanes", "detail.section.lanes", detail.lanePanels.flatMap { lanePanelRows($0, format) }),
    section("source", "detail.section.provenance", provenanceRows(detail, format)),
  ].compactMap { $0 }
}

/// A section with no rows is omitted entirely rather than shown empty: an empty "Lockers"
/// heading reads as "this pool has no lockers", which is a claim the data does not make.
private func section(_ id: String, _ titleKey: String, _ rows: [DetailRow]) -> DetailSection? {
  rows.isEmpty ? nil : DetailSection(id: id, title: Message(titleKey), rows: rows)
}

private func whereRows(_ detail: FacilityDetail) -> [DetailRow] {
  var rows: [DetailRow] = []
  if let address = detail.address, !address.isEmpty {
    rows.append(
      DetailRow(id: "address", label: .key("detail.fact.address"), value: .verbatim(address)))
  }
  if let phone = detail.phone, !phone.isEmpty {
    rows.append(DetailRow(id: "phone", label: .key("detail.fact.phone"), value: .verbatim(phone)))
  }
  if let url = detail.url, !url.isEmpty {
    rows.append(DetailRow(id: "url", label: .key("detail.fact.website"), value: .verbatim(url)))
  }
  if let description = detail.description, !description.isEmpty {
    // The pool's own blurb, in the pool's own language. Untranslated by policy, like a notice.
    rows.append(
      DetailRow(
        id: "description", label: .key("detail.fact.about"), value: .verbatim(description)))
  }
  rows.append(
    DetailRow(
      id: "freshness", label: .key("detail.fact.schedule"),
      value: .message(freshnessLabel(detail.freshness)),
      caveat: freshnessCaveat(detail.freshness).map { .message($0) }))
  return rows
}

/// The three-state `ScheduleFreshness`, said in words. `no_source` is NEVER "closed" — that is
/// the invariant the whole vocabulary exists to protect.
public func freshnessLabel(_ freshness: String) -> Message {
  switch freshness {
  case "scraped": return Message("freshness.scraped")
  case "awaiting_scrape": return Message("freshness.awaiting")
  case "no_source": return Message("freshness.noSource")
  default: return Message("freshness.unknown", ["state": freshness])
  }
}

func freshnessCaveat(_ freshness: String) -> Message? {
  switch freshness {
  case "scraped": return nil
  case "awaiting_scrape": return Message("freshness.awaiting.caveat")
  case "no_source": return Message("freshness.noSource.caveat")
  // A store built by a newer export can carry a state this binary has never seen.
  default: return Message("freshness.unknown.caveat")
  }
}

private func admissionRows(
  _ detail: FacilityDetail, _ person: Person, _ format: Format
) -> [DetailRow] {
  var rows = [
    DetailRow(
      id: "admission", label: .key("detail.fact.entry"),
      value: .message(admissionLabel(detail.admission)))
  ]
  if case .tariff(let prices) = detail.admission {
    rows += prices.entries.enumerated().map { index, entry in
      DetailRow(
        id: "price-\(index)",
        label: .message(priceCategoryLabel(entry.category)),
        // The pool's OWN price line ("Erwachsene CHF 8.00"), quoted rather than rebuilt: it is
        // a dated fact off their page, and re-formatting it would silently restate it.
        value: .verbatim(entry.display),
        caveat: entry.minAge.map {
          .message(Message("price.minAgeCaveat", ["minAge": format.integer($0)]))
        })
    }
    if let bracket = priceFor(prices, person) {
      rows.append(
        DetailRow(
          id: "your-price", label: .key("detail.fact.yourRate"),
          value: .verbatim(bracket.display)))
    }
    // The store writes this as `date.isoformat()` — a machine key — so it goes through
    // `Format.storeDate` before a reader sees it, exactly like the two on the today screen.
    // The EMPTY guard is not defensive noise: the exporter writes `... or ""` for an absent
    // stamp, and a row reading "Prices read" with nothing after it is the invisible degradation
    // this sheet's every other honesty caveat exists to avoid. No stamp, no row.
    if let validAsOf = prices.validAsOf, !validAsOf.isEmpty {
      rows.append(
        DetailRow(
          id: "price-valid", label: .key("detail.fact.pricesRead"),
          value: .verbatim(format.storeDate(validAsOf)),
          caveat: .key("price.staleCaveat")))
    }
    if let source = prices.sourceURL {
      rows.append(
        DetailRow(
          id: "price-source", label: .key("detail.fact.tariffPage"), value: .verbatim(source)))
    }
  }
  if let seconds = detail.lastAdmissionBeforeSeconds {
    rows.append(
      DetailRow(
        id: "last-admission", label: .key("detail.fact.lastAdmission"),
        // The DURATION comes from `Duration`'s own units style, not from a plural catalog
        // entry: Polish's `other` category is the fraction form and is spelled the same as
        // `few` for a feminine noun ("1,5 minuty" / "2 minuty"), so a catalog entry would need
        // two identical forms — which the web's own parity test reads as a copy-paste.
        value: .message(
          Message("detail.lastAdmission.value", ["duration": format.minutes(seconds / 60)]))))
  }
  return rows
}

/// The tariff's own categories, said in words. An arm this binary has not heard of rides
/// through as itself rather than being folded into "Adult", which would misprice somebody.
func priceCategoryLabel(_ category: PriceCategory) -> Message {
  switch category {
  case .adult: return Message("priceCategory.adult")
  case .youth: return Message("priceCategory.youth")
  case .child: return Message("priceCategory.child")
  }
}

public func admissionLabel(_ admission: Admission) -> Message {
  switch admission {
  case .free: return Message("admission.free")
  case .tariff: return Message("admission.tariff")
  // NOT "free": an unstated admission is unknown, and printing "free" would send somebody to a
  // turnstile with no money.
  case .unknown: return Message("admission.unknown")
  }
}

private func seasonRows(_ detail: FacilityDetail, _ format: Format) -> [DetailRow] {
  guard let season = detail.operatingSeason else { return [] }
  return [
    DetailRow(
      id: "season", label: .key("detail.fact.season"),
      value: .message(seasonLabel(season, format)),
      caveat: season.weather == fairOnlyWeather ? .key("season.fairWeatherCaveat") : nil)
  ]
}

/// "May to September", or "1 May to 15 September" — but only when the page said days.
///
/// The MONTH NAMES come from the formatter, never from a table in this file. Polish alone
/// settles it: a hand-written list would be nominative, and even the formatter's standalone
/// names are lower-cased there, which no capitalisation rule applied afterwards could produce.
public func seasonLabel(_ season: OperatingSeason, _ format: Format) -> Message {
  let from = format.monthName(season.startMonth)
  let to = format.monthName(season.endMonth)
  guard season.precision == "day", let startDay = season.startDay, let endDay = season.endDay
  else { return Message("season.range", ["from": from, "to": to]) }
  return Message(
    "season.rangeWithDays",
    [
      "startDay": format.integer(startDay), "from": from,
      "endDay": format.integer(endDay), "to": to,
    ])
}

private func basinRows(_ basin: BasinDetail, _ format: Format) -> [DetailRow] {
  var rows = [
    DetailRow(
      // The basin's NAME is the pool's own word for it ("Hauptbecken", "Lehrschwimmbecken"),
      // so it is the one row label on this sheet that is not a message.
      id: "basin-\(basin.basinID)", label: .verbatim(basin.name),
      value: .message(basinKindLabel(basin.kind)))
  ]
  if let size = basinSize(basin, format) {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-size", label: .key("basin.fact.size"), value: .message(size),
        caveat: physicalSourceCaveat(basin.physicalSource)))
  }
  if let lanes = basin.lanes {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-lanes", label: .key("basin.fact.lanes"),
        value: .verbatim(format.integer(lanes))))
  }
  if let temp = basin.measuredTempC ?? basin.nominalTempC {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-temp", label: .key("basin.fact.water"),
        value: .verbatim(format.temperature(celsius: temp)),
        caveat: basin.measuredTempC == nil ? .key("basin.tempNominalCaveat") : nil))
  }
  if !basin.divingPlatformsM.isEmpty {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-diving", label: .key("basin.fact.diving"),
        value: .verbatim(
          basin.divingPlatformsM.map { format.length(metres: $0) }
            .joined(separator: ", "))))
  }
  if let plan = basin.lanePlanURL {
    rows.append(
      DetailRow(
        id: "basin-\(basin.basinID)-plan", label: .key("basin.fact.lanePlan"),
        value: .verbatim(plan)))
  }
  return rows
}

func basinSize(_ basin: BasinDetail, _ format: Format) -> Message? {
  switch (basin.lengthM, basin.widthM) {
  case (let length?, let width?):
    return Message(
      "basin.size.lengthByWidth",
      ["length": format.number(length, fractionDigits: 0), "width": format.length(metres: width)])
  case (let length?, nil):
    return Message("basin.size.length", ["length": format.length(metres: length)])
  case (nil, let width?):
    return Message("basin.size.width", ["width": format.length(metres: width)])
  default: return nil
  }
}

public func basinKindLabel(_ kind: String) -> Message {
  switch kind {
  case "swimmer", "non_swimmer", "diving", "learner", "paddling", "multi_purpose", "thermal",
    "outdoor":
    return Message("basinKind.\(kind)")
  default:
    return Message(
      "basinKind.unknown", ["kind": kind.replacingOccurrences(of: "_", with: " ").capitalized])
  }
}

/// The `physical_source` caveat, and it is the reason that field is exported at all: a
/// dimension read out of a sentence is a weaker fact than a published one, and the sheet says
/// which it is holding.
func physicalSourceCaveat(_ source: String) -> Wording? {
  source == "parsed_prose" ? .key("basin.parsedProseCaveat") : nil
}

private func featureRows(
  _ feature: FeatureDetail, on day: String, _ localized: Localized
) -> [DetailRow] {
  let format = localized.format
  // A feature's own NAME is the pool's word for it; only the fallback is ours.
  let name: Wording =
    feature.name.map { Wording.verbatim($0) } ?? .message(featureKindLabel(feature.kind))
  var rows = [
    DetailRow(
      id: "feature-\(feature.key)", label: name,
      value: .message(featureKindLabel(feature.kind)),
      caveat: feature.note.map { .verbatim($0) })
  ]
  if let surcharge = feature.surchargeCHF {
    rows.append(
      DetailRow(
        id: "feature-\(feature.key)-fee", label: .key("feature.fact.surcharge"),
        value: .verbatim(format.money(chf: surcharge))))
  }
  if let temp = feature.tempC {
    rows.append(
      DetailRow(
        id: "feature-\(feature.key)-temp", label: .key("feature.fact.temperature"),
        value: .verbatim(format.temperature(celsius: temp))))
  }
  if let resolved = feature.day(day) {
    rows.append(
      DetailRow(
        id: "feature-\(feature.key)-hours", label: .key("feature.fact.hours"),
        value: featureHours(resolved, localized)))
  }
  return rows
}

/// A feature's hours for one date. "Not listed for this date" is deliberately NOT "closed": a
/// feature with no windows and no stated reason is unscheduled, not shut.
///
/// The closed arm NESTS one message inside another, so the clause is RENDERED here and
/// interpolated as a value. Passing the clause's KEY would have printed
/// "Closed — closureClause.out_of_season" on the sheet, in all five languages: a nested lookup
/// happens nowhere by itself, and the outer message has no way to ask for one.
///
/// THREE places do this, not one, and they are worth knowing together because each needs a
/// `Localized` at a call site that would otherwise only need a `Format`: here,
/// `TimeAxis.a11yLabel` (which puts a rendered access name inside `a11y.blockLabel`), and
/// `LaneHold.spoken` (which puts either a club's name or a rendered "open to the public" inside
/// `lane.spoken`). All three interpolate a NOUN PHRASE into a frame, which is ordinary i18n;
/// none of them builds a sentence out of sentence fragments, which is the thing this project
/// forbids.
func featureHours(_ day: FeatureDay, _ localized: Localized) -> Wording {
  if !day.windows.isEmpty {
    // A list of times is a list of VALUES; the separator is punctuation, not grammar.
    return .verbatim(
      day.windows.map { "\($0.start.hhmm)–\($0.end.hhmm)" }.joined(separator: ", "))
  }
  if let reason = day.closedReason {
    return .message(
      Message("feature.closed", ["reason": localized(closedReasonClause(reason))]))
  }
  return .key("feature.hoursNotListed")
}

/// The lower-case clause that goes INSIDE `feature.closed`.
///
/// A fragment, and worded as one in every catalog — which is exactly why it is the only nesting
/// this design allows. An unrecognised code rides through the passthrough clause as ITSELF, so
/// a store built by a newer export states its own reason rather than rendering "Closed — ",
/// which would be a bare closure with nothing behind it.
func closedReasonClause(_ reason: String) -> Message {
  switch reason {
  case "out_of_season", "no_sessions", "closure": return Message("closureClause.\(reason)")
  default:
    return Message(
      "closureClause.unknown", ["reason": reason.replacingOccurrences(of: "_", with: " ")])
  }
}

public func featureKindLabel(_ kind: String) -> Message {
  switch kind {
  case "sauna", "gastronomy", "sunbathing", "playground", "slide", "wellness", "sport":
    return Message("featureKind.\(kind)")
  default:
    return Message(
      "featureKind.unknown", ["kind": kind.replacingOccurrences(of: "_", with: " ").capitalized])
  }
}

private func lockerRow(_ locker: LockerDetail, _ format: Format) -> DetailRow {
  DetailRow(
    id: "locker-\(locker.ordinal)",
    label: .message(lockerCategoryLabel(locker.category)),
    value: feeLabel(
      amount: locker.feeCHF, deposit: locker.depositCHF, period: locker.period, format),
    // The pool's own line, kept beside the parsed fields: the parse is lossy, and where the
    // two disagree the source's words are the fact.
    caveat: locker.raw.map { .verbatim($0) })
}

public func lockerCategoryLabel(_ category: String) -> Message {
  switch category {
  case "wardrobe", "valuables", "cabin": return Message("lockerKind.\(category)")
  default:
    return Message(
      "lockerKind.unknown",
      ["kind": category.replacingOccurrences(of: "_", with: " ").capitalized])
  }
}

private func rentalRow(_ rental: RentalDetail, _ format: Format) -> DetailRow {
  DetailRow(
    id: "rental-\(rental.ordinal)",
    label: .message(rentalKindLabel(rental.kind)),
    value: rentalFeeLabel(rental, format),
    caveat: rental.raw.map { .verbatim($0) })
}

public func rentalKindLabel(_ kind: String) -> Message {
  switch kind {
  case "towel", "locker", "deck_chair", "swim_aid": return Message("rentalKind.\(kind)")
  default:
    return Message(
      "rentalKind.unknown", ["kind": kind.replacingOccurrences(of: "_", with: " ").capitalized])
  }
}

/// The rental fee union, kept CLOSED: a stated-gratis rental and an unstated one are different
/// facts, and rendering both as "free" would invent a price for the second.
func rentalFeeLabel(_ rental: RentalDetail, _ format: Format) -> Wording {
  switch rental.fee {
  case "gratis": return .key("fee.free")
  case "priced":
    return feeLabel(
      amount: rental.feeCHF, deposit: rental.depositCHF, period: rental.period, format)
  default: return .key("fee.unstated")
  }
}

/// The fee, its period and its deposit — as a MESSAGE PER PART, joined by punctuation.
///
/// The parts are a visual list, not a sentence: each is a whole translatable unit and the
/// comma between them is punctuation. That is the same distinction the web's `insight.*`
/// clauses make. What it is NOT is a sentence assembled from fragments — none of these three
/// depends grammatically on another, which is exactly why the join is safe here and was not
/// safe for `LaneAvailability.summary`'s "— some lanes unreadable".
func feeLabel(amount: Double?, deposit: Double?, period: String?, _ format: Format) -> Wording {
  var parts: [Wording] = []
  if let amount {
    parts.append(.message(Message("fee.amount", ["amount": format.money(chf: amount)])))
  }
  if let period, !period.isEmpty {
    // The PERIOD is the source's own token ("Tag", "day"), so it rides through as data.
    parts.append(.message(Message("fee.perPeriod", ["period": period])))
  }
  if let deposit {
    parts.append(.message(Message("fee.deposit", ["amount": format.money(chf: deposit)])))
  }
  guard !parts.isEmpty else { return .key("fee.unstated") }
  return .joined(parts)
}

private func lanePanelRows(_ panel: LanePanel, _ format: Format) -> [DetailRow] {
  var rows = [
    DetailRow(
      id: "panel-\(panel.basinID)", label: .verbatim(panel.basinName),
      value: .message(Message("basin.laneCount", count: panel.day.laneCount)),
      // ONE function, one polarity, one sentence — see `LaneDay.incompleteLanesCaveat`. This
      // used to test `confidence == "partial"` while the Gantt tested `!= "complete"`, so the
      // two surfaces disagreed about the same basin for any other token.
      caveat: panel.day.incompleteLanesCaveat.map { .message($0) })
  ]
  if let best = panel.bestPublic {
    rows.append(
      DetailRow(
        id: "panel-\(panel.basinID)-best", label: .key("legend.lane.best"),
        value: .message(
          Message(
            "panel.bestWindow",
            ["start": best.window.start.hhmm, "end": best.window.end.hhmm],
            count: best.publicLanes))))
  }
  rows += panel.roster.map { slot in
    DetailRow(
      id: "panel-\(panel.basinID)-\(slot.id)",
      // The club's NAME is a proper noun.
      label: .verbatim(slot.club),
      value: .message(
        Message(
          // NOT a plural entry: the string NAMES lanes without counting them, and
          // `xcstringstool` refuses a plural variation whose forms do not interpolate the
          // number. Its own advice is two top-level keys, which is what these are.
          slot.lanes.count == 1 ? "panel.clubSlot.oneLane" : "panel.clubSlot.manyLanes",
          [
            "start": slot.window.start.hhmm, "end": slot.window.end.hhmm,
            "lanes": slot.lanes.map { format.integer($0) }.joined(separator: ", "),
          ])))
  }
  return rows
}

private func provenanceRows(_ detail: FacilityDetail, _ format: Format) -> [DetailRow] {
  var rows: [DetailRow] = []
  if let source = detail.provenance.source {
    rows.append(
      DetailRow(id: "source", label: .key("prov.fact.readFrom"), value: .verbatim(source)))
  }
  // A machine date again, and the one a swimmer is most likely to weigh: "how old is this?".
  // Same guard, same reason — the exporter can write an empty stamp, and "Accurate as of"
  // followed by nothing answers that question with silence rather than with "we do not know".
  if let validAsOf = detail.provenance.validAsOf, !validAsOf.isEmpty {
    rows.append(
      DetailRow(
        id: "valid-as-of", label: .key("prov.fact.accurateAsOf"),
        value: .verbatim(format.storeDate(validAsOf))))
  }
  rows.append(
    DetailRow(
      id: "curated", label: .key("prov.fact.curation"),
      value: detail.provenance.curated ? .key("prov.curated.yes") : .key("prov.curated.no")))
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

// MARK: - The live water temperature, said honestly

/// One live-water row, plus the two facts a view needs in order not to lie with it.
///
/// `hasReading` is what the tests assert against: it is false for EVERY unavailable state, and
/// the row's value in that case is a sentence — never a number, never a dash, never a zero. A
/// dash reads as "cold" beside a °C label, and a zero is a temperature somebody might swim in.
///
/// `isStale` does not change what is SAID — the age is stated either way. It is carried onto the
/// row as `DetailRow.muted`, which the sheet renders in the secondary style, so a reading taken
/// nine hours ago does not sit in the same visual register as one taken nine minutes ago.
public struct LiveWaterRow: Equatable, Sendable {
  public let row: DetailRow
  public let hasReading: Bool
  public let isStale: Bool
}

/// The live reading, as the sheet says it. The port of the web's `liveTempText`, arm for arm.
///
/// THE WHOLE POINT IS THE CLOCK. A reading is a fact about an instant, so its age is derived
/// HERE from `now` — not stored when it was fetched, and never omitted for a reading old enough
/// that omitting it would present last March's water as this morning's.
public func liveWaterRow(
  _ live: LiveTemp, at now: Date, in localized: Localized
)
  -> LiveWaterRow
{
  switch live {
  case .unavailable(let reason):
    // The CODE, never the technical reason: "no baditicker key" reaching a reader is jargon in
    // every language, which is what the web's pseudolocale pass found.
    return LiveWaterRow(
      row: DetailRow(
        id: "live-water", label: .key("detail.fact.liveWater"),
        value: .key(reason.messageKey), muted: true),
      hasReading: false, isStale: false)
  case .reading(let reading):
    return LiveWaterRow(
      row: DetailRow(
        id: "live-water", label: .key("detail.fact.liveWater"),
        value: liveWaterValue(reading, localized.format),
        caveat: liveWaterCaveat(reading, at: now, in: localized),
        // Muted for the two weaker answers, exactly as the web mutes them: a stale reading,
        // and an empty sensor cell ("not yet measured", which is a live answer but not a
        // measurement).
        muted: reading.celsius == nil || reading.isStale(at: now)),
      hasReading: reading.celsius != nil,
      isStale: reading.isStale(at: now))
  }
}

/// The reading itself: a temperature, or the honest "not yet measured" for the empty cell five
/// of the feed's rows ship. `LiveTemp.reading` with no celsius is a LIVE answer — the bath is
/// there, the sensor has not reported — and rendering it as 0 °C is the invented number this
/// whole type exists to prevent.
private func liveWaterValue(_ reading: TempReading, _ format: Format) -> Wording {
  guard let celsius = reading.celsius else { return .key("detail.notYetMeasured") }
  return .verbatim(format.temperature(celsius: celsius))
}

/// When it was measured — the fact that keeps a reading from being read as "now".
///
/// An unmeasured cell carries the feed's open/closed state instead, when it has one, because
/// "not yet measured" plus "open" is a different (and more useful) statement than "not yet
/// measured" alone. An absent cell is UNKNOWN, not closed, so it carries nothing.
///
/// A reading stamped in the FUTURE says only "measured", with no age: our clock and the feed's
/// disagree, and "measured -3 min ago" is worse than saying less.
private func liveWaterCaveat(
  _ reading: TempReading, at now: Date, in localized: Localized
)
  -> Wording?
{
  guard reading.celsius != nil else {
    switch reading.isOpen {
    case true: return .key("detail.liveOpen")
    case false: return .key("detail.liveClosed")
    default: return nil
    }
  }
  guard let age = humanizedAge(reading.age(at: now), localized) else {
    return .key("detail.tempMeasured")
  }
  return .message(Message("detail.liveMeasuredAgo", ["age": age]))
}

/// An elapsed interval in the coarsest unit that is still true, exactly as the web's
/// `humanizeAge` picks it: minutes under an hour, hours under a day, days beyond.
///
/// Nil for a negative interval — see `liveWaterCaveat`. Zero minutes is NOT nil: "measured 0 min
/// ago" is true, and a reading taken this minute is the one case where "now" is honest.
func humanizedAge(_ interval: TimeInterval, _ localized: Localized) -> String? {
  guard interval >= 0 else { return nil }
  let minutes = Int(interval / 60)
  if minutes < 60 {
    return renderedAge("age.minutes", minutes, localized)
  }
  let hours = Int((Double(minutes) / 60).rounded())
  if hours < 24 {
    return renderedAge("age.hours", hours, localized)
  }
  return renderedAge("age.days", Int((Double(minutes) / (60 * 24)).rounded()), localized)
}

/// `age.minutes` and `age.hours` interpolate a formatted number; `age.days` is a PLURAL entry
/// and selects on the count, so it must reach Foundation as an integer. The difference comes
/// from the web catalogs and is not ours to smooth over — it is why this goes through the
/// generated table rather than through one hand-written branch.
private func renderedAge(_ key: String, _ count: Int, _ localized: Localized) -> String {
  localized(Message(key, ["count": localized.format.integer(count)], count: count))
}
