// PoolRowView.swift — one pool's row, and the banners above the list.
//
// THE STRUCTURAL RULE THIS FILE KEEPS (S3a acceptance 5): the row is ONE view. A `ForEach`
// element that resolves to a variable number of views forces `List` to build every row's body
// just to learn the identifiers (WWDC23 10160) — which is precisely what the obvious
// `if expanded { … }` would do, and precisely the laziness S3b's expandable Gantt must not
// cost. So everything a row can grow into stays inside one `VStack`, and a source lint asserts
// no `if`/`switch` appears directly inside the row `ForEach`'s element.
//
// No `.glassEffect()` here either: rows are the content layer, and glass cannot sample glass.
//
// WHAT THE HIG REVIEW CHANGED HERE, and why each one was a real defect rather than a taste:
//
//  * THE ROW WAS ONE ACCESSIBILITY ELEMENT. `.accessibilityElement(children: .combine)` merged
//    the whole subtree into a single label — which swallowed the navigation link, the lane
//    disclosure, and every one of the ribbon's hand-built `a11yBlocks`. The app paid for canvas
//    accessibility explicitly (see `RibbonCanvas`) and then hid it. It is `.contain` now: the
//    row is a container whose children stay reachable, and the SUMMARY sentence moved onto the
//    link, so one swipe still reads name, verdict and mark in one go.
//  * ONLY THE NAME NAVIGATED. Everything else in the row was dead to a tap, while the all-pools
//    browser made the whole row a link for the same destination. The title, the verdict and the
//    sessions are one link now, full width.
//  * THE LANE DISCLOSURE WAS AN 11-POINT CHEVRON. A bare `.caption` glyph is a control you can
//    see and cannot reliably hit; the HIG asks for 44. It is a labelled row of its own now,
//    under the ribbon, using the two catalog sentences that already existed for it — and being
//    outside the link is what lets both be tapped without fighting.
//  * TAPPING THE RIBBON DID NOTHING. The spatial hit test resolved a block and stored its id in
//    a `@State` nothing rendered. The block's own sentence is shown now, which is what the hit
//    test was always for.

import SwiftUI
import SwimZHKit

struct PoolRowView: View {
  @Environment(\.localized) private var localized
  let row: PoolRow
  let isFavourite: Bool
  /// Whether the answer is for the day the user is standing in. It reaches the canvas, which
  /// draws the "now" cursor ONLY on today: a cursor on a future date would be a present-tense
  /// claim about a day nobody is in, which is the bug class this app has already shipped twice.
  let isToday: Bool
  let isExpanded: Bool
  let namespace: Namespace.ID
  let onToggleFavourite: () -> Void
  let onToggleExpanded: () -> Void

  /// The block the reader last tapped on the ribbon, or none.
  ///
  /// It holds the BLOCK, not its id: the id alone was what made this state unrenderable, and
  /// therefore what made the tap dead. `block(at:)` already returns the whole thing, sentence
  /// included, from the same axis the ribbon was painted with.
  @State private var selectedBlock: A11yBlock?

  var body: some View {
    // ONE container. See the header. Everything the row can grow into — its day tail and its
    // expanded lane chart — lives inside this `VStack`, so the `ForEach` element that produced
    // it always resolves to exactly one view.
    VStack(alignment: .leading, spacing: Design.Space.snug) {
      link
      tail
      blockCaption
      laneDisclosure
      expanded
    }
    .padding(.vertical, Design.Space.hair)
    // `.contain`, NEVER `.combine`. See the header: combining swallowed the link, the
    // disclosure and every ribbon block, which is the whole of this row's accessibility.
    .accessibilityElement(children: .contain)
    .swipeActions(edge: .leading) {
      Button(action: onToggleFavourite) {
        Label(
          Message(isFavourite ? "action.unfavourite" : "action.favourite"),
          systemImage: favouriteSymbol, localized)
      }
      // The app's own tint, not the row's TIER colour. A swipe action that changes colour from
      // row to row reads as a different action, and tier colour means something else here.
      .tint(.accentColor)
    }
    // A HEART IS A PHYSICAL ACT. `.sensoryFeedback` rather than a `UIImpactFeedbackGenerator`:
    // it is declarative, it costs no UIKit import in a SwiftUI target, and it obeys the
    // reader's own haptics setting without this file having to ask. `.impact` and not
    // `.success` — nothing succeeded, a switch moved.
    .sensoryFeedback(.impact(weight: .light), trigger: isFavourite)
  }

