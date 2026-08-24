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
  let onToggleFavourite: () -> Void

  var body: some View {
    // ONE container. See the header.
    VStack(alignment: .leading, spacing: 6) {
      header
      verdict
      sessions
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
      Text(row.poolName)
        .font(.headline)
        // A pool name is NEVER truncated: it is the one thing a row exists to say, and at an
        // accessibility size it is allowed to take as many lines as it needs.
        .fixedSize(horizontal: false, vertical: true)
      Spacer(minLength: 4)
      favouriteMark
      Image(systemName: row.mark.symbol)
        .foregroundStyle(row.mark.accent)
        .accessibilityLabel(row.mark.voiceOverLabel)
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
        SessionLine(option: option)
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
      fairWeather
      price
      Image(systemName: option.mark.symbol)
        .font(.caption2)
        .foregroundStyle(option.mark.accent)
        .accessibilityLabel(option.mark.voiceOverLabel)
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
