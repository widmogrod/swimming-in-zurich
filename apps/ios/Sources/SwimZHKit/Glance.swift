// Glance.swift — the three numbers a swimmer wants before any other fact, and the lane plan.
//
// "Water temperature, number of lanes and lane length — at a glance; currently it's buried
// somewhere below." It was: each lived as a labelled row inside the "Basins" section of the
// facts list, under the address, the phone and the website — three things the header's action
// buttons already act on. So the sheet now leads with these three as a strip under the pool's
// name (`PoolGlance` in the app), and the contact rows move down to where a string belongs.
//
// THE KIT DECIDES, THE VIEW DRAWS — the same split as `detailSections`, and for the same
// reason: which basin's number to show, whether a live reading beats a published one, and
// what a stale reading is called are rules, and a rule inside a `body` is a rule nothing can
// test. `GlanceFact.phrase` is what the line shows; `caption` is what VoiceOver says first.
// Every fact here is ALSO still a row in the list below, so `FieldCoverage`'s rendered claims
// are unchanged; the strip is a second, earlier reading of facts the sheet already has.
//
// HONESTY RULES, in one place:
//  * WATER. The live feed's reading wins when it has a number: it is a measurement of the water
//    the reader would swim in, and the caption says "live". Stale (hours old) it is still
//    shown, MUTED, under a caption that says "earlier" — the same rule `liveWaterRow` mutes by.
//    With no live number the published basin temperature stands in, and a NOMINAL one (the
//    pool's stated target, not a measurement) says so in its caption rather than passing as a
//    reading. No number at all: no item. A blank would be a claim.
//  * LENGTH and LANES come from the pool's LONGEST basin, because "how long is the pool" means
//    the lap basin, never the paddling pool beside it. A lane count no basin publishes falls
//    back to the day's Belegungsplan, which counts the lanes it schedules — the one other
//    place the number exists.
//  * A `LanePlanLink` exists only for a basin with a published plan URL: the button appears for
//    seven pools today and for none of the others, exactly like Call for a pool with no phone.

import Foundation

/// One item of the glance line: a number as a phrase, what it is, and how much to trust it.
public struct GlanceFact: Equatable, Sendable, Identifiable {
  public let id: String
  /// The SF Symbol drawn beside the number.
  public let symbol: String
  /// What the number is, and how far to trust it: "Live water", "Water, as stated", "Length",
  /// "Lanes". Spoken by VoiceOver before the phrase; the line itself shows only the phrase.
  public let caption: Wording
  /// The number as a self-contained phrase: "27 °C", "50 m", "6 lanes".
  public let phrase: Wording
  /// A weaker fact, drawn as one — a live reading hours old. Same rule as `DetailRow.muted`.
  public let muted: Bool
}

/// One basin's published Belegungsplan, as something a button can open.
public struct LanePlanLink: Equatable, Sendable, Identifiable {
  public let basinID: String
  /// The basin's own name, the pool's word for it — the menu label when a pool has two plans.
  public let basinName: String
  public let url: String

  public var id: String { basinID }
}

/// The symbols the strip draws, kept beside the rule that picks them so a number and its
/// glyph cannot drift apart.
public enum GlanceSymbol {
  public static let water = "thermometer.medium"
  public static let length = "ruler"
  public static let lanes = "water.waves"
}

/// The glance strip for one pool: water, then length, then lanes — the order a lap swimmer
/// asks them in. Empty for a pool that publishes none of the three (every lake and river bath
/// today), and the view then draws nothing rather than a row of blanks.
public func glanceFacts(
  _ detail: FacilityDetail, live: LiveTemp?, at now: Date, in localized: Localized
) -> [GlanceFact] {
  let format = localized.format
  var facts: [GlanceFact] = []
  if let water = waterFact(detail, live: live, at: now, format) { facts.append(water) }
  let lap = longestBasin(detail.basins)
  if let length = lap?.lengthM {
    let text = format.length(metres: length)
    facts.append(
      GlanceFact(
        id: "length", symbol: GlanceSymbol.length, caption: .key("glance.length"),
        phrase: .verbatim(text), muted: false))
  }
  if let lanes = lap?.lanes ?? scheduledLaneCount(detail.lanePanels) {
    facts.append(
      GlanceFact(
        id: "lanes", symbol: GlanceSymbol.lanes, caption: .key("glance.lanes"),
        phrase: .message(Message("basin.laneCount", count: lanes)), muted: false))
  }
  return facts
}

/// Every basin's published plan, in the store's basin order. See the header for why a pool
/// without one gets no link at all.
public func lanePlanLinks(_ detail: FacilityDetail) -> [LanePlanLink] {
  detail.basins.compactMap { basin in
    basin.lanePlanURL.map { LanePlanLink(basinID: basin.basinID, basinName: basin.name, url: $0) }
  }
}

/// The live number when there is one, else the published one; nil when neither exists.
private func waterFact(
  _ detail: FacilityDetail, live: LiveTemp?, at now: Date, _ format: Format
) -> GlanceFact? {
  if case .reading(let reading)? = live, let celsius = reading.celsius {
    let stale = reading.isStale(at: now)
    return water(
      celsius, caption: stale ? "glance.water.stale" : "detail.fact.liveWater", muted: stale,
      format)
  }
  // The first basin that publishes any temperature: a pool states one per bath, and the
  // "main" basin is the one it states it for.
  if let basin = detail.basins.first(where: { $0.measuredTempC ?? $0.nominalTempC != nil }) {
    if let measured = basin.measuredTempC {
      return water(measured, caption: "basin.fact.water", muted: false, format)
    }
    if let nominal = basin.nominalTempC {
      return water(nominal, caption: "glance.water.nominal", muted: false, format)
    }
  }
  return nil
}

private func water(
  _ celsius: Double, caption: String, muted: Bool, _ format: Format
) -> GlanceFact {
  let text = format.temperature(celsius: celsius)
  return GlanceFact(
    id: "water", symbol: GlanceSymbol.water, caption: .key(caption), phrase: .verbatim(text),
    muted: muted)
}

/// The lap basin: the longest one that publishes a length. A basin with no length cannot be
/// the longest, so a pool whose basins state no dimensions has no lap basin here.
private func longestBasin(_ basins: [BasinDetail]) -> BasinDetail? {
  basins.filter { $0.lengthM != nil }.max { ($0.lengthM ?? 0) < ($1.lengthM ?? 0) }
}

/// The lane count the day's Belegungsplan schedules, when no basin publishes one. The largest
/// across the pool's panels, which for every pool today is its one lap basin.
private func scheduledLaneCount(_ panels: [LanePanel]) -> Int? {
  panels.map(\.day.laneCount).max()
}
