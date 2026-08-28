// LiveTests — the live water temperature, and the one thing it must never do.
//
// THE BUG CLASS THIS SUITE EXISTS FOR. Eight times in this plan a value that is only true at an
// instant has been rendered as if it were true generally: "Open now" on a date four months out,
// "Done for today" on every future day, "no lanes open to the public" beside "Opens 06:00",
// six raw ISO dates in five languages. A temperature is the most dangerous shape yet, because a
// wrong one is PLAUSIBLE — 4 °C from last March looks exactly like 4 °C from this morning, and
// nothing on the screen would contradict it.
//
// So the assertions here are about three things, in order of how badly they would hurt:
//   1. an unavailable reading NEVER renders a number (not zero, not a dash beside a °C label);
//   2. a reading ALWAYS states its age, derived from the clock at render time — a stale one
//      loudly, never silently;
//   3. every one of those sentences exists in all five languages, swept rather than sampled.
//
// The parser is proved against `tests/providers/fixtures/baditicker.xml` — the SAME recorded feed
// body `providers/baditicker.py` is pinned to. On that body the two clients agree, because its
// `openClosedTextPlain` vocabulary is exactly `""` / `offen` / `geschlossen` — pinned by
// `test_baditicker.py::test_the_recorded_feeds_open_vocabulary_is_the_one_both_clients_assume`.
//
// They are NOT identical parsers, and the earlier claim that they "cannot read the feed
// differently" was false: `baditicker.py:120` reads `open_cell.lower() == "offen"`, so any
// unrecognised wording — `geöffnet`, say — becomes False, i.e. CLOSED. This side
// substring-matches and returns nil, i.e. UNKNOWN, which is the honest answer and the one
// `TempReading.is_open`'s own docstring asks for ("absent is not closed"). The pinned vocabulary
// is what makes a wording change visible on the day it happens rather than silently shutting
// baths on the web.

import Foundation
import Testing

@testable import SwimZHKit

/// A transport that answers from memory, or fails. There is no network anywhere in this suite:
/// the whole point of the seam is that its failure modes are drivable.
private struct FakeFetcher: HTTPFetching {
  let payload: Data?
  let error: (any Error)?
  /// How many times it was asked, so the TTL can be proved rather than assumed.
  let calls: Counter

  final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0
    var count: Int {
      lock.lock()
      defer { lock.unlock() }
      return value
    }
    func increment() {
      lock.lock()
      value += 1
      lock.unlock()
    }
  }

  init(payload: Data? = nil, error: (any Error)? = nil) {
    self.payload = payload
    self.error = error
    self.calls = Counter()
  }

  func data(from url: URL) async throws -> Data {
    calls.increment()
    if let error { throw error }
    guard let payload else { throw LiveError.unreadable }
    return payload
  }
}

@Suite("Live water temperature")
struct LiveTests {
  static let feed: Data = {
    let url = RepoFixtures.root.appending(path: "tests/providers/fixtures/baditicker.xml")
    return (try? Data(contentsOf: url)) ?? Data()
  }()

  static let en = CatalogFixture.localized(.en)
  static let now = Date(timeIntervalSince1970: 1_785_000_000)

  static func reading(
    minutesAgo: Double, celsius: Double? = 21.5, isOpen: Bool? = true
  ) -> TempReading {
    TempReading(
      measuredAt: now.addingTimeInterval(-minutesAgo * 60), celsius: celsius, isOpen: isOpen)
  }

  /// What the sheet's live row SAYS, as one string, in one language.
  static func said(_ live: LiveTemp, at when: Date = now, in localized: Localized) -> String {
    let row = liveWaterRow(live, at: when, in: localized).row
    return [localized.string(row.value), row.caveat.map { localized.string($0) } ?? ""]
      .joined(separator: " ")
  }

  // MARK: - Parsing the real recorded feed

