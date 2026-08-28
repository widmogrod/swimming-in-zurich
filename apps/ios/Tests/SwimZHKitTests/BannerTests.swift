// S3a acceptance 3: BOTH `day_warning` codes and `day_notice` rows surface in the UI.
//
// The web renders neither (measured: `AnswerOut.warnings` / `notices` are typed in `api.ts` and
// never read), so this is the phone doing something the board does not. Both are honesty:
// a warning qualifies how certain our answer is, a notice is the pool's own announcement in
// the pool's own words.
//
// The dates are DISCOVERED by walking the store's horizon, never hardcoded. The committed
// store's horizon moves with every regeneration, and a pinned "2026-12-25" would turn a data
// refresh into a red test about nothing.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Warning and notice banners")
struct BannerTests {
  /// The English renderer, for the assertions that are about a SENTENCE. The two rules that
  /// must hold whatever the reader's language — a warning code always has a sentence, and a
  /// pool's own notice is passed through UNTRANSLATED — loop over all five instead.
  static let en = CatalogFixture.english

  /// One day of the horizon that carries a warning with `code`, and its answer.
  static func firstDay(matching predicate: (Answer) -> Bool) async throws -> Answer? {
    let store = try Store.bundled()
    let meta = try await store.metadata()
    for day in ZurichClock.days(from: meta.horizonStart, through: meta.horizonEnd) {
      let answer = try await store.answer(
        onDay: day, at: TimeOfDay(hour: 12, minute: 0), for: Person())
      if predicate(answer) { return answer }
    }
    return nil
  }

  @Test(
    "both warning codes the export emits produce a banner",
    arguments: [
      DayWarning.calendarCoverage, DayWarning.holidayHoursUnverified,
    ])
  func warningCodesProduceBanners(code: String) async throws {
    let answer = try #require(
      await Self.firstDay { $0.warnings.contains { $0.code == code } },
      "no day in the horizon carries \(code) — the store or the export changed"
    )
    let banner = try #require(
      banners(for: answer, format: Self.en.format).first { $0.code == code })
    #expect(banner.kind == .warning)
    #expect(!Self.en(banner.title).isEmpty)
    // The sentence, not the bare code: a banner that showed `calendar_coverage` to a swimmer
    // would be a leaked identifier. S4 made that a catalog lookup keyed off exactly this
    // `code`, so the check runs in all five languages — a code the converter never wrote a
    // sentence for renders as ITSELF, which is the leaked identifier again, in four languages
    // where no English assertion could see it.
    for (language, localized) in CatalogFixture.all {
      let title = localized(banner.title)
      let text = localized(banner.text)
      #expect(!title.isEmpty, "\(language)")
      #expect(text != code, "\(language) has no sentence for \(code)")
      #expect(text.count > code.count, "\(language): \(text)")
    }
    #expect(banner.poolName == nil, "a warning is day-level, not about one pool")
  }

  @Test("a pool's own notice surfaces verbatim, under the pool's name")
  func noticesProduceBanners() async throws {
    let answer = try #require(
      await Self.firstDay { !$0.notices.isEmpty },
      "no day in the horizon carries a notice — the store or the export changed"
    )
    let notice = try #require(answer.notices.first)
    let names = [notice.poolID: "Hallenbad Oerlikon"]
    let banner = try #require(
      banners(for: answer, poolNames: names, format: Self.en.format).first { $0.kind == .notice })
    // Verbatim, and untranslated: the pool wrote it, in its own language. Paraphrasing a
    // closure announcement is how a client invents a fact — so this is asserted in EVERY
    // language, which is the only way the claim "untranslated" can actually be checked.
    // A pool's NAME is a proper noun and is untranslated for the same reason.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(banner.text) == notice.text, "\(language) altered the pool's own words")
      #expect(localized(banner.title) == "Hallenbad Oerlikon", "\(language)")
    }
    #expect(banner.poolName == "Hallenbad Oerlikon")
  }

  @Test("a notice whose pool name is unknown still shows — the text is the point")
  func noticeSurvivesAMissingName() async throws {
    let answer = try #require(await Self.firstDay { !$0.notices.isEmpty })
    let banner = try #require(
      banners(for: answer, format: Self.en.format).first { $0.kind == .notice })
    #expect(Self.en(banner.text) == answer.notices[0].text)
    #expect(banner.poolName == nil)
    #expect(Self.en(banner.title) == answer.notices[0].poolID)
  }

  @Test("warnings lead, notices follow, and every banner id is unique")
  func orderAndIdentity() {
    let answer = Answer(
      day: "2026-08-23",
      options: [],
      statuses: [],
      notices: [
        DayNotice(poolID: "b", text: "Revision"),
        DayNotice(poolID: "a", text: "Sommerpause"),
      ],
      warnings: [
        DayWarning(code: DayWarning.calendarCoverage, params: ["year": "2027"]),
        DayWarning(code: DayWarning.holidayHoursUnverified, params: ["date": "x", "pools": "y"]),
      ]
    )
    let built = banners(for: answer, format: Self.en.format)
    #expect(built.map(\.kind) == [.warning, .warning, .notice, .notice])
    #expect(Set(built.map(\.id)).count == built.count)
  }

  @Test("an unrecognised warning code still banners, without fabricating a sentence")
  func unknownCodeIsHonest() throws {
    // S5 downloads stores a NEWER export built, so a code this binary has never seen is a real
    // state. Rendering the holiday sentence for it would say " is a public holiday … : " —
    // a claim about pools it never named.
    let answer = Answer(
      day: "2026-08-23", options: [], statuses: [], notices: [],
      warnings: [DayWarning(code: "solar_flare", params: [:])]
    )
    let banner = try #require(banners(for: answer, format: Self.en.format).first)
    #expect(Self.en(banner.title) == "Please note")
    // In every language: the code rides through the passthrough key unchanged, and NO language
    // borrows the holiday sentence's claim about pools it never named. `warning.unknown` is
    // "%@" in all five today, and a translator who "improved" it into prose would be inventing
    // exactly the fact this arm exists to refuse.
    for (language, localized) in CatalogFixture.all {
      #expect(localized(banner.text) == "solar_flare", "\(language)")
      #expect(!localized(banner.title).isEmpty, "\(language)")
    }
  }
}
