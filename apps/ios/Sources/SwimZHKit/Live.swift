// Live.swift — the ONE place in this app that reads live water temperature, and one of the two
// files in either target permitted to touch the network at all.
//
// THE OFFLINE FLOOR IS NOT NEGOTIABLE. Everything this app answers — schedules, prices, lane
// plans, features, search, distance — comes out of the bundled store and needs no network ever.
// A live water temperature is the one fact that cannot be baked, because it is a READING AT AN
// INSTANT: the moment it were written into a weekly file it would be presented as current for a
// week. So the key rides in the store (`pool.baditicker_poiid`) and the reading is fetched here,
// or not at all.
//
// WHAT "OR NOT AT ALL" MEANS, precisely. A failed fetch, an absent key, a bath the feed does not
// carry, an unparseable timestamp — every one of them is `.unavailable(reason)`, which renders
// as a sentence saying so. NEVER a zero. NEVER a dash that reads as "cold". NEVER the previous
// reading dressed as the current one. This is the eighth appearance of one bug class in this
// plan (see the ledger) and it is the most dangerous shape it has taken, because a temperature
// is a plausible number: 4 °C from March looks exactly like 4 °C from this morning.
//
// AGE IS DERIVED, NEVER STORED. `TempReading` carries `measuredAt` and nothing else about
// freshness; `age(at:)` and `isStale(at:)` take the clock as an argument. That mirrors
// `domain/query.LiveTemp`, whose docstring says the same thing for the same reason, and it is
// what makes the 2-minute response cache below safe: a cached reading served 119 seconds later
// reports an age 119 seconds larger, not the age it had when it was fetched.
//
// THE CACHE IS THE WEB'S, deliberately: `providers/baditicker.py` holds one 120-second TTL over
// a poiid→reading map so many per-pool reads cost one fetch. The same window here means the two
// clients are as fresh as each other, and a reader flicking between four pools' sheets makes one
// request rather than four.

import Foundation

/// The feed, as it reaches this module.
///
/// A protocol rather than a `URLSession` call at the point of use, because the whole of S5
/// acceptance 1 is about what happens when this FAILS — and a test that needed a real network
/// to prove the offline state would be a test that proves it on a good day.
public protocol HTTPFetching: Sendable {
  func data(from url: URL) async throws -> Data
}

/// The real transport. The only `URLSession` in either target, together with `Refresh.swift`'s
/// download — which is exactly what `SourceLintTests.noNetwork` now asserts.
public struct URLSessionFetcher: HTTPFetching {
  private let timeout: TimeInterval

  public init(timeout: TimeInterval = 10) {
    self.timeout = timeout
  }

  public func data(from url: URL) async throws -> Data {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.timeoutIntervalForRequest = timeout
    // No disk cache: a cached HTTP response would be a reading whose age this module cannot
    // see. Freshness here is the reading's own `dateModified`, and the only cache is the
    // explicit 2-minute one below, which keeps `measuredAt` intact.
    configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
    configuration.urlCache = nil
    let session = URLSession(configuration: configuration)
    defer { session.finishTasksAndInvalidate() }
    let (data, response) = try await session.data(from: url)
    if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
      throw LiveError.status(http.statusCode)
    }
    return data
  }
}

public enum LiveError: Error, Equatable {
  case status(Int)
  case unreadable
}

// MARK: - What a reading is

/// One bath's live water temperature, as the feed states it.
///
/// `celsius` is optional and that is a REAL STATE, not a decoding convenience: SIX of the
/// recorded feed's 25 rows ship an empty temperature cell, and the honest reading of one is "not
/// yet measured" — never 0 °C. `isOpen` is optional for the same reason, and FIVE rows ship an
/// empty one: an absent cell is unknown, not closed. (Both counts are read off the fixture
/// rather than remembered — the previous sentence had one of them wrong, and they are
/// load-bearing.)
public struct TempReading: Equatable, Sendable {
  public let measuredAt: Date
  public let celsius: Double?
  public let isOpen: Bool?
  public let source: String

  public init(measuredAt: Date, celsius: Double?, isOpen: Bool?, source: String = "baditicker") {
    self.measuredAt = measuredAt
    self.celsius = celsius
    self.isOpen = isOpen
    self.source = source
  }

  /// How old this reading is at `now`. Derived, always — see the header.
  ///
  /// Negative when the feed's clock is ahead of ours. That is not folded to zero: a caller
  /// that cannot state an age truthfully states none, which is what `liveWaterRow` does.
  public func age(at now: Date) -> TimeInterval {
    now.timeIntervalSince(measuredAt)
  }

  /// Six hours, matching `domain/query.LiveTemp.is_stale`'s default. Water temperature is
  /// measured a few times a day, so the web's 10-minute occupancy limit would call every
  /// reading stale; the two limits are different because the two facts move at different
  /// speeds, not because one side is sloppier.
  public static let stalenessLimit: TimeInterval = 6 * 60 * 60

