// The facility sheet, as a value (S3b acceptance 4).
//
// The sheet is where this app's honesty caveats live, and a caveat rendered inside a `body` is a
// caveat nothing can test. So every sentence it shows is decided here, and these are the ones
// that would do real harm if they were wrong: an unstated admission rendered as "free" sends
// somebody to a turnstile with no money; a `no_source` schedule rendered as "closed" is the one
// thing the whole four-state vocabulary exists to forbid; a dimension read out of prose stated
// as flatly as a published one overstates what the city said.
//
// SINCE S4 THE SHEET PRODUCES `Message`/`Wording`, NOT ENGLISH. The assertions below are still
// about the SENTENCE — they render through `CatalogFixture.english` — because a check on a key
// would pass on a catalog that says the opposite of what the key is named. And the rules that
// are rules in EVERY language ("never says free", "never says closed", "claims no day", "shows
// an unknown token as itself") loop over all five: those are exactly the rules a translator,
// handed one string out of context, can break without any English assertion noticing.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The facility detail sheet")
struct FacilityDetailTests {
  static let day = "2026-08-24"

  /// The English renderer, and the formatter that goes with it. Most assertions here are about
  /// one sentence, and reading one language keeps them legible.
  static let en = CatalogFixture.english
  static let format = CatalogFixture.english.format

  /// How each language says "free of charge" — stems, matched against folded text so a
  /// diacritic cannot hide one. Polish keeps its `ł`: `.diacriticInsensitive` decomposes `ę`
  /// but NOT `ł`, which is a letter of its own rather than a marked `l` (measured, not assumed).
  static let freeWords: [Language: [String]] = [
    .en: ["free"],
    .de: ["gratis", "kostenlos"],
    .fr: ["gratuit"],
    .it: ["gratuit"],
    .pl: ["bezpłat", "darmow"],
  ]

  /// How each language says a pool is shut. The same stems `DayStateTests` uses, for the same
  /// reason: this is the invariant the whole freshness vocabulary exists to protect.
  static let shutWords: [Language: [String]] = [
    .en: ["closed", "shut"],
    .de: ["geschlossen"],
    .fr: ["ferm"],
    .it: ["chius"],
    .pl: ["zamkni", "nieczynn"],
  ]

  /// The ONE sentence on this sheet that is allowed to contain a shut-word: the `no_source`
  /// caveat, whose whole job is to say that unknown hours are not a closure. Folded.
  static let notTheSameAsClosed: [Language: String] = [
    .en: "not the same as being closed",
    .de: "nicht dasselbe wie geschlossen",
    .fr: "pas la meme chose que fermee",
    .it: "non e la stessa cosa che essere chiusa",
    .pl: "to nie to samo co zamkniety",
  ]

  /// Words that would turn a standing fact about a pool into a claim about one moment.
  static let temporalWords: [Language: [String]] = [
    .en: ["today", "tonight", "right now", " now", "tomorrow", "this week"],
    .de: ["heute", "jetzt", "morgen abend", "diese woche"],
    .fr: ["aujourd", "maintenant", "ce soir", "cette semaine"],
    .it: ["oggi", "adesso", "stasera", "questa settimana"],
    .pl: ["dzisiaj", "dzis", "teraz", "w tym tygodniu"],
  ]

  static func folded(_ text: String) -> String {
    text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
  }

  static func detail(
    admission: Admission = .unknown,
    basins: [BasinDetail] = [],
    lockers: [LockerDetail] = [],
    rentals: [RentalDetail] = [],
    features: [FeatureDetail] = [],
    season: OperatingSeason? = nil,
    lastAdmission: Int? = nil,
    freshness: String = "scraped",
    panels: [LanePanel] = [],
    poiid: String? = nil,
    provenance: Provenance = Provenance(
      source: "stadt-zuerich.ch", curated: false, validAsOf: "2026-08-24")
  ) -> FacilityDetail {
    FacilityDetail(
      poolID: "p", name: "Hallenbad Test", kind: "indoor", address: "Teststrasse 1",
      description: nil, phone: nil, url: nil, freshness: freshness, admission: admission,
      basins: basins, lockers: lockers, rentals: rentals, features: features,
      operatingSeason: season, lastAdmissionBeforeSeconds: lastAdmission,
      provenance: provenance,
      baditickerPOIID: poiid,
      lanePanels: panels)
  }

