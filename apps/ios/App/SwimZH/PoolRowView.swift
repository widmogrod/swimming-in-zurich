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

import SwiftUI
import SwimZHKit

struct PoolRowView: View {
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

  @State private var selectedBlock: String?

  var body: some View {
    // ONE container. See the header. Everything the row can grow into — its day tail and its
    // expanded lane chart — lives inside this `VStack`, so the `ForEach` element that produced
    // it always resolves to exactly one view.
    VStack(alignment: .leading, spacing: 6) {
      header
      verdict
      sessions
      tail
      expanded
    }
    .padding(.vertical, 2)
    .accessibilityElement(children: .combine)
    .accessibilityLabel(accessibilityLabel)
    .swipeActions(edge: .leading) {
      Button(isFavourite ? "Unfavourite" : "Favourite", systemImage: favouriteSymbol) {
        onToggleFavourite()
      }
      .tint(row.tier.accent)
    }
  }

  private var favouriteSymbol: String { isFavourite ? "heart.slash" : "heart" }

  private var header: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      Image(systemName: row.tier.symbol)
        .foregroundStyle(row.tier.accent)
        .accessibilityHidden(true)
      // The name opens the facility sheet. `matchedTransitionSource` is HALF of the zoom
      // transition — the destination carries the other half — and neither works alone.
      NavigationLink(value: row.poolID) {
        Text(row.poolName)
          .font(.headline)
          // A pool name is NEVER truncated: it is the one thing a row exists to say, and at an
          // accessibility size it is allowed to take as many lines as it needs.
          .fixedSize(horizontal: false, vertical: true)
      }
      .buttonStyle(.plain)
      .matchedTransitionSource(id: row.poolID, in: namespace)
      Spacer(minLength: 4)
      favouriteMark
      Image(systemName: row.mark.symbol)
        .foregroundStyle(row.mark.accent)
        .accessibilityLabel(row.mark.voiceOverLabel)
      laneToggle
    }
  }

  /// The disclosure for the per-lane chart, shown ONLY where there is a parsed lane plan to
  /// show. A chevron that expands into nothing is worse than no chevron.
  @ViewBuilder
  private var laneToggle: some View {
    if !panels.isEmpty {
      Button(action: onToggleExpanded) {
        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .buttonStyle(.plain)
      .contentShape(Rectangle())
      .accessibilityLabel(isExpanded ? "Hide the lane plan" : "Show the lane plan")
    }
  }

  /// The day tail: this row's whole day as a ribbon, with the hour marks.
  ///
  /// Built from `dayRibbon(for:)` in the package, so the phone paints the same encoding the
  /// desktop board does from the same facts.
  private var tail: some View {
    RibbonCanvas(day: dayRibbon(for: row), isToday: isToday, selection: $selectedBlock)
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
      Image(systemName: "heart.fill")
        .font(.caption)
        .foregroundStyle(row.tier.accent)
        .accessibilityLabel("Favourite")
    }
  }

  private var verdict: some View {
    HStack(spacing: 4) {
      Text(row.verdict.head).font(.subheadline.weight(.semibold))
      verdictTail
      Spacer(minLength: 0)
      distance
    }
  }

  @ViewBuilder
  private var verdictTail: some View {
    if let tail = row.verdict.tail {
      Text("· \(tail)").font(.subheadline).foregroundStyle(.secondary)
    }
  }

  @ViewBuilder
  private var distance: some View {
    if let km = row.distanceKm {
      // `Measurement` formatting, not a hand-built string: it gets the unit, the separator and
      // the fraction right per locale, which the web pinned by test after getting it wrong.
      Text(
        Measurement(value: km, unit: UnitLength.kilometers),
        format: .measurement(width: .abbreviated)
      )
      .font(.caption)
      .foregroundStyle(.secondary)
      .monospacedDigit()
    }
  }

  /// The sessions the MODEL says to show inline. The cap and the remainder are decided by
  /// `listModel` (`inlineSessionLimit`), not here: a threshold that governs what a swimmer
  /// sees is a rule, and a rule in a view body is one the CRAP gate never scores.
  private var sessions: some View {
    VStack(alignment: .leading, spacing: 2) {
      ForEach(row.inlineOptions) { option in
        SessionLine(option: option, isToday: isToday)
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
      Text(label)
        .font(.caption)
        .foregroundStyle(.secondary)
    }
  }

  private var accessibilityLabel: String {
    var parts = [row.poolName, row.verdict.head]
    if let tail = row.verdict.tail { parts.append(tail) }
    parts.append(row.mark.voiceOverLabel)
    return parts.joined(separator: ", ")
  }
}

/// One session inside a row.
struct SessionLine: View {
  let option: SwimOption
  /// Whether this answer is for the day the user is standing in. The lane line's wording
  /// depends on it, because off today the store is asked at a fixed midday moment and nothing
  /// read from that moment may be spoken as a fact about now (invariant E1).
  let isToday: Bool

  var body: some View {
    HStack(spacing: 6) {
      Text("\(option.window.start.hhmm)–\(option.window.end.hhmm)")
        .font(.caption)
        .monospacedDigit()
      Text(option.basinName)
        .font(.caption)
        .foregroundStyle(.secondary)
        .lineLimit(1)
      Spacer(minLength: 0)
      lanes
      fairWeather
      price
      Image(systemName: option.mark.symbol)
        .font(.caption2)
        .foregroundStyle(option.mark.accent)
        .accessibilityLabel(option.mark.voiceOverLabel)
    }
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
    if let summary = option.laneSummary(isToday: isToday) {
      Text(summary)
        .font(.caption2)
        .foregroundStyle(.secondary)
        .lineLimit(1)
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
      Image(systemName: "sun.max")
        .font(.caption2)
        .foregroundStyle(.secondary)
        .accessibilityLabel("Fair weather only")
    }
  }

  @ViewBuilder
  private var price: some View {
    if let price = option.price {
      Text(price.display).font(.caption2).foregroundStyle(.secondary)
    }
  }
}

/// A day-level caveat, or a pool's own words.
struct BannerView: View {
  let banner: BannerModel

  var body: some View {
    HStack(alignment: .top, spacing: 8) {
      Image(systemName: banner.kind.symbol)
        .foregroundStyle(banner.kind.accent)
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 2) {
        Text(banner.title).font(.subheadline.weight(.semibold))
        Text(banner.text).font(.footnote).foregroundStyle(.secondary)
      }
    }
    .accessibilityElement(children: .combine)
  }
}
