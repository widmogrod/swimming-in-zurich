// Format.swift — every date, number, measurement and price the app renders.
//
// This file is the iOS half of the web's `datefmt.ts`, and it exists for the same reason: a
// formatted value is not a translatable message. There is no catalog entry that can make
// "8.00" read as "8,00" in French, and no translator should be asked to; `Intl` on the web and
// `FormatStyle` here already know. So the catalog carries the WORDS and this file carries the
// VALUES, and the two meet only where a message interpolates one.
//
// THE REGIONAL LOCALES ARE NOT THE LANGUAGES. `AppLocale` maps en→en-GB, de→de-CH, fr→fr-CH,
// it→it-CH, pl→pl, exactly as `datefmt.ts` pins them. Bare `en` means en-US and would flip
// every date to month-first for a Zürich audience.
//
// Facts about these locales, all pinned by test rather than assumed — Apple ships its own ICU
// snapshot, so parity with the web's CLDR is a claim to be checked, not a given:
//   * de-CH and it-CH use a DOT decimal separator, unlike de-DE and it-IT.
//   * fr-CH uses a DOT ON THIS PLATFORM and a COMMA on node's. The web pins the comma
//     (`datefmt.test.ts:85-93`); measured here, Foundation formats 2.5 in fr-CH as "2.5". The
//     two clients therefore disagree for a French reader, neither is wrong, and checking rather
//     than assuming is exactly what caught it. `FormatTests.swissDecimalSeparators` records the
//     measurement, `LocalizationDeviceTests.separatorsOnDevice` re-checks it in the simulator,
//     and CLAUDE.md's i18n section names both sides.
//   * pl is the one locale here that genuinely uses a comma.
//   * the current-CLDR Swiss GROUP separator is an ASCII apostrophe (U+0027), not U+2019.
//
// THE RULE THIS FILE ENFORCES BY BEING THE ONLY ONE: never re-parse a formatted date.
// `datefmt.ts` learned this the hard way — `formatLabel(...).split(' ')` assumed three
// space-separated tokens and produced silent nonsense in the locales that use none. The port
// of that rule is `dayParts` below: format `.attributed` and read the `DateFieldAttribute`
// runs, which is the platform TELLING you which characters are the weekday. A grep in
// `SourceLintTests` bans `.split(` and `.components(separatedBy:` anywhere in this file, which
// is the decidable form of the rule: this is the one module that holds format results, so
// banning the operators here is banning the mistake.

import Foundation

/// The parts of one date, as the formatter itself labelled them.
public struct DayParts: Equatable, Sendable {
  /// The abbreviated weekday — "Mon", "Mo", "lun.", "pon.".
  public let weekday: String
  /// The day of the month, without a leading zero.
  public let dayOfMonth: String
  /// The whole date, spelled out: what VoiceOver reads.
  public let full: String
}

/// Values, formatted for one reader.
public struct Format: Equatable, Sendable {
  public let locale: AppLocale

  public init(_ locale: AppLocale) {
    self.locale = locale
  }

  private var regional: Locale { locale.formatting }

  // MARK: - Dates

  /// The parts of `date`, read off the formatter's own field runs.
  ///
  /// Two styles rather than one because the two consumers want different widths: the strip's
  /// chip wants an abbreviated weekday and a bare day number, and VoiceOver wants the date
  /// spelled out in full. Both are formatted; NEITHER is taken apart with a separator.
  ///
  /// Polish is the case that proves the method: it takes a GENITIVE month ("23 lipca", not
  /// "23 lipiec") and lower-cases its weekday and month names, so no lookup table of month
  /// names can produce it and no capitalisation rule can be applied afterwards. Only asking
  /// the formatter works.
  public func dayParts(_ date: Date) -> DayParts {
    DayParts(
      weekday: field(
        .weekday, of: date,
        in: Date.FormatStyle(date: .omitted, time: .omitted).weekday(.abbreviated)),
      dayOfMonth: field(
        .day, of: date, in: Date.FormatStyle(date: .omitted, time: .omitted).day(.defaultDigits)),
      full: date.formatted(styled(Date.FormatStyle(date: .complete, time: .omitted)))
    )
  }