  static func rows(_ detail: FacilityDetail) -> [DetailRow] {
    detailSections(detail, on: day, for: Person(age: 30), in: en).flatMap(\.rows)
  }

  /// A row's label/value/caveat as the reader sees it. The rows carry `Wording`, so every
  /// assertion about what a row SAYS has to go through a renderer.
  static func said(_ wording: Wording?) -> String? {
    wording.map { en.string($0) }
  }

  @Test("an unstated admission is never rendered as free — IN ANY OF THE FIVE LANGUAGES")
  func unknownAdmissionIsNotFree() {
    // Five languages, because this is a rule and not a sentence: "Nicht angegeben" and "Gratis"
    // are one careless catalog edit apart, and the harm — somebody at a turnstile with no money
    // — is the same whichever language they read it in.
    for (language, localized) in CatalogFixture.all {
      let free = Self.freeWords[language] ?? []
      #expect(!free.isEmpty, "no free-word list for \(language)")
      let unknown = Self.folded(localized(admissionLabel(.unknown)))
      for word in free {
        #expect(
          !unknown.contains(word), "\(language) renders an unstated admission as \"\(unknown)\"")
      }
      // ...and the positive control: a genuinely free pool DOES say so, so the loop above
      // cannot be passing because no language has a word for free.
      let gratis = Self.folded(localized(admissionLabel(.free)))
      #expect(free.contains { gratis.contains($0) }, "\(language) does not say free: \"\(gratis)\"")
    }
    #expect(Self.en(admissionLabel(.unknown)) == "Not published — check with the pool")
    #expect(Self.en(admissionLabel(.free)) == "Free")
  }

  @Test("an unstated rental price is never rendered as free either — in all five languages")
  func unstatedRentalIsNotFree() {
    // The wire keeps the fee union CLOSED for exactly this reason: a stated-gratis rental and
    // an unstated one are different facts.
    let unstated = RentalDetail(
      ordinal: 0, kind: "towel", fee: "unstated", feeCHF: nil, depositCHF: nil, period: nil,
      raw: nil)
    let gratis = RentalDetail(
      ordinal: 1, kind: "towel", fee: "gratis", feeCHF: nil, depositCHF: nil, period: nil,
      raw: nil)
    for (language, localized) in CatalogFixture.all {
      let free = Self.freeWords[language] ?? []
      let said = Self.folded(localized(rentalFeeLabel(unstated, Format(AppLocale(language)))))
      for word in free {
        #expect(!said.contains(word), "\(language) prices an unstated rental as \"\(said)\"")
      }
      let stated = Self.folded(localized(rentalFeeLabel(gratis, Format(AppLocale(language)))))
      #expect(free.contains { stated.contains($0) }, "\(language) lost the gratis: \"\(stated)\"")
    }
    #expect(Self.en(rentalFeeLabel(unstated, Self.format)) == "Price not published")
    #expect(Self.en(rentalFeeLabel(gratis, Self.format)) == "Free")
  }

  @Test("`no_source` is never worded as closed — the invariant, one layer up, in five languages")
  func noSourceIsNotClosed() {
    // The catalog is now the easiest place to break this: a translator handed "No timetable to
    // read" out of context can reasonably reach for "Geschlossen", and no English-only check
    // could ever see it. The ONE licensed exception is the `no_source` caveat, whose sentence
    // is precisely "that is not the same as being closed".
    for (language, localized) in CatalogFixture.all {
      let shut = Self.shutWords[language] ?? []
      #expect(!shut.isEmpty, "no shut-word list for \(language)")
      let exemption = Self.notTheSameAsClosed[language] ?? ""
      #expect(!exemption.isEmpty, "no exemption phrase for \(language)")
      for freshness in ["scraped", "awaiting_scrape", "no_source", "something_new"] {
        let caveat = freshnessCaveat(freshness).map { localized($0) } ?? ""
        let said = Self.folded(localized(freshnessLabel(freshness)) + " " + caveat)
        for word in shut {
          #expect(!said.contains(word) || said.contains(exemption), "\(language)/\(freshness)")
        }
      }
      // The exception is not merely tolerated, it is REQUIRED: a `no_source` pool whose caveat
      // stopped saying this would be a pool the reader is free to read as shut.
      let noSource = Self.folded(localized(freshnessCaveat("no_source") ?? Message("")))
      #expect(noSource.contains(exemption), "\(language) dropped the not-closed sentence")
    }
    #expect(Self.en(freshnessLabel("no_source")) == "No timetable to read")
    #expect(freshnessCaveat("scraped") == nil)
  }

  @Test("a season is only stated day-precise when the page said days")
  func seasonPrecisionIsRespected() {
    let months = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "month",
      weather: "any")
    #expect(Self.en(seasonLabel(months, Self.format)) == "May to September")
    let days = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: 1, endDay: 15, precision: "day", weather: "any")
    #expect(Self.en(seasonLabel(days, Self.format)) == "1 May to 15 September")
    // A DAY-precision claim with no days is a contradiction in the store, and the honest
    // rendering is the weaker one — never an invented day.
    let broken = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "day", weather: "any")
    #expect(Self.en(seasonLabel(broken, Self.format)) == "May to September")
    // In every language the weaker rendering stays weaker: it names two months and no day. The
    // month NAMES come from the formatter, so this also pins that a `pl` reader gets Polish
    // months rather than English ones leaking through the message.
    for (language, localized) in CatalogFixture.all {
      let format = Format(AppLocale(language))
      let said = localized(seasonLabel(broken, format))
      #expect(said.contains(format.monthName(5)), "\(language): \"\(said)\" lost May")
      #expect(said.contains(format.monthName(9)), "\(language): \"\(said)\" lost September")
      #expect(said == localized(seasonLabel(months, format)), "\(language) invented a day")
    }
  }

  @Test("a fair-weather season carries its caveat")
  func fairWeatherSeasonSaysSo() {
    let season = OperatingSeason(
      startMonth: 5, endMonth: 9, startDay: nil, endDay: nil, precision: "month",
      weather: fairOnlyWeather)
    let row = Self.rows(Self.detail(season: season)).first { $0.id == "season" }
    #expect(Self.said(row?.caveat)?.contains("fair weather") == true)
    // The caveat exists in all five, rather than falling back to its own key on the four
    // languages nobody proof-read.
    for (language, localized) in CatalogFixture.all {
      let said = row?.caveat.map { localized($0) } ?? ""
      #expect(!said.isEmpty && said != "season.fairWeatherCaveat", "\(language)")
    }
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
    #expect(
      Self.said(rows.first { $0.id == "basin-b1-size" }?.caveat)?.contains("approximate")
        == true)
    #expect(rows.first { $0.id == "basin-b2-size" }?.caveat == nil)
    // A nominal temperature is a STATEMENT, a measured one is a reading; the two are not
    // rendered with the same confidence.
    #expect(
      Self.said(rows.first { $0.id == "basin-b1-temp" }?.caveat)?.contains("not a reading")
        == true)
    #expect(rows.first { $0.id == "basin-b2-temp" }?.caveat == nil)
    #expect(rows.contains { $0.id == "basin-b2-plan" })
    // The basin's NAME is the pool's own word for it and is never translated — the one row
    // label on this sheet that must stay `verbatim`.
    #expect(rows.first { $0.id == "basin-b2" }?.label == Wording.verbatim("Lehrbecken"))
  }

  @Test("a feature with no hours is unscheduled, not closed")
  func featureWithoutHoursIsNotClosed() {
    #expect(
      Self.en(featureHours(FeatureDay(windows: [], closedReason: nil), Self.en))
        == "Hours not listed for this date")
    // A stated reason is RENDERED into the sentence, not flattened into a bare "closed" and
    // not left as the clause's KEY. Asserted as the whole sentence, because "contains the word
    // season" also passes on "Closed — closureClause.out_of_season", which is what this used
    // to say before the nesting was fixed.
    #expect(
      Self.en(featureHours(FeatureDay(windows: [], closedReason: "out_of_season"), Self.en))
        == "Closed — outside its season")
    #expect(Self.en(closedReasonClause("out_of_season")) == "outside its season")
    #expect(
      Self.en(closedReasonClause("no_sessions")) == "no hours published for this date")
    // In every language, an unscheduled feature is not a shut one. This is the same invariant
    // as `no_source`, one surface over, and it has no exemption here at all.
    for (language, localized) in CatalogFixture.all {
      let said = Self.folded(
        localized(featureHours(FeatureDay(windows: [], closedReason: nil), localized)))
      for word in Self.shutWords[language] ?? [] {
        #expect(!said.contains(word), "\(language) reads unscheduled hours as \"\(said)\"")
      }
    }
    let open = FeatureDay(
      windows: [
        TimeWindow(start: TimeOfDay(hour: 9, minute: 0), end: TimeOfDay(hour: 17, minute: 0))
      ], closedReason: nil)
    // A list of times is a list of VALUES: the same characters in every language.
    #expect(Self.en(featureHours(open, Self.en)) == "09:00–17:00")
    #expect(featureHours(open, Self.en) == .verbatim("09:00–17:00"))
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
    // The feature's own name and the pool's own note are the SOURCE's words: `verbatim`, so no
    // language can translate a proper noun or a German notice.
    #expect(
      rows.first { $0.id == "feature-sauna" }?.label == Wording.verbatim("Saunalandschaft"))
    #expect(
      rows.first { $0.id == "feature-sauna" }?.caveat
        == Wording.verbatim("Textilfrei am Dienstag"))
    // The currency is formatted, so the space between symbol and amount is the LOCALE's
    // (en-GB puts a non-breaking one there) and a literal with an ASCII space would fail for a
    // reason that has nothing to do with the sheet. The claim here is that the row shows this
    // amount as money; `FormatTests` is where the separator itself is pinned.
    #expect(
      Self.said(rows.first { $0.id == "feature-sauna-fee" }?.value)
        == Self.en.format.money(chf: 9))
    #expect(Self.said(rows.first { $0.id == "feature-sauna-temp" }?.value) == "90°C")
    #expect(Self.said(rows.first { $0.id == "feature-sauna-hours" }?.value) == "10:00–21:00")
    // The NEXT day is closed for a stated reason, and that reason is rendered rather than
    // flattened into a bare "closed".
    let tomorrow = detailSections(
      Self.detail(features: [feature]), on: "2026-08-25", for: Person(), in: Self.en
    ).flatMap(\.rows)
    #expect(
      Self.said(tomorrow.first { $0.id == "feature-sauna-hours" }?.value)?.contains("season")
        == true)
    // A date the feature says nothing about gets no hours row at all — never an invented one.
    let far = detailSections(
      Self.detail(features: [feature]), on: "2027-01-01", for: Person(), in: Self.en
    ).flatMap(\.rows)
    #expect(!far.contains { $0.id == "feature-sauna-hours" })
    // A feature with no name falls back to its KIND, so a row is never blank — in any language.
    let unnamed = try #require(
      FeatureDetail.decode(key: "rest", json: #"{"kind":"gastronomy","name":null}"#))
    let unnamedRow = Self.rows(Self.detail(features: [unnamed])).first { $0.id == "feature-rest" }
    #expect(Self.said(unnamedRow?.label) == "Restaurant or kiosk")
    for (language, localized) in CatalogFixture.all {
      let label = unnamedRow.map { localized($0.label) } ?? ""
      #expect(!label.isEmpty && label != "featureKind.gastronomy", "\(language) has no fallback")
    }
  }

  @Test("an empty section is omitted, never shown empty")
  func emptySectionsAreOmitted() {
    // An empty "Lockers" heading reads as "this pool has no lockers", which is a claim the
    // data does not make.
    let sections = detailSections(
      Self.detail(), on: Self.day, for: Person(), in: Self.en)
    #expect(!sections.contains { $0.id == "lockers" })
    #expect(!sections.contains { $0.id == "features" })
    #expect(!sections.contains { $0.id == "season" })
    // ...and the sections that always have something are always there.
    #expect(sections.contains { $0.id == "where" })
    #expect(sections.contains { $0.id == "source" })
    // Every heading the sheet can show is translated in all five: a section whose title fell
    // back to its key would read as a design choice rather than as a missing string.
    for (language, localized) in CatalogFixture.all {
      for section in sections {
        let title = localized(section.title)
        #expect(title != section.title.key, "\(language) has no title for \(section.title.key)")
      }
    }
  }

  @Test("the person's own price bracket is stated beside the table")
  func personalBracketIsShown() {
    let prices = PriceDoc(
      entries: [
        PriceEntry(category: .child, amountCHF: 4, display: "Kinder CHF 4.00", minAge: 6),
        PriceEntry(category: .adult, amountCHF: 8, display: "Erwachsene CHF 8.00", minAge: 20),
      ], validAsOf: "2026-07-18", sourceURL: "https://example.invalid/tarife")
    let rows = Self.rows(Self.detail(admission: .tariff(prices)))
    // The pool's OWN price line, quoted rather than rebuilt — so it stays `verbatim` in every
    // language, which is the whole reason a dated tariff is not re-formatted.
    #expect(
      rows.first { $0.id == "your-price" }?.value == Wording.verbatim("Erwachsene CHF 8.00"))
    #expect(
      Self.said(rows.first { $0.id == "price-valid" }?.caveat)?.contains("can change")
        == true)
    // Each published band states the bound it was printed under, so a swimmer can see WHY
    // theirs was chosen.
    #expect(Self.said(rows.first { $0.id == "price-0" }?.caveat)?.contains("6") == true)
    // ...and the bound survives translation: it is a formatted NUMBER interpolated into the
    // caveat, so a catalog entry that dropped the placeholder would silently lose the age.
    for (language, localized) in CatalogFixture.all {
      let said = rows.first { $0.id == "price-0" }?.caveat.map { localized($0) } ?? ""
      #expect(said.contains("6"), "\(language) dropped the minimum age: \"\(said)\"")
    }
  }

  @Test("last admission is stated in minutes, from the store's seconds")
  func lastAdmissionIsRendered() {
    let row = Self.rows(Self.detail(lastAdmission: 1800)).first { $0.id == "last-admission" }
    #expect(Self.said(row?.value) == "30 minutes before closing")
    // The DURATION comes from `Duration`'s own units style rather than from a plural entry, so
    // each language spells it itself ("30 Minuten", "30 minut") — but every one of them must
    // still carry the NUMBER, which is the only part of this row a swimmer can act on. The rows
    // are rebuilt per language, because a row formatted in English and rendered in Polish would
    // prove nothing about what a Polish reader sees.
    for (language, localized) in CatalogFixture.all {
      let localRow = detailSections(
        Self.detail(lastAdmission: 1800), on: Self.day, for: Person(age: 30),
        in: localized
      ).flatMap(\.rows).first { $0.id == "last-admission" }
      let said = localRow.map { localized($0.value) } ?? ""
      #expect(said.contains("30"), "\(language) lost the 30 minutes: \"\(said)\"")
    }
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
    #expect(Self.said(rows.first { $0.id == "panel-b" }?.caveat)?.contains("incomplete") == true)
    #expect(rows.contains { $0.id == "panel-b-best" })
    // In all five: a partial plan admits it. A caveat that fell back to its key still reads as
    // a caveat to nobody.
    for (language, localized) in CatalogFixture.all {
      let said = rows.first { $0.id == "panel-b" }?.caveat.map { localized($0) } ?? ""
      #expect(!said.isEmpty && said != "lane.incompleteCaveat", "\(language) has no caveat")
    }
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
    //
    // Five languages, and for a sharper reason than most of the loops here: the English was
    // written with this rule in mind and the translations were not written by whoever wrote the
    // rule. "Heute geschlossen" is the natural German for a closure and is exactly wrong here.
    for (language, localized) in CatalogFixture.all {
      let temporal = Self.temporalWords[language] ?? []
      #expect(!temporal.isEmpty, "no temporal-word list for \(language)")
      let format = Format(AppLocale(language))
      var said: [Wording] = [
        .message(admissionLabel(.unknown)), .message(admissionLabel(.free)),
        .message(admissionLabel(.tariff(PriceDoc(entries: [])))),
        .message(
          seasonLabel(
            OperatingSeason(
              startMonth: 1, endMonth: 12, startDay: nil, endDay: nil, precision: "month",
              weather: "any"), format)),
        featureHours(FeatureDay(windows: [], closedReason: nil), Self.en),
        featureHours(FeatureDay(windows: [], closedReason: "out_of_season"), Self.en),
      ]
      for freshness in ["scraped", "awaiting_scrape", "no_source", "zzz"] {
        said.append(.message(freshnessLabel(freshness)))
        said += freshnessCaveat(freshness).map { [Wording.message($0)] } ?? []
      }
      for kind in ["swimmer", "paddling", "zzz"] { said.append(.message(basinKindLabel(kind))) }
      for kind in ["sauna", "gastronomy", "zzz"] { said.append(.message(featureKindLabel(kind))) }
      for kind in ["towel", "zzz"] { said.append(.message(rentalKindLabel(kind))) }
      for kind in ["wardrobe", "zzz"] { said.append(.message(lockerCategoryLabel(kind))) }
      for sentence in said {
        let lowered = Self.folded(localized(sentence))
        for word in temporal {
          #expect(!lowered.contains(word), "\(language): \"\(lowered)\" claims \"\(word)\"")
        }
      }
    }
  }

  @Test("an unrecognised code is shown as itself, never guessed at")
  func unrecognisedCodesAreShownAsThemselves() {
    // A store built by a newer export can carry a kind, a category or a freshness this binary
    // has never seen. Every fallback here degrades to the raw token or to an explicit "check
    // with the pool" — none of them invents a category.
    #expect(Self.en(basinKindLabel("wave_pool")) == "Wave Pool")
    #expect(Self.en(featureKindLabel("ice_rink")) == "Ice Rink")
    #expect(Self.en(freshnessLabel("brand_new")).contains("brand_new"))
    // The raw token is DATA, so it must survive every catalog: an entry that dropped its
    // placeholder would leave the reader looking at a blank where a token should be.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(basinKindLabel("wave_pool")).contains("Wave Pool"), "\(language)")
      #expect(localized(featureKindLabel("ice_rink")).contains("Ice Rink"), "\(language)")
      #expect(localized(rentalKindLabel("jet_ski")).contains("Jet Ski"), "\(language)")
      #expect(localized(lockerCategoryLabel("safe_box")).contains("Safe Box"), "\(language)")
      #expect(localized(freshnessLabel("brand_new")).contains("brand_new"), "\(language)")
    }
    // A closure reason this binary does not classify rides through as ITSELF, in every
    // language — the same rule as the four labels above, and the one the sheet most needs:
    // rendering "Closed — " with an empty reason would be a bare closure with nothing behind
    // the claim, which is precisely what the four-state vocabulary exists to forbid.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(closedReasonClause("mystery")).contains("mystery"), "\(language)")
      let hours = featureHours(
        FeatureDay(windows: [], closedReason: "mystery"), localized)
      #expect(localized(hours).contains("mystery"), "\(language): \(localized(hours))")
    }
  }

  // MARK: - No machine date reaches a reader

  /// `yyyy-MM-dd` — the shape every date the exporter writes has, and the shape no reader
  /// should ever see. Python's `date.isoformat()` produces it for `meta.gold_valid_as_of`,
  /// `meta.horizon_end`, `prices.valid_as_of`, `provenance.valid_as_of` and every `day` key.
  /// A function rather than a stored `Regex`: `Regex` is not `Sendable`, so a `static let`
  /// would be shared mutable state across the concurrent test suites.
  static func looksLikeAStoreDate(_ text: String) -> Bool {
    text.contains(/\b\d{4}-\d{2}-\d{2}\b/)
  }

  @Test("no rendered sheet row shows a raw store date, on any pool, in any language")
  func everyStoreDateIsFormatted() async throws {
    // WRITTEN AS A SWEEP, NOT AS A LIST, and that is the point. Two review rounds each found
    // more raw dates than the one before — three on the today screen, then two more here —
    // because each fix was a list of the sites somebody had noticed. This asks the question
    // itself: build every section for every pool in the committed store and assert that
    // nothing a reader sees still looks like a machine date. A row added next year is covered
    // without anyone remembering to add it.
    //
    // All five languages, because "formatted" means formatted FOR THE READER: a `storeDate`
    // wired through an English-only path would pass an en-only sweep and still show
    // `2026-08-24` to everyone else.
    let store = try Store.bundled()
    let metadata = try await store.metadata()
    let day = metadata.horizonStart
    var checked = 0
    var provenanceSections = 0
    for (language, localized) in CatalogFixture.all {
      for pool in try await store.pools() {
        guard let detail = try await store.facility(poolID: pool.id, on: day) else { continue }
        for section in detailSections(detail, on: day, for: Person(age: 30), in: localized) {
          if section.id == "source" { provenanceSections += 1 }
          for row in section.rows {
            for wording in [row.label, row.value, row.caveat].compactMap({ $0 }) {
              let said = localized(wording)
              checked += 1
              // A URL legitimately contains a date-like path segment; it is a machine string a
              // reader is meant to see as one, and the sheet renders it as a link.
              guard !said.hasPrefix("http") else { continue }
              if Self.looksLikeAStoreDate(said) {
                Issue.record("\(language)/\(pool.id)/\(row.id) shows a raw date: \"\(said)\"")
              }
            }
          }
        }
      }
    }
    #expect(checked > 2000, "the sweep read \(checked) strings — it is scanning nothing")
    #expect(provenanceSections > 0, "no provenance section anywhere — the dated rows were missed")
  }

  @Test("the two dated sheet rows really are rendered, and really are formatted")
  func datedRowsAreFormattedNotDropped() {
    // The sweep above is also satisfied if the rows VANISH, which is the other way to pass it
    // and the wrong one. This pins the positive direction on both — in Polish, where a
    // formatted date is unmistakable.
    let polish = CatalogFixture.localized(.pl)
    let detail = Self.detail(
      admission: .tariff(
        PriceDoc(
          entries: [PriceEntry(category: .adult, amountCHF: 8, display: "CHF 8.00", minAge: nil)],
          validAsOf: "2026-07-23", sourceURL: nil)),
      provenance: Provenance(source: "stadt-zuerich.ch", curated: false, validAsOf: "2026-07-23"))
    let rows = detailSections(detail, on: Self.day, for: Person(age: 30), in: polish)
      .flatMap(\.rows)
    for id in ["price-valid", "valid-as-of"] {
      let said = rows.first { $0.id == id }.map { polish($0.value) } ?? ""
      #expect(said == "23 lipca 2026", "\(id) reads \"\(said)\"")
    }
  }

  @Test("an empty stamp means NO ROW, never a labelled blank")
  func anEmptyStampIsOmitted() {
    // The exporter writes `... or ""` for an absent stamp. A row reading "Accurate as of" with
    // nothing after it answers "how old is this?" with silence, which is the invisible
    // degradation every other caveat on this sheet exists to avoid. `Format.storeDate("")`
    // still returns "" — it is a formatter, not a policy — and the POLICY lives at the call
    // sites, which is where a test can drive it.
    let detail = Self.detail(
      admission: .tariff(
        PriceDoc(
          entries: [PriceEntry(category: .adult, amountCHF: 8, display: "CHF 8.00", minAge: nil)],
          validAsOf: "", sourceURL: nil)),
      provenance: Provenance(source: "stadt-zuerich.ch", curated: false, validAsOf: ""))
    let rows = detailSections(detail, on: Self.day, for: Person(age: 30), in: Self.en)
      .flatMap(\.rows)
    #expect(!rows.contains { $0.id == "price-valid" })
    #expect(!rows.contains { $0.id == "valid-as-of" })
    // ...and the rows that do not depend on a stamp are still there, so this cannot pass
    // because the whole sheet collapsed.
    #expect(rows.contains { $0.id == "curated" })
    #expect(rows.contains { $0.id == "source" })
  }
}