  @Test("the recorded feed parses into readings keyed by poiid")
  func parsesTheRecordedFeed() {
    let readings = Baditicker.parse(Self.feed)
    #expect(readings.count >= 20, "only \(readings.count) records — the parser is missing rows")

    // A specific record, in full: `flb6940` is Flussbad Unterer Letten, 22 °C, open, stamped
    // 25.07.2026 09:03 Zurich. Naming one keeps this from being a count that any regex passes.
    let letten = readings["flb6940"]
    #expect(letten?.celsius == 22)
    #expect(letten?.isOpen == true)
    #expect(
      letten?.measuredAt
        == ZurichClock.instant(day: "2026-07-25", at: TimeOfDay(hour: 9, minute: 3)))
    // ...and a CLOSED one, because "geschlossen" contains neither of the open tokens and a
    // sloppy substring check would report it open.
    #expect(readings["flb6938"]?.isOpen == false)
  }

  @Test("the counts the comments quote are the counts the fixture has")
  func theQuotedCountsAreReal() {
    // Both numbers are load-bearing — they are the evidence for "an empty cell is a real state"
    // — and one of them was wrong in review. Counted here rather than remembered, and pinned on
    // the Python side too (`test_baditicker.py`), so the two implementations' comments cannot
    // drift from the file they both describe.
    let text = String(data: Self.feed, encoding: .utf8) ?? ""
    let baths = Baditicker.blocks(of: text)
    #expect(baths.count == 25)
    #expect(
      baths.filter { (Baditicker.element("temperatureWater", in: $0) ?? "").isEmpty }.count == 6)
    #expect(
      baths.filter { (Baditicker.element("openClosedTextPlain", in: $0) ?? "").isEmpty }.count == 5)
    // The vocabulary both clients rest on. The Swift side answers `nil` for anything else; the
    // Python side answers CLOSED, which is why this set is pinned on both sides.
    let vocabulary = Set(baths.compactMap { Baditicker.element("openClosedTextPlain", in: $0) })
    #expect(vocabulary == ["", "offen", "geschlossen"], "\(vocabulary)")
  }

  @Test("an empty temperature cell is a live reading with no number — never zero")
  func emptyCellIsNotZero() {
    // Five of the feed's rows ship an empty cell. Reading them as 0 °C would put a plausible,
    // freezing, invented number on screen; reading them as "unavailable" would hide that the
    // bath is there and reporting.
    let xml = """
      <baths><bath><poiid>hb999</poiid><temperatureWater></temperatureWater>
      <dateModified><![CDATA[Sa., 25.07.2026 09:03]]></dateModified>
      <openClosedTextPlain><![CDATA[offen]]></openClosedTextPlain></bath></baths>
      """
    let reading = Baditicker.parse(Data(xml.utf8))["hb999"]
    #expect(reading != nil)
    #expect(reading?.celsius == nil)
    #expect(reading?.isOpen == true)

    let said = Self.said(.reading(reading!), in: Self.en)
    #expect(said.contains("Not yet measured"))
    #expect(!said.contains("0"), "an unmeasured cell rendered a number: \(said)")
  }

  @Test("a record with no timestamp, a bad number or a rolled-over date is DROPPED")
  func malformedRecordsAreDropped() {
    // Dropped, never defaulted: a record with no `dateModified` has no age, and a reading with
    // no age is exactly the thing that gets rendered as current.
    let cases = [
      "<bath><poiid>a</poiid><temperatureWater>21</temperatureWater></bath>",
      """
      <bath><poiid>b</poiid><temperatureWater>warm</temperatureWater>
      <dateModified>25.07.2026 09:03</dateModified></bath>
      """,
      // 45th of the 13th month. `Calendar` would roll this into 2027 and hand back a
      // plausible instant — which is why `Baditicker.timestamp` round-trips it.
      """
      <bath><poiid>c</poiid><temperatureWater>21</temperatureWater>
      <dateModified>45.13.2026 09:03</dateModified></bath>
      """,
    ]
    for xml in cases {
      #expect(Baditicker.parse(Data("<baths>\(xml)</baths>".utf8)).isEmpty, "\(xml)")
    }
    // The control: the same record with a valid stamp DOES parse, so the drops above are about
    // the defect and not about the scaffolding.
    let good = """
      <baths><bath><poiid>d</poiid><temperatureWater>21</temperatureWater>
      <dateModified>25.07.2026 09:03</dateModified></bath></baths>
      """
    #expect(Baditicker.parse(Data(good.utf8)).count == 1)
  }

  // MARK: - The client, and what it does when the feed is not there

  @Test("a failing transport is an explicit unavailable state, never an exception or a number")
  func failingTransportDegrades() async {
    // S5 acceptance 1, the assertable half: the app in Airplane Mode. Every path through this
    // client returns a STATE.
    let offline = FakeFetcher(error: URLError(.notConnectedToInternet))
    let client = LiveClient(fetcher: offline, url: URL(string: "https://example.test/feed"))
    let answer = await client.temperature(poiid: "flb6940", now: Self.now)
    #expect(answer == .unavailable(.providerError))

    for (language, localized) in CatalogFixture.all {
      let said = Self.said(answer, in: localized)
      #expect(!said.isEmpty, "\(language) says nothing at all")
      #expect(said.rangeOfCharacter(from: .decimalDigits) == nil, "\(language) shows \(said)")
      #expect(!said.contains("live."), "\(language) leaked the raw key: \(said)")
    }
  }

  @Test("no key is a different state from a failed fetch, and asks the feed nothing")
  func noKeyNeverFetches() async {
    let fetcher = FakeFetcher(payload: Self.feed)
    let client = LiveClient(fetcher: fetcher, url: URL(string: "https://example.test/feed"))
    #expect(await client.temperature(poiid: nil, now: Self.now) == .unavailable(.noKey))
    #expect(await client.temperature(poiid: "", now: Self.now) == .unavailable(.noKey))
    #expect(fetcher.calls.count == 0, "a pool with no key must not cost a request")
  }

  @Test("a bath the feed does not carry is a provider gap, not a missing key")
  func unknownBathIsAProviderGap() async {
    let client = LiveClient(
      fetcher: FakeFetcher(payload: Self.feed), url: URL(string: "https://example.test/feed"))
    #expect(await client.temperature(poiid: "nope", now: Self.now) == .unavailable(.providerError))
  }

  @Test("one fetch serves every pool for two minutes, and the age still grows")
  func theTTLIsTwoMinutes() async {
    // The web's window (`providers/baditicker.py`'s `_DEFAULT_TTL`), so the two clients are
    // never more than the same interval apart from the feed.
    let fetcher = FakeFetcher(payload: Self.feed)
    let client = LiveClient(fetcher: fetcher, url: URL(string: "https://example.test/feed"))
    _ = await client.temperature(poiid: "flb6940", now: Self.now)
    _ = await client.temperature(poiid: "flb6938", now: Self.now.addingTimeInterval(119))
    #expect(fetcher.calls.count == 1, "two pools inside the window cost two requests")
    _ = await client.temperature(poiid: "flb6940", now: Self.now.addingTimeInterval(121))
    #expect(fetcher.calls.count == 2, "the window never expired")

    // AND THE POINT OF THE CACHE BEING SAFE: a reading served from it reports the age it has
    // NOW, not the age it had when it was fetched. Age is derived, never stored.
    guard case .reading(let reading) = await client.temperature(poiid: "flb6940", now: Self.now)
    else {
      Issue.record("no reading")
      return
    }
    let early = reading.age(at: Self.now)
    let later = reading.age(at: Self.now.addingTimeInterval(600))
    #expect(later - early == 600)
  }

  @Test("a feed that parses to nothing is a failure, not an empty feed")
  func emptyParseIsAFailure() async {
    // The real feed carries 25 records. Zero means the markup changed under us — and the
    // difference matters: `.failed` says "no reading", while an empty map would say "this bath
    // is not in the feed" for all 57 pools, which is a different (and wrong) explanation.
    let client = LiveClient(
      fetcher: FakeFetcher(payload: Data("<html>we redesigned</html>".utf8)),
      url: URL(string: "https://example.test/feed"))
    #expect(
      await client.temperature(poiid: "flb6940", now: Self.now) == .unavailable(.providerError))
  }

  // MARK: - What a reading SAYS

  @Test("a reading always states its age, and a stale one is marked as well as stated")
  func everyReadingStatesItsAge() {
    let fresh = liveWaterRow(.reading(Self.reading(minutesAgo: 3)), at: Self.now, in: Self.en)
    #expect(fresh.hasReading)
    #expect(!fresh.isStale)
    #expect(Self.en.string(fresh.row.caveat!).contains("3 min"))

    // Seven hours — past the six-hour limit `domain/query.LiveTemp.is_stale` uses. The row
    // still SAYS the age (that is the honesty), and additionally reports itself stale so the
    // view can mute it rather than presenting it with the weight of a fresh reading.
    let old = liveWaterRow(.reading(Self.reading(minutesAgo: 7 * 60)), at: Self.now, in: Self.en)
    #expect(old.isStale)
    #expect(Self.en.string(old.row.caveat!).contains("7 h"))
    #expect(Self.en.string(old.row.value).contains("21.5"), "the reading itself is still shown")
  }

  @Test("a reading stamped in the future says `measured`, never a negative age")
  func aFutureStampSaysLess() {
    // Our clock and the feed's can disagree. "measured -3 min ago" is worse than saying less,
    // and a folded-to-zero "0 min ago" would be a claim we cannot support.
    let ahead = liveWaterRow(.reading(Self.reading(minutesAgo: -3)), at: Self.now, in: Self.en)
    let said = Self.en.string(ahead.row.caveat!)
    #expect(said == "measured")
    #expect(!said.contains("-"))
  }

  @Test("an unavailable state renders a sentence in every language, and never a digit")
  func unavailableIsASentenceEverywhere() {
    for reason in LiveUnavailable.allCases {
      for (language, localized) in CatalogFixture.all {
        let row = liveWaterRow(.unavailable(reason), at: Self.now, in: localized)
        let said = localized.string(row.row.value)
        #expect(!row.hasReading)
        #expect(!row.isStale)
        #expect(said.count > 2, "\(language)/\(reason.rawValue) says \"\(said)\"")
        #expect(
          said.rangeOfCharacter(from: .decimalDigits) == nil,
          "\(language)/\(reason.rawValue) shows a number: \(said)")
        #expect(said != reason.messageKey, "\(language) has no \(reason.messageKey)")
        #expect(row.row.caveat == nil, "an unavailable reading has no age to state")
      }
    }
  }

  // MARK: - The whole range, in all five languages

  @Test("every age from a minute to the far end of the horizon reads as words, in five languages")
  func theWholeAgeRangeIsWordsInEveryLanguage() {
    // SWEPT, NOT SAMPLED, and the comment says why because this is the third time: S4's first
    // date sweep sampled offsets 0/45/120 and missed the store's only Christmas-Day warning by
    // three days. A sample is a guess about where the bug is.
    //
    // The range covers the whole span a reading can plausibly have — the feed's own stalest
    // rows are 1-2.5 years old (measured in `providers/baditicker.py`'s notes) — at every
    // boundary between the three units and either side of each.
    var minutes: [Int] = Array(0...125)
    minutes += stride(from: 130, through: 60 * 24 * 400, by: 37).map { $0 }
    for (language, localized) in CatalogFixture.all {
      for minute in minutes {
        let live = LiveTemp.reading(Self.reading(minutesAgo: Double(minute)))
        let row = liveWaterRow(live, at: Self.now, in: localized)
        let caveat = try? #require(row.row.caveat)
        let said = caveat.map { localized.string($0) } ?? ""
        #expect(!said.isEmpty, "\(language) at \(minute) min says nothing")
        // No catalog key, no format specifier, no bare token reaching a reader.
        for leak in ["age.", "detail.", "%@", "%d", "%#@"] {
          #expect(!said.contains(leak), "\(language) at \(minute) min leaked \(leak): \(said)")
        }
        // The age is STATED for every reading, at every distance. This is the assertion that
        // fails the day somebody decides an old reading looks tidier without one.
        #expect(said.rangeOfCharacter(from: .decimalDigits) != nil, "\(language): \(said)")
      }
    }
  }

  @Test("the three age units switch where the web's `humanizeAge` switches them")
  func theUnitsMatchTheWeb() {
    // `detailpanel.ts`: minutes under an hour, hours under a day, days beyond — with ROUNDING,
    // not truncation, at the two boundaries. Asserted in English, where the units are readable;
    // the loop above is what proves the other four say something at all.
    let expectations: [(Int, String)] = [
      (0, "0 min"), (59, "59 min"), (60, "1 h"), (89, "1 h"), (90, "2 h"),
      (23 * 60, "23 h"), (24 * 60, "1 day"), (36 * 60, "2 days"), (48 * 60, "2 days"),
    ]
    for (minute, expected) in expectations {
      let row = liveWaterRow(
        .reading(Self.reading(minutesAgo: Double(minute))), at: Self.now, in: Self.en)
      let said = Self.en.string(row.row.caveat!)
      #expect(said == "measured \(expected) ago", "\(minute) min rendered \"\(said)\"")
    }
  }

  @Test("Polish selects a real plural form for the day count, rather than falling back")
  func polishDayPluralsAreReal() {
    // `age.days` is the one plural entry on this path, and Polish is the language the whole
    // plural apparatus exists for: 1 / 2 / 5 take three DIFFERENT forms, and a catalog missing
    // `many` would silently render the decimal form for 5.
    let polish = CatalogFixture.localized(.pl)
    // The NOUN, with the count stripped out. Comparing whole strings would be a test that
    // passes on "2 dni" != "22 dni" — a difference in the number, not in the grammar, which is
    // the only thing a plural rule decides.
    let forms = [1, 2, 5, 22].map { days -> String in
      let row = liveWaterRow(
        .reading(Self.reading(minutesAgo: Double(days * 24 * 60))), at: Self.now, in: polish)
      return polish.string(row.row.caveat!)
        .filter { !$0.isNumber }
        .trimmingCharacters(in: .whitespaces)
    }
    // `pl.ts`: one → "dzień", few → "dni", many → "dni", other → "dnia". So 1 must differ from
    // the rest, and 2 (few) must match 22 (few) — while `other`, the DECIMAL form "dnia", must
    // appear for none of them. That last one is the actual failure mode: a catalog missing
    // `many` falls back to `other` silently, and 5 would read "5 dnia".
    #expect(forms[0] != forms[1], "Polish rendered \(forms) — 1 and 2 take the same form")
    #expect(forms[1] == forms[3], "2 and 22 take the same Polish form (`few`)")
    for form in forms {
      #expect(!form.contains("dnia"), "Polish fell back to the decimal form: \(forms)")
    }
  }

  // MARK: - The store's half of the bargain

  @Test("the store carries the KEY and no reading at all")
  func theStoreCarriesKeysNotReadings() async throws {
    // The other half of the honesty rule, asserted against the committed store: a temperature
    // baked into a weekly file would be shown as current for a week.
    let store = try Store.bundled()
    var keyed = 0
    for pool in try await store.pools() {
      guard let detail = try await store.facility(poolID: pool.id, on: "2026-08-23") else {
        continue
      }
      if let poiid = detail.baditickerPOIID {
        #expect(!poiid.isEmpty)
        keyed += 1
      }
    }
    #expect(keyed >= 20, "only \(keyed) pools carry a Baditicker key — did the export drop it?")
  }
}