  /// A date without its weekday — "23 July 2026" — for the metadata rows.
  public func date(_ date: Date) -> String {
    date.formatted(styled(Date.FormatStyle(date: .long, time: .omitted)))
  }

  /// One of the store's own date keys (`yyyy-MM-dd`), as words in the reader's language.
  ///
  /// The store writes machine dates — `meta.gold_valid_as_of`, `meta.horizon_end`,
  /// `prices.valid_as_of`, `provenance.valid_as_of`, a `day` row's key — and S4 first shipped
  /// several of them straight onto the screen inside `Text(verbatim:)`, so a Polish reader saw
  /// `2026-08-24` where the browser shows `24 sierpnia 2026`. That was a bigger app-vs-web
  /// divergence than the fr-CH separator this file's header is careful about, and nothing was
  /// checking for it. NO COUNT IS GIVEN HERE ON PURPOSE: two review rounds each found more
  /// sites, so a number in a comment is a claim that goes stale the next time a row is added.
  /// `FacilityDetailTests.everyStoreDateIsFormatted` is the check that does not go stale.
  ///
  /// This is NOT re-parsing a formatted date, which the module bans: `day` is a machine value
  /// the store wrote, never a formatter's output. `ZurichClock.instant` does the parse, in the
  /// same place `DayChip` already asks for it.
  ///
  /// An unparseable key is shown AS ITSELF rather than blanked: the store's own horizon is what
  /// produces these strings, so a malformed one means the store is wrong, and a visible date
  /// reports that where an empty row would hide it.
  ///
  /// The EMPTY key is a different case and is deliberately not handled here. `""` is the
  /// exporter saying "no stamp" (`gold_valid_as_of or ""`), and the honest answer is no row at
  /// all rather than a label with nothing after it — which is a decision about a screen, not
  /// about a formatter. Every caller guards it; `FacilityDetailTests.anEmptyStampIsOmitted`
  /// and `TodayView.stampRow` are where that is asserted.
  public func storeDate(_ day: String) -> String {
    guard let instant = ZurichClock.instant(day: day, at: TimeOfDay(hour: 12, minute: 0)) else {
      return day
    }
    return date(instant)
  }

  /// A month's name on its own — "May", "Mai", "maj".
  ///
  /// The STANDALONE symbols, not the formatting ones, because this name is not part of a date:
  /// Polish takes a genitive month inside a date ("23 lipca") and the nominative when the month
  /// stands alone ("lipiec"), and using the wrong set reads as a grammatical error to a native
  /// speaker. A month outside 1...12 cannot come from the export's `start_month`; if one ever
  /// did, its number is shown rather than a fabricated name.
  public func monthName(_ month: Int) -> String {
    let formatter = DateFormatter()
    formatter.locale = regional
    let names = formatter.standaloneMonthSymbols ?? []
    guard month >= 1, month <= names.count else { return integer(month) }
    return names[month - 1]
  }

  private func styled(_ style: Date.FormatStyle) -> Date.FormatStyle {
    // The Zurich zone, always. A formatter left on the system zone names the wrong weekday for
    // anyone reading from another continent — and every date in the store is a Zurich calendar
    // day, so rendering one in a device zone would show a day the store has no row for.
    //
    // Set as PROPERTIES, not through `.timeZone(_:)`: that modifier takes a
    // `Date.FormatStyle.Symbol.TimeZone` (which zone FIELD to print), not the zone to format in.
    var styled = style
    styled.locale = regional
    styled.timeZone = ZurichClock.timeZone
    return styled
  }