  private var favouriteSymbol: String { isFavourite ? Icon.unfavourite : Icon.favourite }

  /// The row's answer, and the link to the whole story.
  ///
  /// Full width, so a tap anywhere on the text navigates — the same target the all-pools
  /// browser has always had for the same destination. NO disclosure chevron of our own: `List`
  /// draws one for this link even though it shares the row with the ribbon below it, and a
  /// hand-drawn second one sat beside the system's in the simulator.
  private var link: some View {
    NavigationLink(value: Route.pool(row.poolID)) {
      VStack(alignment: .leading, spacing: Design.Space.snug) {
        header
        verdict
        sessions
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .matchedTransitionSource(id: row.poolID, in: namespace)
    // The four clauses, on the ONE element that both reads them and navigates.
    .accessibilityLabel(Text(verbatim: accessibilityLabel))
    // The swipe action, said out loud. VoiceOver surfaces swipe actions on a plain row; this
    // row is a container, so the action is named here rather than hoped for.
    .accessibilityAction(
      named: Text(Message(isFavourite ? "action.unfavourite" : "action.favourite"), localized),
      onToggleFavourite
    )
    // For `SwimZHUITests`, which drives the app instead of reading it. Not the English label:
    // a test that queried a sentence would pass in one language and fail in four.
    .accessibilityIdentifier("poolRow")
  }

  private var header: some View {
    HStack(alignment: .firstTextBaseline, spacing: Design.Space.row) {
      Image(systemName: row.tier.symbol)
        .foregroundStyle(row.tier.accent)
        .accessibilityHidden(true)
      Text(row.poolName)
        .font(.rowTitle)
        // A pool name is NEVER truncated: it is the one thing a row exists to say, and at an
        // accessibility size it is allowed to take as many lines as it needs.
        .fixedSize(horizontal: false, vertical: true)
      Spacer(minLength: Design.Space.tight)
      favouriteMark
      Image(systemName: row.mark.symbol)
        .foregroundStyle(row.mark.accent)
        .accessibilityLabel(Text(row.mark.voiceOverLabel, localized))
    }
  }

  /// The disclosure for the per-lane chart, shown ONLY where there is a parsed lane plan to
  /// show. A control that expands into nothing is worse than no control.
  ///
  /// A labelled row rather than the 11-point chevron it replaces: it says what it will do, in
  /// the reader's language, at a size the HIG's 44 points actually covers. Outside the link, so
  /// the two targets never fight.
  @ViewBuilder
  private var laneDisclosure: some View {
    if !panels.isEmpty {
      Button(action: onToggleExpanded) {
        Label(
          Message(isExpanded ? "action.hideLanePlan" : "action.showLanePlan"),
          systemImage: isExpanded ? Icon.collapse : Icon.expand, localized
        )
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .frame(minHeight: Design.hitTarget, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
      }
      // `.borderless`, so the List routes the tap here instead of to the row's link.
      .buttonStyle(.borderless)
      .accessibilityIdentifier("laneDisclosure")
    }
  }

  /// The sentence for the ribbon block the reader tapped.
  ///
  /// It is the block's OWN label — the same `Message` VoiceOver reads for it — so the tap and
  /// the screen reader answer with one sentence rather than two.
  @ViewBuilder
  private var blockCaption: some View {
    if let block = selectedBlock {
      Text(block.label, localized)
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityHidden(true)
        .accessibilityIdentifier("blockCaption")
    }
  }

  /// The day tail: this row's whole day as a ribbon, with the hour marks.
  ///
  /// Built from `dayRibbon(for:)` in the package, so the phone paints the same encoding the
  /// desktop board does from the same facts.
  private var tail: some View {
    RibbonCanvas(
      day: dayRibbon(for: row), isToday: isToday, selection: $selectedBlock,
      localized: localized)
  }

  /// The expanded lane chart — ONE at a time, never 57 in the list.
  ///
  /// `TodayModel` holds a single expanded row id, so opening a second row closes the first;
  /// this branch is what turns that into "at most one `Chart` exists". 57 live charts inside a
  /// `List` is the shape with credible reports of 100% CPU and 50–150 ms hangs.
  @ViewBuilder
  private var expanded: some View {
    if isExpanded {
      ForEach(panels) { panel in
        LaneGanttView(panel: panel)
      }
    }
  }

  /// The lane panels this row can show — one per basin with a parsed Belegungsplan, taken from
  /// the options themselves so no second read is needed.
  private var panels: [LanePanel] {
    var seen: Set<String> = []
    return row.options.compactMap { option in
      guard let day = option.laneDayView, !seen.contains(option.basinID) else { return nil }
      seen.insert(option.basinID)
      return LanePanel(basinID: option.basinID, basinName: option.basinName, day: day)
    }
  }

  @ViewBuilder
  private var favouriteMark: some View {
    if isFavourite {
      Image(systemName: Icon.favouriteMark)
        .font(.rowFact)
        // The app's TINT, not the row's tier colour: a heart is not a time of day, and tier
        // colour is the vocabulary that says when a session runs.
        .foregroundStyle(.tint)
        .accessibilityLabel(Text(Message("action.favourite"), localized))
    }
  }

  private var verdict: some View {
    HStack(spacing: Design.Space.tight) {
      Text(row.verdict.head, localized).font(.rowVerdict)
      verdictTail
      Spacer(minLength: 0)
      distance
    }
  }

  @ViewBuilder
  private var verdictTail: some View {
    if let tail = row.verdict.tail {
      // The middot is PUNCTUATION between two whole clauses, not grammar joining two
      // fragments — the same distinction the web's `insight.*` clause list makes. Each half is
      // a translatable unit that stands on its own, which is why the separator can live here.
      Text(verbatim: "· \(localized(tail))").font(.rowVerdictTail).foregroundStyle(.secondary)
    }
  }

  @ViewBuilder
  private var distance: some View {
    if let km = row.distanceKm {
      // `Measurement` formatting, not a hand-built string: it gets the unit, the separator and
      // the fraction right per locale, which the web pinned by test after getting it wrong.
      // `Format`, not an inline `.measurement` style: the unit, the separator and the
      // fraction are the READER's regional locale's, and this view has no business knowing
      // that de-CH uses a dot where fr-CH uses a comma.
      Text(verbatim: localized.format.distance(kilometres: km))
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .monospacedDigit()
    }
  }

  /// The sessions the MODEL says to show inline. The cap and the remainder are decided by
  /// `listModel` (`inlineSessionLimit`), not here: a threshold that governs what a swimmer
  /// sees is a rule, and a rule in a view body is one the CRAP gate never scores.
  private var sessions: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      ForEach(row.inlineOptions) { option in
        SessionLine(option: option, isToday: isToday, localized: localized)
      }
      moreSessions
    }
  }

  /// The model's own sentence, or nothing. The view does not compose it: its wording depends on
  /// whether the answer is for TODAY, and "+2 more today" printed on a date four months out was
  /// the last temporal claim the app could still make off-today.
  @ViewBuilder
  private var moreSessions: some View {
    if let label = row.moreSessionsLabel {
      Text(label, localized)
        .font(.rowNote)
        .foregroundStyle(.secondary)
    }
  }

  /// The row's spoken headline: four independent clauses read as a list.
  ///
  /// A list, NOT a sentence. Each part stands on its own — a name, a verdict, its tail, an
  /// eligibility mark — and the comma between them is punctuation, so no language has to accept
  /// English word order. Every part is localised BEFORE it is joined; joining first and
  /// translating after is the mistake this shape exists to make impossible.
  private var accessibilityLabel: String {
    var parts: [Wording] = [.verbatim(row.poolName), .message(row.verdict.head)]
    if let tail = row.verdict.tail { parts.append(.message(tail)) }
    parts.append(.message(row.mark.voiceOverLabel))
    return localized(.joined(parts))
  }
}

/// One session inside a row.
///
/// TWO LINES, NOT FIVE THINGS ON ONE, and a screenshot is what settled it. The single-row form
/// put the window, the basin, the lane split, the price and two badges in one `HStack`, and on a
/// real iPhone the widest row read:
///
///     06:00–  Schwimmer…  5 of 6 lanes…  Erwachsene (ab
///     22:00                              20 J.) Fr. 8.00
///
/// — a time broken across two lines, a basin truncated, a lane summary truncated and a price
/// wrapped mid-parenthesis. Every one of those is a fact the row was spending space to say and
/// then not saying. The fix is not smaller type (the ramp already had it at its smallest) and
/// not `minimumScaleFactor` (which makes a row of five sizes): it is to stop asking one line to
/// hold two ranks.
///
/// So line one is WHEN AND WHERE — the window, the basin, and whether you may attend. Line two
/// is WHAT IT COSTS AND WHAT IS LEFT — the lane split, the price, the fair-weather badge — and
/// it is absent entirely when the source published none of them. Nothing truncates, because
/// nothing is competing.
struct SessionLine: View {
  let option: SwimOption
  /// Whether this answer is for the day the user is standing in. The lane line's wording
  /// depends on it, because off today the store is asked at a fixed midday moment and nothing
  /// read from that moment may be spoken as a fact about now (invariant E1).
  let isToday: Bool
  let localized: Localized

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      whenAndWhere
      support
    }
  }

  private var whenAndWhere: some View {
    HStack(spacing: Design.Space.snug) {
      // A time RANGE, built from two store values and an en dash. Both halves are `HH:MM` as
      // the store wrote them, and the dash is punctuation. `fixedSize` because a broken time is
      // not a time — everything else on the line yields before this does.
      Text(verbatim: "\(option.window.start.hhmm)–\(option.window.end.hhmm)")
        .font(.rowFact)
        .monospacedDigit()
        .fixedSize()
      // The basin's own name, as the pool wrote it.
      Text(verbatim: option.basinName)
        .font(.rowFact)
        .foregroundStyle(.secondary)
        .lineLimit(1)
      Spacer(minLength: 0)
      Image(systemName: option.mark.symbol)
        .font(.rowNote)
        .foregroundStyle(option.mark.accent)
        .accessibilityLabel(Text(option.mark.voiceOverLabel, localized))
    }
  }

  /// The supporting half, or nothing at all. `@ViewBuilder` rather than an always-present row
  /// with three optional children: an empty `HStack` still costs its spacing, and a two-point
  /// gap under every session was visible as a ragged rhythm down the card.
  @ViewBuilder
  private var support: some View {
    if hasSupport {
      HStack(spacing: Design.Space.snug) {
        lanes
        price
        fairWeather
        Spacer(minLength: 0)
      }
    }
  }

  private var hasSupport: Bool {
    option.laneSummary(isToday: isToday, format: localized.format) != nil || option.price != nil
      || option.isFairWeatherOnly
  }

  /// "5 of 8 lanes open" — `OptionOut.lane_availability`, rendered.
  ///
  /// The SENTENCE is the package's (`SwimOption.laneSummary(isToday:)`), including the edge
  /// case that matters: zero public lanes is not "0 of 8 open", which reads as a measurement,
  /// but "no lanes open to the public", which is what the plan says. Absent for a basin with no
  /// published plan — never an empty string, which would read as "no lanes free". `isToday` is
  /// threaded in rather than assumed: the split is a wall-clock fact and off today there is no
  /// wall clock to read it from.
  @ViewBuilder
  private var lanes: some View {
    if let summary = option.laneSummary(isToday: isToday, format: localized.format) {
      Text(summary, localized)
        .font(.rowNote)
        .foregroundStyle(.secondary)
    }
  }

  /// A session the source publishes only for fair weather.
  ///
  /// The TOKEN comparison lives in `SwimZHKit` (`SwimOption.isFairWeatherOnly`), where a test
  /// pins it — mirroring the web, which keeps `FAIR_ONLY` in its measured module. Compared
  /// here, a change to the export's spelling would make this badge silently vanish with every
  /// gate still green.
  @ViewBuilder
  private var fairWeather: some View {
    if option.isFairWeatherOnly {
      Image(systemName: Icon.fairWeather)
        .font(.rowNote)
        .foregroundStyle(.secondary)
        .accessibilityLabel(Text(Message("session.fairWeather.badge"), localized))
    }
  }

  @ViewBuilder
  private var price: some View {
    if let price = option.price {
      // The pool's OWN price line, quoted rather than rebuilt: it is a dated fact off their
      // page, and re-formatting it would silently restate what they published.
      Text(verbatim: price.display).font(.rowNote).foregroundStyle(.secondary)
    }
  }
}

/// A day-level caveat, or a pool's own words.
struct BannerView: View {
  @Environment(\.localized) private var localized
  let banner: BannerModel

  var body: some View {
    HStack(alignment: .top, spacing: Design.Space.row) {
      Image(systemName: banner.kind.symbol)
        .foregroundStyle(banner.kind.accent)
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: Design.Space.hair) {
        // A WARNING's two halves are ours; a NOTICE's are the pool's name and the pool's
        // own sentence. `Wording` is what keeps the renderer from translating either.
        Text(banner.title, localized).font(.noticeTitle)
        Text(banner.text, localized).font(.noticeBody).foregroundStyle(.secondary)
      }
    }
    .accessibilityElement(children: .combine)
  }
}