  public func isStale(at now: Date, limit: TimeInterval = TempReading.stalenessLimit) -> Bool {
    age(at: now) > limit
  }
}

/// Why there is no reading. The i18n key space for that answer — `live.no_key`,
/// `live.provider_error`, `live.not_configured` are catalog keys the web already renders, so
/// this app says the same three things in the same five languages.
///
/// The raw technical reason (an HTTP status, a parse failure) is deliberately NOT carried to
/// the reader: the web learned in its pseudolocale pass that "no baditicker key" reaching a
/// user is both untranslated and jargon.
public enum LiveUnavailable: String, Equatable, Sendable, CaseIterable {
  /// This pool publishes no live temperature — there is nothing to ask for.
  case noKey = "no_key"
  /// The feed was asked and could not answer: offline, a bad status, unparseable markup, or a
  /// bath the feed does not carry.
  case providerError = "provider_error"
  /// No live source is wired at all — a deployment state, not a failure.
  case notConfigured = "not_configured"

  /// The catalog key for this state, as the web spells it.
  public var messageKey: String { "live.\(rawValue)" }
}

/// A live water temperature, or the honest reason there is not one. There is no third state,
/// and in particular there is no "unknown" that renders as blank.
public enum LiveTemp: Equatable, Sendable {
  case reading(TempReading)
  case unavailable(LiveUnavailable)
}

// MARK: - The feed

/// The Baditicker OGD feed: one `<bath>` record per bath, keyed by `<poiid>`.
///
/// Parsed by scanning for element bounds rather than with an XML parser, exactly as
/// `providers/baditicker.py` does and for the same reason: the markup is flat, and a real
/// parser brings an external-entity surface this app has no use for. A record that does not
/// parse is DROPPED — never defaulted — so a malformed row costs one pool its badge instead of
/// giving every pool a wrong number.
public enum Baditicker {
  public static let feedURL = URL(string: "https://www.stadt-zuerich.ch/stzh/bathdatadownload")

  /// The inner text of `<tag>…</tag>` inside `block`, CDATA-unwrapped and trimmed.
  ///
  /// Nil when the element is absent; `""` when it is present and empty — the distinction the
  /// empty-cell state depends on.
  static func element(_ tag: String, in block: Substring) -> String? {
    guard let open = block.range(of: "<\(tag)", options: .caseInsensitive),
      let openEnd = block[open.upperBound...].firstIndex(of: ">"),
      let close = block.range(of: "</\(tag)>", options: .caseInsensitive),
      close.lowerBound >= openEnd
    else { return nil }
    var inner = block[block.index(after: openEnd)..<close.lowerBound]
      .trimmingCharacters(in: .whitespacesAndNewlines)
    if inner.hasPrefix("<![CDATA[") && inner.hasSuffix("]]>") {
      inner = String(inner.dropFirst(9).dropLast(3)).trimmingCharacters(
        in: .whitespacesAndNewlines)
    }
    return inner
  }

  /// The feed's German timestamp — an optional weekday token, then `dd.MM.yyyy HH:mm` — as an
  /// instant in Zurich.
  ///
  /// Every component is RANGE-CHECKED and the result is round-tripped back to its day key
  /// before it is returned. That is not belt-and-braces: `Calendar.date(from:)` happily rolls
  /// `2026-13-45` forward into 2027, so a corrupt feed cell would otherwise yield a plausible
  /// wrong instant — and an instant is what every age and staleness claim is measured from.
  static func timestamp(_ text: String?) -> Date? {
    guard let text else { return nil }
    let digits = text.split(whereSeparator: { !$0.isNumber })
    guard digits.count >= 5 else { return nil }
    // The weekday token ("Sa.") carries no digits, so the first five runs are the date and
    // time in order.
    let numbers = digits.prefix(5).compactMap { Int($0) }
    guard numbers.count == 5 else { return nil }
    let (day, month, year, hour, minute) = (
      numbers[0], numbers[1], numbers[2], numbers[3], numbers[4]
    )
    guard (1...31).contains(day), (1...12).contains(month), (2000...2100).contains(year),
      (0...23).contains(hour), (0...59).contains(minute)
    else { return nil }
    let key = String(format: "%04d-%02d-%02d", year, month, day)
    guard
      let instant = ZurichClock.instant(day: key, at: TimeOfDay(hour: hour, minute: minute)),
      ZurichClock.day(of: instant) == key
    else { return nil }
    return instant
  }

  /// `poiid → reading` for every record the feed carries and this parser understands.
  public static func parse(_ data: Data) -> [String: TempReading] {
    guard let text = String(data: data, encoding: .utf8) else { return [:] }
    var readings: [String: TempReading] = [:]
    for block in blocks(of: text) {
      guard let poiid = element("poiid", in: block), !poiid.isEmpty,
        let measuredAt = timestamp(element("dateModified", in: block))
      else { continue }
      let cell = element("temperatureWater", in: block) ?? ""
      // An empty cell is "not yet measured", a non-numeric one is a defect: neither may become
      // a number, so both leave `celsius` nil and only the empty one is a live answer.
      let celsius = cell.isEmpty ? nil : Double(cell)
      if !cell.isEmpty && celsius == nil { continue }
      readings[poiid] = TempReading(
        measuredAt: measuredAt,
        celsius: celsius,
        isOpen: openState(element("openClosedTextPlain", in: block)),
        source: "baditicker"
      )
    }
    return readings
  }

