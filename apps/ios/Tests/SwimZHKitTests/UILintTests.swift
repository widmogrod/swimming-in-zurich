// The UI rules that are DECIDABLE FROM SOURCE and cannot be runtime tests (S3a acceptance 5
// and 6, and S4's catalog rule brought forward).
//
// Each of these is a rule about what the app target may not contain. None of them can be a
// runtime assertion, and the reason is the same every time: SwiftUI exposes no API for the
// thing in question.
//
//  * LAZINESS. There is no "how many bodies did `List` build" API. A counter inside a `body`
//    would assert a framework scheduling decision — flaky, and about an implementation detail
//    rather than about our code. The RULE, though, is decidable: a `ForEach` element that
//    resolves to a variable number of views defeats laziness (WWDC23 10160), so no `if` or
//    `switch` may appear directly inside the row `ForEach`'s element.
//  * COLOURS. A resolved `Color` cannot be interrogated for how it was built. The banned forms
//    can be named exactly, which is what makes the check decidable rather than a matter of
//    taste: `#colorLiteral`, `Color(red:`, `Color(.sRGB`, `Color(hue:`, `UIColor(red:`.
//  * GLASS. `.glassEffect()` in the content layer is a HIG violation ("Don't use Liquid Glass
//    in the content layer") and renders inconsistently, because glass cannot sample glass.
//    Nothing at runtime reports where it was applied.
//
// The colour lint CARRIES S4'S CATALOG RULE FROM THIS SLICE ON. That is deliberate: if the ban
// arrived with S4, every slice in between could land literals that S4 would then have to
// retrofit — which is how a localisation pass turns into an archaeology exercise.
//
// It lives in the PACKAGE's suite even though it polices the APP, because the app target's own
// tests need a simulator while these are text on disk: `swift test` runs them on every push,
// including on a runner with no simulator at all.
//
// AND THE LIMIT OF ALL OF IT: everything here reads SOURCE. A lint proves a modifier is present,
// never what pressing it does. `.searchToolbarBehavior(.minimize)` was present, asserted below,
// and commented in two files as putting search in the bottom bar — while the field collapsed
// into the navigation bar and opening it took that bar away. Every check here was green; a
// reader found it in one tap. `App/SwimZHUITests/BehaviourTests.swift` is the answer to that
// class of defect, and the two suites are complements: this one is decidable and instant, that
// one is the only thing that can say what the app DOES.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("App-target UI lints")
struct UILintTests {
  static func appFiles() throws -> [(name: String, text: String)] {
    try SourceLintTests.appSwiftFiles()
  }

  /// Comment-stripped text. The headers in this app explain at length WHY `Color(red:` is
  /// banned, so a lint that matched prose would fire on its own rationale — and the natural
  /// "fix" for that would be to delete the explanation.
  static func code(_ text: String) -> String { SourceLintTests.code(text) }

  @Test("the lint can see the app target it is meant to police")
  func appIsVisible() throws {
    let files = try Self.appFiles()
    #expect(files.count >= 12, "found \(files.map(\.name))")
    for expected in [
      "TodayView.swift", "DayStrip.swift", "FilterBar.swift", "PoolRowView.swift",
      "RibbonCanvas.swift", "LaneGanttView.swift", "FacilitySheet.swift",
    ] {
      #expect(files.contains { $0.name == expected }, "missing \(expected)")
    }
  }

  // MARK: - S3b acceptance 5 and 7: what a Canvas must and must not carry

  /// Every `Canvas` construction in `code`, with the modifier chain that follows it.
  ///
  /// A regex would be the obvious tool and the wrong one: `RibbonCanvas` CONTAINS "Canvas", so
  /// a naive match reports the type declaration as a canvas site and the lint passes on a file
  /// with no canvas in it at all. The scan therefore requires a word boundary before the token
  /// and a `(` or `{` after it — the two ways a `Canvas` can be built.
  ///
  /// The site runs to the end of the enclosing declaration, approximated by the next top-level
  /// `private`/`var`/`func`/`}`. Generous on purpose: a site cut too short would miss a
  /// modifier and fail a compliant file.
  static func canvasSites(in code: String) -> [String] {
    let characters = Array(code)
    let token = Array("Canvas")
    var sites: [String] = []
    var index = 0
    while index + token.count < characters.count {
      guard Array(characters[index..<(index + token.count)]) == token else {
        index += 1
        continue
      }
      let before = index == 0 ? " " : characters[index - 1]
      // `Canvas(...)` and `Canvas { ... }` are both constructions; `Canvas` followed by a space
      // and then a brace is the trailing-closure form.
      let after = characters[(index + token.count)...].first { !$0.isWhitespace }
      guard !before.isLetter, !before.isNumber, before != "_", after == "(" || after == "{" else {
        index += 1
        continue
      }
      let rest = String(characters[index...])
      let end =
        ["\n  private ", "\n  var ", "\n  func ", "\n}"]
        .compactMap { rest.range(of: $0)?.lowerBound }
        .min() ?? rest.endIndex
      sites.append(String(rest[..<end]))
      index += token.count
    }
    return sites
  }