  /// The characters the formatter itself labelled as `field`.
  ///
  /// `.attributed` yields runs tagged with `DateFieldAttribute`; taking the run is the platform
  /// telling us where the weekday is. The fallback is the whole formatted string rather than an
  /// empty one: a locale that somehow tagged nothing should show a date, not a blank.
  private func field(
    _ field: AttributeScopes.FoundationAttributes.DateFieldAttribute.Field,
    of date: Date,
    in style: Date.FormatStyle
  ) -> String {
    let attributed = date.formatted(styled(style).attributed)
    for run in attributed.runs where run.dateField == field {
      return String(attributed[run.range].characters)
    }
    return String(attributed.characters)
  }

  // MARK: - Numbers and quantities

  /// A whole number, grouped for the reader — 1'234 in de-CH, 1 234 in pl.
  public func integer(_ value: Int) -> String {
    value.formatted(.number.locale(regional))
  }

  /// A number with the reader's decimal separator: 8.00 in de-CH and it-CH, 8,00 in fr-CH
  /// and pl.
  public func number(_ value: Double, fractionDigits: Int = 2) -> String {
    value.formatted(
      .number.precision(.fractionLength(fractionDigits)).locale(regional))
  }

  /// A dimension in metres. The unit comes from `Measurement`, never from the catalog — the
  /// web made the same call ("units bypass the catalog"), because `FormatStyle` gets the
  /// abbreviation, the spacing and the plural right per locale and no message can.
  /// `usage: .asProvided` is LOAD-BEARING, not boilerplate. The default converts to the
  /// locale's customary unit, and en-GB's is imperial: measured on this machine, a 12.5 m basin
  /// renders as "41 ft" and a 1 m diving platform as "3 ft". The store's number is what the
  /// pool PUBLISHED, in metres, on a Swiss page; converting it is the same class of
  /// misreporting as showing a Celsius water temperature in Fahrenheit.
  public func length(metres: Double) -> String {
    Measurement(value: metres, unit: UnitLength.meters)
      .formatted(.measurement(width: .abbreviated, usage: .asProvided).locale(regional))
  }

  /// A distance in kilometres, for the row's "how far" line.
  ///
  /// `.asProvided` again, and for a second reason on top of the first: the web renders
  /// kilometres in every locale (`Intl.NumberFormat` with `unit: 'kilometer'` does not
  /// convert), so a phone that showed miles to an English reader would disagree with the
  /// browser about the same pool.
  public func distance(kilometres: Double) -> String {
    Measurement(value: kilometres, unit: UnitLength.kilometers)
      .formatted(
        .measurement(
          width: .abbreviated, usage: .asProvided,
          numberFormatStyle: .number.precision(.fractionLength(1))
        )
        .locale(regional))
  }

  /// A water temperature. `usage: .asProvided` because the number in the store IS Celsius and
  /// converting it to Fahrenheit for an en-GB reader would misreport what the pool published.
  public func temperature(celsius: Double) -> String {
    Measurement(value: celsius, unit: UnitTemperature.celsius)
      .formatted(.measurement(width: .abbreviated, usage: .asProvided).locale(regional))
  }

  /// A price in Swiss francs. The SYMBOL'S POSITION is the locale's business — CHF 8.00 in
  /// en-GB and de-CH, 8,00 CHF in fr-CH and pl — which is exactly why this is not a message
  /// with a "{amount}" in it.
  public func money(chf: Double) -> String {
    chf.formatted(.currency(code: "CHF").locale(regional))
  }

  /// A span of minutes, spelled out — "45 minutes", "45 Minuten", "45 minut".
  ///
  /// Through `Duration`'s own units style rather than a plural catalog entry, and that is a
  /// deliberate choice with a reason: Polish's `other` category is the FRACTION form, which for
  /// a feminine noun is spelled the same as `few` ("1,5 minuty", "2 minuty"). A catalog entry
  /// would therefore have to carry two identical forms, which the web's own parity test flags
  /// as a copy-paste. `Duration` has the rules built in and needs no entry at all.
  public func minutes(_ minutes: Int) -> String {
    Duration.seconds(minutes * 60)
      .formatted(
        .units(allowed: [.hours, .minutes], width: .wide, zeroValueUnits: .hide)
          .locale(regional))
  }
}
