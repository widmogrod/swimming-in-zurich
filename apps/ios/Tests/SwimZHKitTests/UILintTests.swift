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
    // `FacilityDetailOut.facility_name` has no `DetailRow` of its own — it is the sheet's
    // title — so this lint is its evidence, and the reason `facility_id` is deliberately NOT
    // claimed rendered (see `FieldCoverage.deliberatelyOmitted`).
    let sheet = try #require(try Self.appFiles().first { $0.name == "FacilitySheet.swift" })
    let code = Self.code(sheet.text)
    #expect(code.contains(".navigationTitle(detail.name)"))
    #expect(!code.contains("Text(detail.poolID)"))
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

  @Test("`.glassEffect()` appears only in the filter bar")
  func glassOnlyInTheFilterBar() throws {
    // The HIG: "Don't use Liquid Glass in the content layer", and "glass can not sample other
    // glass" — so a second glass surface renders inconsistently against the first. The filter
    // bar is the app's one bar, and it is the only place this may appear.
    for file in try Self.appFiles() where Self.code(file.text).contains(".glassEffect(") {
      let site = "\(file.name) applies .glassEffect() outside the filter bar"
      #expect(file.name == "FilterBar.swift", "\(site) — glass cannot sample glass")
    }
    let bar = try #require(try Self.appFiles().first { $0.name == "FilterBar.swift" })
    // ...and it really is applied there, so the lint above cannot pass because glass vanished.
    #expect(Self.code(bar.text).contains(".glassEffect("))
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

  @Test("search is INLINE WITH CONTENT, because it filters rather than navigates")
  func searchIsInlineWithContent() throws {
    let view = try #require(try Self.appFiles().first { $0.name == "TodayView.swift" })
    let code = Self.code(view.text)
    #expect(code.contains(".searchable("))
    // The HIG blesses the inline placement for FILTERING, which is all this search does — it
    // never pushes a result screen. `.navigationBarDrawer(displayMode: .always)` is that
    // placement: the field sits below the title, in the scrolling content.
    #expect(code.contains(".navigationBarDrawer(displayMode: .always)"))
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