  @Test("every Canvas in the app target carries accessibilityChildren")
  func everyCanvasIsAccessible() throws {
    // Apple states it twice: "A canvas doesn't offer interactivity or accessibility for
    // individual elements." A ribbon without `accessibilityChildren` is one opaque rectangle to
    // a screen reader, so this fails outright rather than warning.
    var canvases = 0
    for file in try Self.appFiles() {
      for site in Self.canvasSites(in: Self.code(file.text)) {
        canvases += 1
        #expect(
          site.contains(".accessibilityChildren"),
          "\(file.name): a Canvas with no accessibilityChildren — VoiceOver sees one blank rect"
        )
      }
    }
    #expect(canvases >= 2, "the lint found \(canvases) canvases — it is scanning nothing")
  }

  @Test("the canvas lint really would catch a Canvas without accessibilityChildren")
  func canvasLintIsNotVacuous() {
    let bad = """
      private var plot: some View {
        Canvas { context, size in
          context.fill(path, with: .color(.red))
        }
        .frame(height: 40)
      }
      """
    let good = """
      private var plot: some View {
        Canvas { context, size in
          context.fill(path, with: .color(.red))
        }
        .accessibilityChildren { EmptyView() }
      }
      """
    #expect(UILintTests.canvasSites(in: bad).count == 1)
    #expect(UILintTests.canvasSites(in: bad).first?.contains(".accessibilityChildren") == false)
    #expect(UILintTests.canvasSites(in: good).first?.contains(".accessibilityChildren") == true)
    // ...and the word boundary really holds: `RibbonCanvas` is a TYPE, not a canvas site.
    #expect(UILintTests.canvasSites(in: "struct RibbonCanvas: View {}").isEmpty)
  }

  @Test("`drawingGroup()` is applied to nothing")
  func noDrawingGroup() throws {
    // `Canvas` is already Metal-backed, so `drawingGroup()` adds an offscreen render pass and
    // buys nothing — it is a pessimisation dressed as a performance fix.
    for file in try Self.appFiles() {
      #expect(
        !Self.code(file.text).contains("drawingGroup("),
        "\(file.name) applies drawingGroup() — Canvas is already Metal-backed"
      )
    }
  }

  @Test("the ribbon and the cursor are TWO canvases, and only the cursor is on a timeline")
  func theTwoCanvasSplitSurvives() throws {
    // The whole canvas redraws on every invalidation, so a moving cursor inside the ribbon's
    // canvas would repaint every ribbon once a minute. The split is the CPU guard, and it is
    // structural — this is what stops a later edit from quietly merging the two.
    let canvas = try #require(try Self.appFiles().first { $0.name == "RibbonCanvas.swift" })
    let code = Self.code(canvas.text)
    #expect(Self.canvasSites(in: code).count >= 2, "the two-canvas split has collapsed")
    #expect(code.contains("TimelineView("))
    // `paused:` comes from the package's pure policy, never from a literal or an inline guess:
    // whether TimelineView self-pauses off-screen is undocumented.
    #expect(code.contains("paused: animationPaused(scenePhase:"))
    // ...and the STATIC canvas must not be inside the timeline, or the split buys nothing.
    let timeline = try #require(code.range(of: "TimelineView("))
    #expect(
      !code[..<timeline.lowerBound].contains("TimelineView("),
      "the static ribbon canvas must be built outside the TimelineView"
    )
  }

  // MARK: - S3b acceptance 8: Swift Charts, one at a time

  @Test("`Chart` appears in exactly one file, and it is not the row's day tail")
  func chartsAreBuiltOneAtATime() throws {
    // 57 live charts inside a `List` is the shape with credible reports of 100% CPU and
    // 50-150 ms hangs. The ribbons are Canvas; the Gantt is the one chart, built only for the
    // expanded row.
    let holders = try Self.appFiles()
      .filter { Self.code($0.text).contains("Chart(") }
      .map(\.name)
    #expect(holders == ["LaneGanttView.swift"], "Chart( appears in \(holders)")
    // ...and the row builds it behind its expansion flag, which `TodayModel` keeps to ONE id.
    let row = try #require(try Self.appFiles().first { $0.name == "PoolRowView.swift" })
    #expect(Self.code(row.text).contains("if isExpanded"))
    let model = try #require(try Self.appFiles().first { $0.name == "TodayModel.swift" })
    #expect(
      Self.code(model.text).contains("expandedPoolID = expandedPoolID == poolID ? nil : poolID"),
      "the expansion must be a single id — a Set would allow 57 open charts"
    )
  }

  // MARK: - The zoom transition, and the sheet's rendered identity

  @Test("the zoom transition has BOTH halves — neither works alone")
  func zoomTransitionIsComplete() throws {
    let row = try #require(try Self.appFiles().first { $0.name == "PoolRowView.swift" })
    #expect(Self.code(row.text).contains(".matchedTransitionSource(id:"))
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    #expect(Self.code(view.text).contains(".navigationTransition(.zoom(sourceID:"))
  }

  @Test("the detail sheet renders the pool's NAME, which is why its id stays omitted")
  func detailSheetRendersTheName() throws {
    // `FacilityDetailOut.facility_name` has no `DetailRow` of its own — it is the screen's own
    // heading — so this lint is its evidence, and the reason `facility_id` is deliberately NOT
    // claimed rendered (see `FieldCoverage.deliberatelyOmitted`).
    //
    // IT USED TO PIN THE NAVIGATION TITLE, and that stopped being the whole truth: the name is
    // rendered at `heroTitle` in `PoolHeader` and the bar states it only once that has scrolled
    // away, so a lint demanding an unconditional `.navigationTitle(Text(verbatim: detail.name))`
    // would now be demanding the duplication back. Both halves are checked instead — the hero
    // is where the reader meets the name, the bar is what keeps it after that — because either
    // one alone leaves a screen that can be looking at a pool without ever naming it.
    let sheet = try #require(try Self.appFiles().first { $0.name == "FacilitySheet.swift" })
    let code = Self.code(sheet.text)
    #expect(
      code.contains("showsTitle ? Text(verbatim: detail.name)"),
      "the bar never takes the name over, so a scrolled screen names no pool")
    #expect(!code.contains("Text(detail.poolID)"))

    let header = try #require(try Self.appFiles().first { $0.name == "PoolHeader.swift" })
    let hero = Self.code(header.text)
    #expect(
      hero.contains("Text(verbatim: detail.name)"), "the pool screen no longer opens on a name")
    // ...and the bar's copy is CONDITIONAL. Without this the two could quietly both be
    // unconditional again, which is the defect the pair exists to prevent rather than describe.
    #expect(
      code.contains("poolTitleShows("),
      "the bar states the name unconditionally again — that is the same word twice")
  }

  @Test("the sheet asks for a live reading, and hands it to the rule that words it")
  func detailSheetRendersTheLiveReading() throws {
    // The evidence behind `FacilityDetailOut.live_water_temp`'s move into `renderedFields`.
    // `FieldCoverageTests` proves the ROW is built from the real store; this proves the app
    // actually asks for a reading and passes it in, which is the half a kit test cannot see.
    let sheet = try #require(try Self.appFiles().first { $0.name == "FacilitySheet.swift" })
    #expect(Self.code(sheet.text).contains("live: live"), "the sheet drops the live reading")

    let loader = try #require(try Self.appFiles().first { $0.name == "PoolsBrowser.swift" })
    let code = Self.code(loader.text)
    #expect(code.contains("await live(detail?.baditickerPOIID)"), "nothing fetches a reading")
    // The age is a fact about the clock, so the sheet must re-ask while it is open and on
    // returning to the foreground. Without both, a sheet left idle keeps printing the age it
    // had when it was opened — the same understating temporal claim in a new place.
    #expect(code.contains("LiveClient.reaskInterval"), "the sheet never re-asks while open")
    #expect(code.contains("scenePhase"), "the sheet never re-asks on foreground")
    #expect(code.contains("asOf = Date()"), "the age is never restated")

    // ...and `muted` is CONSUMED. `liveWaterRow` sets it for a stale or unmeasured reading, and
    // a flag no view reads is a claim the kit makes and the app quietly drops.
    #expect(
      Self.code(sheet.text).contains("row.muted"),
      "FacilitySheet ignores DetailRow.muted — a stale reading renders like a fresh one")
    // The wording is the KIT's: a view that formatted a temperature or decided what to say
    // when there is no reading would be a rule nothing measures.
    #expect(!code.contains("°C"))
    for file in try Self.appFiles() {
      #expect(
        !Self.code(file.text).contains("LiveUnavailable."),
        "App/\(file.name) decides what an unavailable reading says — that belongs to liveWaterRow"
      )
    }
  }

  @Test("the app target contains no SWITCH mapping a state string to a sentence")
  func noStateToStringInTheApp() throws {
    // The condition S3a's deletion of `TodayView.statusLabel` created, and which S3b had to
    // keep while adding the canvas, the sheet, the browser and the legend: every sentence the
    // app shows comes from `SwimZHKit`, where a test drives it. A second path to one mapping is
    // exactly how the two drifted last time.
    //
    // NARROW, AND SAID SO. This checks exactly one shape — no arm of a switch over a raw state
    // string may RETURN a string literal — which is the shape of the deleted `statusLabel`. It
    // does not ban a switch on a string per se: `familyColor` maps a family to an ASSET and
    // `RibbonCanvas.draw` dispatches a variant to a drawing function; neither is a sentence.
    // It is NOT a general "no domain logic in the app" gate, and it did not see the real S3b
    // defect — `if panel.day.confidence != "complete" { Text("Some lanes could not…") }`, an
    // `if` rather than a `case`. `noDomainTokenComparisonsInTheApp` below is the check that
    // catches that shape.
    for file in try Self.appFiles() {
      for line in Self.code(file.text).split(separator: "\n") {
        let text = line.trimmingCharacters(in: .whitespaces)
        guard text.hasPrefix("case \"") else { continue }
        #expect(
          !text.contains("return \""),
          "\(file.name): `\(text)` maps a state to a SENTENCE — that belongs in SwimZHKit"
        )
      }
    }
  }

  /// Tokens the EXPORT writes and `SwimZHKit` interprets. Comparing one in the app target means
  /// a domain rule has a second home there, where nothing scores or drives it.
  ///
  /// Deliberately not every string the domain uses: ribbon `variant`s and access `family`
  /// names are the app layer's own dispatch keys (to a drawing function, to an asset colour),
  /// and both are named in `noStateToStringInTheApp`'s comment as legitimate. These six are
  /// the ones that decide WHAT A SWIMMER IS TOLD.
  static let domainStateTokens = [
    "complete", "partial", "scraped", "awaiting_scrape", "no_source", "out_of_season",
  ]

  @Test("the app target never compares a domain state token itself")
  func noDomainTokenComparisonsInTheApp() throws {
    // The check the switch lint could not make. `LaneGanttView` asked `confidence != "complete"`
    // and shipped its own copy of the sentence, while `FacilityDetail` in the package asked
    // `confidence == "partial"` — the same fact, two homes, OPPOSITE polarities, and for any
    // token that was neither the sheet stayed silent while the Gantt shouted. The fix is a kit
    // predicate (`LaneDay.isComplete`); this is what stops the next one being written here.
    for file in try Self.appFiles() {
      let code = Self.code(file.text)
      for token in Self.domainStateTokens {
        for form in ["== \"\(token)\"", "!= \"\(token)\""] {
          #expect(
            !code.contains(form),
            "\(file.name) tests `\(form)` — that predicate belongs in SwimZHKit"
          )
        }
      }
    }
  }

  // MARK: - S4 acceptance 2: nothing user-visible is left in English

  /// Every string literal handed to `Message(...)` in either target, with the file it came
  /// from. These ARE the catalog keys: the whole app says what it says through them.
  static func messageKeyLiterals(in files: [(name: String, text: String)]) -> [(String, String)] {
    var found: [(String, String)] = []
    for file in files {
      for match in Self.code(file.text).matches(of: /Message\(\s*"([^"]+)"/) {
        // An INTERPOLATED key is not a literal and cannot be looked up as one; it is checked by
        // its prefix in `interpolatedKeysHaveARealPrefix`. Without this filter every
        // `Message("poolKind.\(kind)")` would be reported as a missing key, and the honest
        // reading of that much noise is "turn the lint off".
        guard !match.1.contains("\\(") else { continue }
        found.append((file.name, String(match.1)))
      }
      // `Wording.key("…")` is the same thing said shorter.
      for match in Self.code(file.text).matches(of: /\.key\(\s*"([^"]+)"/) {
        guard !match.1.contains("\\(") else { continue }
        found.append((file.name, String(match.1)))
      }
      // ...and an interpolated key (`"poolKind.\(kind)"`) cannot be checked as a literal, so
      // the PREFIX is checked instead by `interpolatedKeysHaveARealPrefix` below.
    }
    return found
  }

  @Test("every message key the app and the kit name exists in the catalog")
  func everyMessageKeyResolves() throws {
    // The half of acceptance 2 that stops criterion 1 being vacuous. Key parity inside the
    // catalog is worth nothing if the code names keys that are not in it: a missing key renders
    // as ITSELF, which on screen reads as a design choice rather than as a missing string.
    let files = try Self.appFiles() + SourceLintTests.swiftFiles()
    let literals = Self.messageKeyLiterals(in: files)
    #expect(literals.count > 80, "only \(literals.count) message keys found — is the scan working?")
    for (file, key) in literals {
      #expect(Catalog.entries[key] != nil, "\(file) names \(key), which the catalog lacks")
    }
    // ...and the app target really is one of the scanned trees, so this cannot pass by reading
    // the package alone.
    #expect(literals.contains { $0.0 == "TodayView.swift" })
  }

  @Test("an interpolated key is built from a prefix the catalog actually has")
  func interpolatedKeysHaveARealPrefix() throws {
    // `Message("poolKind.\(kind)")` cannot be checked as a literal, and it is the right shape
    // for a closed vocabulary — so the PREFIX is checked instead: at least one real key must
    // begin with it, which catches a renamed family (`poolKind.` → `pool.kind.`) that would
    // otherwise render every kind as a raw key.
    let files = try Self.appFiles() + SourceLintTests.swiftFiles()
    var prefixes: [(String, String)] = []
    for file in files {
      for match in Self.code(file.text).matches(of: /Message\(\s*"([A-Za-z.]+)\\\(/) {
        prefixes.append((file.name, String(match.1)))
      }
    }
    #expect(!prefixes.isEmpty, "no interpolated keys found — the scan is broken")
    for (file, prefix) in prefixes {
      #expect(
        Catalog.entries.keys.contains { $0.hasPrefix(prefix) },
        "\(file) builds keys under \(prefix), which no catalog key starts with")
    }
  }

  @Test("no bare string literal sits in a LocalizedStringKey position")
  func noLiteralsInLocalizedStringKeyPositions() throws {
    // In SwiftUI a literal in a `LocalizedStringKey` position IS a key — which is the correct
    // idiom in general and the wrong one HERE, because SwiftUI resolves it against
    // `Bundle.main` while this app's catalog lives in the package's bundle. Such a literal
    // renders as the raw key, silently.
    //
    // So the rule is not "no literals" (that would forbid right code elsewhere); it is: any
    // literal in one of these positions must be a catalog key AND, in this app, there should be
    // none at all, because everything goes through `Text(Message)`.
    let positions = [
      "Text(\"", "Label(\"", ".navigationTitle(\"", ".accessibilityLabel(\"",
      ".accessibilityValue(\"", "Button(\"", "Section(\"", "Toggle(\"", "Picker(\"",
      "LabeledContent(\"", "ContentUnavailableView(\"", "prompt: \"",
    ]
    for file in try Self.appFiles() {
      let code = Self.code(file.text)
      for position in positions {
        // EVERY occurrence, not the first. Acceptance 2(a) says "every string literal in a
        // LocalizedStringKey position", and `range(of:)` checks one per token per file — which
        // is harmlessly equivalent today, because there are zero such literals, and stops being
        // equivalent the moment one legitimate literal is added above a wrong one.
        for range in code.ranges(of: position) {
          // If one is ever added deliberately it must at least BE a key, so the failure names
          // both facts rather than only the ban.
          let rest = code[range.upperBound...]
          let key = String(rest.prefix { $0 != "\"" })
          #expect(
            Catalog.entries[key] != nil,
            "\(file.name) has a bare literal in a LocalizedStringKey position: \(position)\(key)"
          )
        }
      }
    }
  }

  /// One allowlisted `Text(verbatim:)` site.
  struct VerbatimSite: Decodable, Hashable {
    let file: String
    let expression: String
    let reason: String
  }

  /// Every `Text(verbatim: …)` argument in the app target, paren-matched.
  ///
  /// Paren-matched rather than regex-matched because the arguments contain parentheses of their
  /// own (`localized.format.distance(kilometres: km)`), and a scan that stopped at the first
  /// `)` would report a truncated expression that no allowlist entry could match — which reads
  /// as "you forgot to allowlist it" rather than as "the lint is broken".
  static func verbatimSites(in code: String) -> [String] {
    // `(verbatim:` rather than `Text(verbatim:`, so the two `self.init(verbatim:)` calls in
    // `Localization.swift` — the ones that make every OTHER site unnecessary — are covered by
    // the same rule as the rest. A token that only matched `Text(` would have exempted exactly
    // the file most worth policing.
    let token = "(verbatim:"
    var sites: [String] = []
    var search = code.startIndex
    while let start = code.range(of: token, range: search..<code.endIndex) {
      var depth = 1
      var cursor = start.upperBound
      while cursor < code.endIndex, depth > 0 {
        if code[cursor] == "(" { depth += 1 }
        if code[cursor] == ")" { depth -= 1 }
        if depth > 0 { cursor = code.index(after: cursor) }
      }
      sites.append(
        String(code[start.upperBound..<cursor]).trimmingCharacters(in: .whitespacesAndNewlines))
      search = cursor
    }
    return sites
  }

  @Test("every `Text(verbatim:)` in the app target is allowlisted, with a reason")
  func verbatimTextIsAllowlisted() throws {
    // `Text(verbatim:)` says "this string is NOT a key". That is right for a value — a pool's
    // name, a formatted distance, a string this code localised on the line above — and wrong
    // for a sentence, and the two are indistinguishable in a diff. So every site is named in
    // `apps/ios/verbatim-allowlist.json` with the reason it is a value.
    let allowlist = RepoFixtures.root.appending(path: "apps/ios/verbatim-allowlist.json")
    struct Allowlist: Decodable { let sites: [VerbatimSite] }
    let allowed = try JSONDecoder().decode(Allowlist.self, from: Data(contentsOf: allowlist))
    #expect(allowed.sites.count >= 15, "the allowlist looks truncated")
    for site in allowed.sites {
      #expect(site.reason.count > 20, "\(site.file)/\(site.expression) has no real reason")
    }
    let permitted = Set(allowed.sites.map { "\($0.file)|\($0.expression)" })

    var seen = 0
    for file in try Self.appFiles() {
      for expression in Self.verbatimSites(in: Self.code(file.text)) {
        seen += 1
        #expect(
          permitted.contains("\(file.name)|\(expression)"),
          "\(file.name): Text(verbatim: \(expression)) is not in verbatim-allowlist.json")
      }
    }
    #expect(seen >= 15, "the scan found \(seen) verbatim sites — it is reading nothing")
    // ...and every allowlisted site still exists, so the file cannot rot into a list of
    // exemptions for code that is gone.
    var live: Set<String> = []
    for file in try Self.appFiles() {
      for expression in Self.verbatimSites(in: Self.code(file.text)) {
        live.insert("\(file.name)|\(expression)")
      }
    }
    #expect(
      permitted.subtracting(live).isEmpty,
      "stale allowlist entries: \(permitted.subtracting(live).sorted())")
  }

  @Test("the verbatim scan really matches whole arguments, parentheses included")
  func verbatimScanIsNotVacuous() {
    let sample = """
      Text(verbatim: pool.name)
      Text(verbatim: localized.format.distance(kilometres: km))
      Text("nav.allPools")
      self.init(verbatim: localized(message))
      """
    let sites = UILintTests.verbatimSites(in: sample)
    #expect(
      sites == [
        "pool.name", "localized.format.distance(kilometres: km)", "localized(message)",
      ])
  }

  /// Every string LITERAL in `code`, as its contents.
  ///
  /// A hand-written scanner rather than a regex, and the reason is a bug this lint had on its
  /// first run: `/"([^"\n]*)"/ ` happily matches the text BETWEEN two adjacent literals, so
  /// `Color("A"), systemImage: "B"` was reported as a phrase reading `"), systemImage: "`. A
  /// scanner that toggles in/out of a string cannot make that mistake. Interpolations are
  /// skipped whole (`\(…)` can contain braces and quotes of its own), and an escaped quote
  /// does not close the literal.
  static func stringLiterals(in code: String) -> [String] {
    var literals: [String] = []
    var current = ""
    var inString = false
    var index = code.startIndex
    while index < code.endIndex {
      let character = code[index]
      if inString {
        if character == "\\" {
          let next = code.index(after: index)
          if next < code.endIndex, code[next] == "(" {
            // An interpolation: skip to its matching `)` without leaving the literal.
            var depth = 0
            var cursor = next
            while cursor < code.endIndex {
              if code[cursor] == "(" { depth += 1 }
              if code[cursor] == ")" {
                depth -= 1
                if depth == 0 { break }
              }
              cursor = code.index(after: cursor)
            }
            current.append("\u{FFFC}")  // an opaque placeholder: a value, not a word
            index = cursor < code.endIndex ? code.index(after: cursor) : code.endIndex
            continue
          }
          // Any other escape: consume both characters.
          current.append(character)
          if next < code.endIndex { current.append(code[next]) }
          index = next < code.endIndex ? code.index(after: next) : code.endIndex
          continue
        }
        if character == "\"" {
          literals.append(current)
          current = ""
          inString = false
        } else if character == "\n" {
          // An unterminated literal means the scan lost sync; drop it rather than run on.
          current = ""
          inString = false
        } else {
          current.append(character)
        }
      } else if character == "\"" {
        inString = true
      }
      index = code.index(after: index)
    }
    return literals
  }

  @Test("the app target holds no user-visible sentence of its own")
  func noSentencesInTheApp() throws {
    // The broadest of the four, and the one that catches a literal nobody thought of: a string
    // literal in the app target holding two or more WORDS is prose, and prose belongs in the
    // catalog. Symbol names, asset names and keys have no spaces, so they are out of scope by
    // construction; the handful that genuinely do are named here rather than pattern-matched,
    // so adding one is a deliberate edit.
    let allowed: Set<String> = [
      "\u{FFFC} \u{FFFC}", ", ", " · ", "· \u{FFFC}",
      // `os_log` format strings. They go to the console for whoever has to fix the store or
      // debug an upload, never to a reader — which is the whole point of S4 moving the first
      // one off the error screen. The refresh pair are the reason a failed refresh needs no UI
      // at all: the operator gets the reason, the swimmer gets the app they already had.
      "store unreadable: \u{FFFC}",
      "store refresh skipped: \u{FFFC}",
      "store refreshed to \u{FFFC}",
    ]
    for file in try Self.appFiles() {
      for literal in Self.stringLiterals(in: Self.code(file.text)) {
        let words = literal.split(separator: " ").filter { $0.contains(where: \.isLetter) }
        guard words.count >= 2, !allowed.contains(literal) else { continue }
        Issue.record("\(file.name) holds a phrase: \"\(literal)\" — it belongs in the catalog")
      }
    }
  }

  @Test("the literal scanner really reads literals, and only literals")
  func literalScannerIsSound() {
    // The three shapes that broke the regex this replaced, pinned so it cannot come back.
    let sample = #"""
      Image(systemName: "heart.fill")
      Color("MarkAttend"), systemImage: "line.3.horizontal"
      Text(verbatim: "\(a) – \(b)")
      let escaped = "say \"hi\""
      """#
    let literals = UILintTests.stringLiterals(in: sample)
    #expect(literals.contains("heart.fill"))
    #expect(literals.contains("MarkAttend"))
    #expect(literals.contains("line.3.horizontal"))
    // ...and NOT the text between two literals, which is what the regex reported as a phrase.
    #expect(!literals.contains { $0.contains("systemImage") })
    // An interpolation becomes an opaque placeholder rather than leaking its expression.
    #expect(literals.contains("\u{FFFC} – \u{FFFC}"))
    #expect(literals.contains(#"say \"hi\""#))
  }

  // MARK: - Acceptance 6: colours

  /// The banned forms, named so the check is decidable. Every one of them is a channel value
  /// written into source; none of them can carry a dark-appearance variant, an accessibility
  /// contrast variant, or a `GraphicsContext.environment` resolution inside a `Canvas` — which
  /// is what S3b's ribbon needs.
  static let bannedColourTokens = [
    "#colorLiteral", "Color(red:", "Color(.sRGB", "Color(hue:", "UIColor(red:",
  ]

  @Test("no hardcoded colour literal anywhere in the app target")
  func noColourLiterals() throws {
    for file in try Self.appFiles() {
      let code = Self.code(file.text)
      for token in Self.bannedColourTokens {
        let found = "\(file.name) builds a colour from literal channels: \(token)"
        #expect(!code.contains(token), "\(found) — colours resolve from the Asset Catalog")
      }
    }
  }

  @Test("every named colour the app asks for exists in the Asset Catalog")
  func namedColoursExist() throws {
    // The other half of the same rule, and the half that actually bites: `Color("Typo")`
    // compiles, ships, and renders as an invisible default. Without this the ban above would
    // simply move the failure from a literal to a silent blank.
    let catalog = SourceLintTests.sources
      .deletingLastPathComponent()
      .deletingLastPathComponent()
      .appending(path: "App/SwimZH/Assets.xcassets")
    let sets = try FileManager.default.contentsOfDirectory(atPath: catalog.path)
      .filter { $0.hasSuffix(".colorset") }
      .map { String($0.dropLast(".colorset".count)) }
    #expect(sets.count >= 10, "the catalog looks empty: \(sets)")

    var asked: Set<String> = []
    for file in try Self.appFiles() {
      for match in Self.code(file.text).matches(of: /Color\("([A-Za-z0-9_]+)"\)/) {
        asked.insert(String(match.1))
      }
    }
    #expect(!asked.isEmpty, "no named colours found — did Theme.swift stop using the catalog?")
    #expect(
      asked.subtracting(Set(sets)).isEmpty,
      "colours asked for but absent from the catalog: \(asked.subtracting(Set(sets)).sorted())"
    )
  }

  // MARK: - The design system: one decision, one place

  /// The file that IS the design system. Every token lives there, so it is the one file the
  /// bans below cannot apply to.
  static let tokenFile = "Theme.swift"

  /// The system font names. A `.font(.caption)` at a call site is a decision about RANK taken
  /// five files away from the other four that had to agree with it — which is how "a price" and
  /// "a distance" shipped as two different sizes in the same row.
  static let bannedFontForms = [
    ".font(.caption)", ".font(.caption2)", ".font(.footnote)", ".font(.headline)",
    ".font(.subheadline", ".font(.title", ".font(.body)", ".font(.callout)",
    ".font(.largeTitle)", ".font(.system(",
  ]

  @Test("every font in the app comes from the type ramp, not from a system name")
  func fontsComeFromTheRamp() throws {
    // `.font(.rowFact)` and friends are declared in `Theme.swift`; nothing else may name a size.
    // `.font(.system(size:))` is the worst of them and had one live site: the ribbon's hour
    // labels, the only text in the app a reader with large type could not enlarge.
    for file in try Self.appFiles() where file.name != Self.tokenFile {
      let code = Self.code(file.text)
      for form in Self.bannedFontForms {
        #expect(
          !code.contains(form),
          "\(file.name) names a system font (\(form)) — ask the ramp in \(Self.tokenFile)")
      }
    }
  }

  @Test("every SF Symbol the app names is named in the icon list")
  func glyphsComeFromTheIconList() throws {
    // One glyph, one meaning. `questionmark.circle` was the tier for "we cannot tell", the mark
    // for "check with the pool" AND the menu item for the colour legend; the two lists of pools
    // showed the same "nothing matched" sentence under two different pictures. Neither is
    // visible from any one file, which is exactly why the list has to be somewhere.
    for file in try Self.appFiles() where file.name != Self.tokenFile {
      let code = Self.code(file.text)
      for form in ["systemName: \"", "systemImage: \""] {
        #expect(
          !code.contains(form),
          "\(file.name) names an SF Symbol inline — add it to `Icon` in \(Self.tokenFile)")
      }
    }
  }

  @Test("no two icons in the list are the same glyph")
  func glyphsAreDistinct() throws {
    // The `Icon` list exists so that one glyph standing for two ideas is VISIBLE — that was its
    // founding defect (`questionmark.circle` was a tier, a mark and a menu item). Keeping the
    // names in one file makes the collision visible to a reader of that file; it took a
    // screenshot to notice the next one, because `allPools` and the mode picker's `list` were
    // both `list.bullet` and ended up four inches apart in the same bottom bar.
    //
    // Two entries MAY share a glyph when they are the same idea in two states — `filter` and
    // `filterActive` differ only by `.fill`, and `favourite`/`favouriteMark` likewise — so the
    // comparison is on the base name with the state suffix removed.
    let theme = try #require(try Self.appFiles().first { $0.name == Self.tokenFile })
    var seen: [String: String] = [:]
    for match in Self.code(theme.text).matches(
      of: /static let ([A-Za-z0-9_]+) = "([a-z0-9.]+)"/)
    {
      let (name, glyph) = (String(match.1), String(match.2))
      let base = glyph.hasSuffix(".fill") ? String(glyph.dropLast(5)) : glyph
      if let owner = seen[base], !name.hasPrefix(owner), !owner.hasPrefix(name) {
        Issue.record("`\(name)` and `\(owner)` are both `\(base)` — one glyph, two meanings")
      }
      seen[base] = name
    }
    #expect(seen.count >= 10, "the icon list looks empty: \(seen)")
  }

  @Test("every corner radius comes from the scale")
  func radiiComeFromTheScale() throws {
    // 12, 3 and 2, in three files, with no rule between them. `RibbonCanvas` is exempt: its
    // radii are GEOMETRY — half the height of the band being drawn — not a style choice.
    for file in try Self.appFiles()
    where file.name != Self.tokenFile && file.name != "RibbonCanvas.swift" {
      let code = Self.code(file.text)
      for match in code.matches(of: /cornerRadius[:(] ?([0-9]+)/) {
        Issue.record("\(file.name) uses a raw corner radius (\(match.1)) — use `Design.Radius`")
      }
    }
  }

  // MARK: - One screen, one idiom

  @Test("no screen pins its search field open")
  func noScreenPinsItsSearchField() throws {
    // `.always` is not a placement, it is a pin: the field never yields a row however far you
    // scroll. `chromeYieldsToContent` has banned it on the find screen since S3b — and the
    // all-pools browser was doing it anyway, so the app searched two different ways depending
    // on which list you were looking at. The ban is app-wide now.
    for file in try Self.appFiles() {
      #expect(
        !Self.code(file.text).contains("displayMode: .always"),
        "\(file.name) pins its search field open")
    }
  }

  @Test("both lists of pools reach search and filters the same way")
  func theTwoListsShareOneIdiom() throws {
    // They push the same destination and answer the same question about the same roster. One
    // pinned its search field and hung its filter off a top-bar MENU while the other reached
    // search from the bar and opened a filter SHEET — wearing the same glyph for both.
    for name in ["TodayView.swift", "PoolsBrowser.swift"] {
      let file = try #require(try Self.appFiles().first { $0.name == name })
      let code = Self.code(file.text)
      #expect(code.contains(".searchToolbarBehavior(.minimize)"), "\(name): search is resident")
      #expect(
        code.contains("ToolbarItem(placement: .bottomBar)"),
        "\(name): the filter control is not in the system's bottom bar")
      // AND THE SEARCH FIELD IS ACTUALLY DOWN THERE WITH IT. `.minimize` says the field is
      // collapsed, not where: without this item it collapses into the NAVIGATION bar, next to
      // the browse menu, and opening search takes that bar over so the menu disappears. Every
      // comment in both files claimed the two shared one bar while they did not — which is
      // exactly the class of claim a lint has to carry, because prose cannot be run.
      #expect(
        code.contains("DefaultToolbarItem(kind: .search, placement: .bottomBar)"),
        "\(name): search collapses into the top bar, not the bar the filter is in")
    }
  }

  @Test("every screen's title is inline")
  func titlesAreInline() throws {
    // A large title on one screen of a flow and an inline one on the next is a header that
    // changes height as you push. The browser opened large; the kind picker, three pushes into
    // the filter sheet, still did.
    for file in try Self.appFiles() {
      let code = Self.code(file.text)
      let titles = code.ranges(of: ".navigationTitle(").count
      guard titles > 0 else { continue }
      #expect(
        code.ranges(of: ".navigationBarTitleDisplayMode(.inline)").count >= titles,
        "\(file.name) has \(titles) titles and fewer inline modes")
    }
  }

  // MARK: - Accessibility: a control nothing can reach

  /// The app's view declarations, one chunk each. `.combine` is a property of ONE view, so a
  /// file-level scan would report the pool row's banner (which combines correctly) for the pool
  /// row's own defect.
  static func structChunks(in code: String) -> [String] {
    code.components(separatedBy: "\nstruct ")
  }

  @Test("no view combines away a control or a canvas's own accessibility")
  func controlsStayReachableToVoiceOver() throws {
    // THE DEFECT THIS EXISTS FOR. `PoolRowView` combined its children into one element, which
    // swallowed the navigation link, the favourite, the lane disclosure and every one of the
    // ribbon's hand-built `a11yBlocks` — the app paid for canvas accessibility explicitly and
    // then hid all of it behind one label. Combining is right for a row that is only text
    // (a banner, a legend entry); it is wrong the moment the view builds something to press.
    for file in try Self.appFiles() {
      for chunk in Self.structChunks(in: Self.code(file.text))
      where chunk.contains(".accessibilityElement(children: .combine)") {
        for offender in ["NavigationLink(", ".accessibilityChildren"] {
          #expect(
            !chunk.contains(offender),
            "\(file.name): a view combines its children AND builds \(offender) — use `.contain`")
        }
        #expect(
          chunk.ranges(of: "Button(").count <= 1,
          "\(file.name): a view combines its children and builds two or more buttons")
      }
    }
  }

  @Test("the pool row is a container, and its lane control is big enough to hit")
  func thePoolRowIsAContainer() throws {
    let row = try #require(try Self.appFiles().first { $0.name == "PoolRowView.swift" })
    let code = Self.code(row.text)
    #expect(code.contains(".accessibilityElement(children: .contain)"))
    // The lane disclosure was a `.caption` chevron — about 11 points, which is a control you
    // can see and cannot reliably hit. The HIG asks for 44 and the token says so once.
    #expect(
      code.contains("minHeight: Design.hitTarget"),
      "the lane disclosure no longer states a minimum hit target")
    // ...and the whole row navigates, rather than the pool's name alone.
    #expect(code.contains(".frame(maxWidth: .infinity, alignment: .leading)"))
  }

  @Test("the ribbon's hit test resolves to something the row can render")
  func theRibbonTapIsNotDead() throws {
    // It stored the block's ID in a `@State` nothing read, so the gesture ran, resolved a block
    // through the axis, and changed nothing on screen for two slices.
    let row = try #require(try Self.appFiles().first { $0.name == "PoolRowView.swift" })
    let code = Self.code(row.text)
    #expect(code.contains("@State private var selectedBlock: A11yBlock?"))
    #expect(
      code.contains("Text(block.label, localized)"),
      "the tapped block's own sentence is not rendered — the tap is dead again")
  }

  @Test("`.glassEffect()` is applied nowhere; the system paints the bar")
  func nothingPaintsItsOwnGlass() throws {
    // The HIG: "Don't use Liquid Glass in the content layer", and "glass can not sample other
    // glass" — so a second glass surface renders inconsistently against the first. The filter
    // bar is the app's one bar, and it is the only place this may appear.
    // Stronger than it used to be. This once permitted ONE hand-painted glass surface — the
    // custom filter bar — and banned the rest. That bar is gone: the filter control is a
    // toolbar item, so the SYSTEM paints its glass, in its own bar, with the scroll edge
    // effect that comes with it. The app now paints none at all, which is the whole lesson of
    // the iOS 26 guidance: you do not apply the material, you use the chrome that already has
    // it. A `.glassEffect(` reappearing here means something is being hand-built again.
    for file in try Self.appFiles() where Self.code(file.text).contains(".glassEffect(") {
      Issue.record("\(file.name) paints its own glass; the system paints the toolbar's")
    }
  }

  @Test("the filter bar is attached with safeAreaBar, never safeAreaInset or an overlay")
  func filterBarUsesSafeAreaBar() throws {
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    let code = Self.code(view.text)
    // `safeAreaBar` is the ONLY one that extends the scroll edge effect under the bar; the
    // other two float a rectangle over clipped content.
    #expect(code.contains(".safeAreaBar(edge:"))
    #expect(!code.contains(".safeAreaInset("))
  }

  @Test("nothing pins the chrome open, and both bars hang off the SCROLLING view")
  func chromeYieldsToContent() throws {
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    let code = Self.code(view.text)
    #expect(code.contains(".searchable("))

    // This lint used to REQUIRE `.navigationBarDrawer(displayMode: .always)`, on the reading
    // that it was the HIG's blessed inline-for-filtering placement. `.always` is not a
    // placement — it is a pin, and it is why the field never yielded a row no matter how far
    // you scrolled. The HIG's point is about WHERE search sits, not about keeping it open.
    #expect(
      !code.contains("displayMode: .always"),
      "`.always` pins the search field open; the default yields it on scroll")
    // Search is REACHED, not resident. `.searchToolbarBehavior(.minimize)` did that, but on a
    // screen that already owns a bottom bar it added a SECOND stacked bottom surface. The
    // property that matters is that the field is presented on demand and the control lives in
    // the bar the thumb is already near — so the lint checks that, not a modifier name.
    #expect(
      code.contains(".searchToolbarBehavior(.minimize)"),
      "the search field is reached from the toolbar, never resident in a row of its own")
    // ONE bottom bar, and it is the system's. Two custom attempts stacked a second surface
    // under the field iOS 26 already draws at the bottom; the filter control is a toolbar
    // item now, so it shares that bar and the system insets the list for both.
    #expect(
      code.contains("ToolbarItem(placement: .bottomBar)"),
      "the filter control shares the system's bottom bar with the search field")
    #expect(
      !code.contains(".safeAreaBar(edge: .bottom)"),
      "a bar of our own at the bottom stacks under the system's search field")

    // NO TITLE AT ALL on this screen. It used to spell the day out while the strip underneath
    // drew the same fact — one thing said twice, costing a row of a phone screen for the copy
    // you cannot tap. The strip is the one that stays.
    #expect(
      !code.contains(".navigationTitle("),
      "the find screen is naming the day again, above a strip that already says it")
    #expect(!code.contains("Message(\"app.title\")"))
    // NO NAVIGATION BAR EITHER. Once the title went, the bar was a full row of chrome holding
    // one overflow button — the same height the title cost, saying nothing. The controls moved
    // to the bottom bar and the bar went with them.
    #expect(
      code.contains(".toolbarVisibility(.hidden, for: .navigationBar)"),
      "the find screen has a navigation bar again — that is ~50 points of the list")
    // ...and nothing is behind an ellipsis. Two destinations, neither of them a rarely-wanted
    // variant of anything, were costing two taps each and a bar to hang the menu on.
    #expect(
      !code.contains("Icon.browse"),
      "the overflow menu is back; both of its items are one-tap controls now")
    // ...and the strip yields to the content rather than sitting there for the whole scroll.
    // Whether it shows is the KIT's rule; a threshold in a `body` is one nothing measures.
    #expect(
      code.contains("stripShouldShow(") && code.contains(".onScrollGeometryChange("),
      "the day strip no longer yields to the list")
    // NEVER from inside the scroll callback: that runs on every frame of a drag, and starting
    // an animation there is what stopped the app ever reporting itself idle.
    #expect(
      !code.contains("withAnimation"),
      "an animation is being started from the scroll callback again")

    // The defect this lint exists to prevent from returning. A `VStack` between the
    // navigation bar and the `List` leaves the bar with no scroll view to respond to: the
    // title never collapses and neither bar receives the scroll edge effect, which IS the
    // Liquid Glass. Both bars must attach to the scrolling view itself.
    #expect(
      !code.contains("VStack(spacing: 0) {"),
      "a stack between the bar and the List is what broke the title collapse and the glass")
    // The day strip is ours and rides the scroll view. The bottom bar is the SYSTEM's, shared
    // with the search field — a `safeAreaBar` of our own down there stacked a second surface
    // under the field iOS 26 already draws, and hid the rows behind both.
    #expect(code.contains(".safeAreaBar(edge: .top)"))
    #expect(
      !code.contains(".safeAreaBar(edge: .bottom)"),
      "the bottom bar belongs to the system, and it already has the search field in it")
  }

  @Test("the iOS 26 day-strip adoptions are actually in the strip")
  func dayStripAdoptions() throws {
    let strip = try #require(try Self.appFiles().first { $0.name == "DayStrip.swift" })
    let code = Self.code(strip.text)
    for required in [
      // Bidirectional, so the centred chip is readable back — which `ScrollViewReader` cannot
      // do.
      ".scrollPosition(",
      ".scrollTargetBehavior(.viewAligned)",
      // Apple: "Scroll edge effects aren't decorative." Nothing passes under this strip.
      ".scrollEdgeEffectHidden(for: .horizontal)",
      ".sensoryFeedback(.selection,",
      // The 44 pt rule needs the whole chip to be the target, not just its glyphs.
      ".contentShape(Rectangle())",
    ] {
      #expect(code.contains(required), "the day strip no longer uses \(required)")
    }
    #expect(!code.contains("ScrollViewReader"))
  }

  @Test("the list is a `List`, and nothing pretends to refresh a bundled store")
  func listAndNoFakeRefresh() throws {
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    let code = Self.code(view.text)
    #expect(code.contains("List {"), "the rows must be a List — .swipeActions needs one")
    #expect(!code.contains("LazyVStack"))
    // The store is bundle-only until S5. A pull-to-refresh would spin and change nothing,
    // which is a lie told with an animation.
    #expect(!code.contains(".refreshable"))
  }

  // MARK: - Acceptance 5: List laziness, structurally

  @Test("no ForEach element resolves to a variable number of views")
  func forEachElementsAreOneView() throws {
    // WWDC23 10160: a variable-count element forces `List` to build EVERY row's body just to
    // learn the identifiers. The obvious implementation of S3b's expandable Gantt —
    // `if expanded { GanttView() }` inside the element — is exactly that anti-pattern, which
    // is why the rule is pinned here, one slice before it is tempting.
    // The real-file direction, pinned first: the lint must actually be finding elements in the
    // screen it exists to police. A scanner that returned nothing would satisfy every
    // expectation in the loop below forever.
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    #expect(
      forEachBodies(in: Self.code(view.text)).count >= 3,
      "the laziness lint found no ForEach elements in the list screen — it is scanning nothing"
    )
    for file in try Self.appFiles() {
      for body in forEachBodies(in: Self.code(file.text)) {
        for keyword in ["if ", "if(", "switch ", "switch("] {
          let site = "\(file.name):\(body.line): a branch inside a ForEach element"
          let why = "resolves to a variable number of views and defeats List laziness"
          #expect(!body.text.contains(keyword), "\(site) \(why) — wrap it in one container")
        }
      }
    }
  }

  @Test("the laziness lint really finds ForEach elements, and really rejects a branch")
  func lazinessLintIsNotVacuous() {
    // A lint that scanned nothing would pass the test above forever. Both directions are
    // pinned: a compliant element is accepted, and the anti-pattern is caught.
    let good = """
      ForEach(section.rows) { row in
        PoolRowView(row: row)
      }
      """
    let bad = """
      ForEach(section.rows) { row in
        if expanded { GanttView(row: row) }
        PoolRowView(row: row)
      }
      """
    #expect(forEachBodies(in: good).count == 1)
    #expect(forEachBodies(in: good)[0].text.contains("PoolRowView"))
    #expect(forEachBodies(in: bad).count == 1)
    #expect(forEachBodies(in: bad)[0].text.contains("if "))
  }
}

/// One `ForEach { … }` trailing-closure body, and the line it started on.
struct ForEachBody {
  let line: Int
  let text: String
}

/// Every `ForEach(...) { ... }` trailing-closure body in `code`, brace-matched.
///
/// A brace match rather than a regex: a `ForEach` body contains braces of its own, and a
/// line-based scan would stop at the first `}` — reporting compliance for exactly the nested
/// case the rule is about. NESTED `ForEach`es are found too, because the scan continues from
/// just after the opening brace rather than skipping the whole body.
func forEachBodies(in code: String) -> [ForEachBody] {
  let characters = Array(code)
  var bodies: [ForEachBody] = []
  var index = 0
  var line = 1
  while index < characters.count {
    if characters[index] == "\n" { line += 1 }
    guard characters[index] == "F", matches("ForEach", in: characters, at: index) else {
      index += 1
      continue
    }
    // `continue`, NEVER `break`: a `ForEach` token that is not a call with a trailing closure
    // (a mention in a string, a `ForEach` type reference) must skip ITSELF, not abandon the rest
    // of the file. Breaking here would silently disable the laziness lint for everything below
    // it while the test still passed — the exact shape of a gate that stops gating.
    guard let open = openingBrace(in: characters, from: index) else {
      index += 1
      continue
    }
    if let close = closingBrace(in: characters, from: open) {
      bodies.append(ForEachBody(line: line, text: String(characters[(open + 1)..<close])))
    }
    index = open + 1
  }
  return bodies
}

private func matches(_ needle: String, in characters: [Character], at index: Int) -> Bool {
  let needle = Array(needle)
  guard index + needle.count <= characters.count else { return false }
  return Array(characters[index..<(index + needle.count)]) == needle
}

/// The `{` that opens the trailing closure — the first one after the call's balanced parens.
private func openingBrace(in characters: [Character], from index: Int) -> Int? {
  var depth = 0
  var cursor = index
  while cursor < characters.count {
    switch characters[cursor] {
    case "(": depth += 1
    case ")": depth -= 1
    case "{" where depth == 0: return cursor
    // A newline at paren depth 0 before any brace means this `ForEach` was not a call with a
    // trailing closure (e.g. a mention in a string); give up rather than run to the next one.
    case "\n" where depth == 0 && cursor > index + "ForEach".count: return nil
    default: break
    }
    cursor += 1
  }
  return nil
}

private func closingBrace(in characters: [Character], from open: Int) -> Int? {
  var depth = 0
  var cursor = open
  while cursor < characters.count {
    if characters[cursor] == "{" { depth += 1 }
    if characters[cursor] == "}" {
      depth -= 1
      if depth == 0 { return cursor }
    }
    cursor += 1
  }
  return nil
}