  /// The feed's open/closed cell. An absent or empty cell is UNKNOWN, not closed — five of the
  /// recorded feed's 25 rows ship one, and reading them as closed reported open baths as shut.
  ///
  /// Unrecognised wording is unknown too, which is where this deliberately differs from
  /// `baditicker.py` (it reads anything that is not exactly `offen` as CLOSED) — see the header.
  static func openState(_ cell: String?) -> Bool? {
    guard let cell, !cell.isEmpty else { return nil }
    let folded = cell.lowercased()
    if folded.contains("geöffnet") || folded.contains("offen") { return true }
    if folded.contains("geschlossen") { return false }
    return nil
  }

  static func blocks(of text: String) -> [Substring] {
    var found: [Substring] = []
    var cursor = text.startIndex
    while let open = text.range(
      of: "<bath", options: .caseInsensitive, range: cursor..<text.endIndex),
      let close = text.range(
        of: "</bath>", options: .caseInsensitive, range: open.upperBound..<text.endIndex)
    {
      found.append(text[open.lowerBound..<close.upperBound])
      cursor = close.upperBound
    }
    return found
  }
}

/// The live client: one fetch serves every pool for two minutes.
///
/// An actor because the cache is shared mutable state read from whichever task a sheet opened
/// on, and because two sheets opened at once must not become two fetches.
public actor LiveClient {
  /// A whole feed read, cached with the instant it was read at. The FAILURE is cached too, and
  /// on purpose: offline, every sheet opened would otherwise start a request that cannot
  /// succeed, and the honest answer is already known for the next two minutes.
  private enum Snapshot {
    case readings([String: TempReading])
    case failed
  }

  private let fetcher: HTTPFetching
  private let url: URL?
  private let ttl: TimeInterval
  private var snapshot: (value: Snapshot, at: Date)?

  /// How often an OPEN sheet should ask again, so the age it prints stays true.
  ///
  /// This is not the cache window and must not be confused with it. The TTL below decides how
  /// often the FEED is read; this decides how often the SENTENCE is rebuilt. A reading fetched
  /// once and rendered once says "measured 3 min ago" for as long as the sheet is open — the
  /// same understating shape of temporal claim this plan has now hit repeatedly — and the
  /// wording changes at minute granularity, so a minute is the interval that keeps it honest.
  /// Most of these re-asks are served from the cache and cost no request at all.
  public static let reaskInterval: TimeInterval = 60

  /// - Parameter ttl: 120 seconds, matching `providers/baditicker.py`'s `_DEFAULT_TTL`, so the
  ///   phone and the web are never more than the same window apart from the feed.
  public init(
    fetcher: HTTPFetching = URLSessionFetcher(),
    url: URL? = Baditicker.feedURL,
    ttl: TimeInterval = 120
  ) {
    self.fetcher = fetcher
    self.url = url
    self.ttl = ttl
  }

  /// This pool's live water temperature, or the honest reason there is none.
  ///
  /// Never throws: an error here is a STATE the reader is shown, not an exception that empties
  /// a screen. That is the same errors-as-values stance the Python providers take at their own
  /// boundary.
  public func temperature(poiid: String?, now: Date = Date()) async -> LiveTemp {
    guard let poiid, !poiid.isEmpty else { return .unavailable(.noKey) }
    guard url != nil else { return .unavailable(.notConfigured) }
    switch await snapshot(now: now) {
    case .failed:
      return .unavailable(.providerError)
    case .readings(let readings):
      // A bath the feed does not carry is a provider gap, not a missing key: the store said
      // this pool HAS one, so "no key" would be a different — and false — statement.
      guard let reading = readings[poiid] else { return .unavailable(.providerError) }
      return .reading(reading)
    }
  }

  /// Discard the cached feed read. For a pull-to-refresh, and for tests that need the next
  /// call to go back to the transport.
  public func invalidate() {
    snapshot = nil
  }

  private func snapshot(now: Date) async -> Snapshot {
    if let snapshot, now.timeIntervalSince(snapshot.at) < ttl, now >= snapshot.at {
      return snapshot.value
    }
    let value = await read()
    snapshot = (value, now)
    return value
  }

  private func read() async -> Snapshot {
    guard let url else { return .failed }
    do {
      let readings = Baditicker.parse(try await fetcher.data(from: url))
      // An empty parse is a failure, not an empty feed: the real feed carries 25 records, so
      // zero means the markup changed under us and every pool would silently lose its badge.
      return readings.isEmpty ? .failed : .readings(readings)
    } catch {
      return .failed
    }
  }
}
