// Theme.swift — the design system: every colour, size, radius, type role and glyph the app uses.
//
// It began as the colour file, and the rest arrived for the same reason the colours did. A
// review found the app saying one thing four ways: secondary text was `.caption` in one row and
// `.caption2` in the next, corner radii were 12, 3 and 2 with no rule between them, the same
// `questionmark.circle` stood for three unrelated ideas, and the "no match" state carried a
// different icon on each of the two screens that show it. None of that is a bug any test could
// see, and all of it is the same defect: a decision taken at the call site, five times, by
// whoever was editing that file. So every one of those decisions is named ONCE here, and
// `UILintTests` bans the raw forms in the rest of the app target — a font token, a radius and a
// glyph are as much a state-to-value mapping as a colour is, and the reason the colours moved
// here was never that they were colours.
//
// Apple's stated answer to hardcoded colours is a colour asset: it carries a light and a dark
// value, it resolves correctly inside `Canvas` via `GraphicsContext.environment` (which S3b's
// ribbon needs), and it is one place to change. A source lint bans every literal form —
// `#colorLiteral`, `Color(red:`, `Color(.sRGB`, `Color(hue:`, `UIColor(red:` — so this file is
// the only route from a state to a colour, and it contains no channel values itself.
//
// System semantic colours (`.primary`, `.secondary`, `.tint`) are used freely and deliberately:
// they are not literals, they already track appearance and accessibility settings, and
// replacing them with assets would be a downgrade.

import SwiftUI
import SwimZHKit

// MARK: - Metrics

/// The sizes the app is allowed to use. Four spacings, three radii and one hit target — a
/// closed set, so "how much space goes here" stops being a per-file judgement.
enum Design {
  /// The vertical and horizontal rhythm. `hair` separates two lines of one thought, `tight`
  /// two thoughts in one row, `snug` two rows of one card, `gutter` the card from the screen.
  enum Space {
    static let hair: Double = 2
    static let tight: Double = 4
    static let snug: Double = 6
    static let row: Double = 8
    static let gutter: Double = 16
  }

  /// Corner radii. A `control` is something you press, a `swatch` is a small painted sample,
  /// and a `mark` is a bar inside a chart — three sizes, because there are three sizes of
  /// thing, not because three numbers happened to look right in three files.
  enum Radius {
    static let control: Double = 12
    static let swatch: Double = 4
    static let mark: Double = 2
  }

  /// The HIG's minimum comfortable target. Every control the app draws itself is at least this
  /// on both axes — a `.caption`-sized chevron is about 11 points, which is a control you can
  /// see and cannot reliably hit.
  static let hitTarget: Double = 44
}

// MARK: - Type roles

/// The type ramp, by ROLE rather than by size.
///
/// A view asks for the rank of the thing it is showing — a row's title, a fact inside that row,
/// a caveat under it — and the ramp decides which system font that is. The point is not to
/// rename `.caption`: it is that "a price" and "a distance" are the same rank and were shipping
/// as two different sizes, which no amount of care at the call site was going to fix.
extension Font {
  /// The name of the thing a row is about.
  static let rowTitle = Font.headline
  /// The row's answer, in a sentence.
  static let rowVerdict = Font.subheadline.weight(.semibold)
  /// The clause after the verdict — same size, less weight, because it is the same sentence.
  static let rowVerdictTail = Font.subheadline
  /// A FACT inside a row: a time, a distance, a basin, the disclosure that opens the lane plan.
  static let rowFact = Font.caption
  /// What SUPPORTS a fact: a caveat, a remainder, an axis tick, and the lane split, price and
  /// badges riding on a session line that already carries five things.
  static let rowNote = Font.caption2
  /// The heading of a notice or a legend entry.
  static let noticeTitle = Font.subheadline.weight(.semibold)
  /// Its prose.
  static let noticeBody = Font.footnote
  /// The heading of a panel inside a row (the lane chart).
  static let panelTitle = Font.caption.weight(.semibold)
  /// The sentence at the top of the list — a fact, and the largest one on screen.
  static let screenHeadline = Font.title3.weight(.semibold)
  /// The day strip: the numeral, its weekday caption, and the legend that replaces the caption
  /// at an accessibility size.
  static let chipNumber = Font.headline
  static let chipCaption = Font.caption2
  static let stripLegend = Font.subheadline.weight(.semibold)
  /// The pool screen's own name, and the line under it. A DETAIL SCREEN IS NOT A ROW: it opens
  /// on one pool and has the width to say so, which is the difference between a screen and the
  /// table of label/value pairs this app shipped first.
  static let heroTitle = Font.title.weight(.bold)
  static let heroSubtitle = Font.subheadline
  /// The label under one of the three round actions.
  static let actionCaption = Font.caption2.weight(.medium)
}

// MARK: - Glyphs

/// Every SF Symbol the app names, in one list — which is the only way to notice that one glyph
/// is standing for three ideas.
///
/// `questionmark.circle` was doing exactly that: the tier for "we cannot tell", the mark for
/// "check with the pool", and the menu item for the colour legend. The first two ARE the same
/// idea and keep it; the legend is not, and is now `info.circle`.
enum Icon {
  /// The one filter glyph, on both screens that filter. Filled when something is narrowed —
  /// which is the only state difference a reader needs and the one both screens now show.
  static let filter = "line.3.horizontal.decrease.circle"
  static let filterActive = "line.3.horizontal.decrease.circle.fill"
  /// The one empty-result glyph. Both lists reach it through a search or a filter, and showing
  /// two different pictures for one sentence was the plainest inconsistency in the app.
  static let noMatch = "magnifyingglass"
  static let browse = "ellipsis.circle"
  /// THE WHOLE ROSTER, and it must not be `list.bullet`. That is the mode picker's "list"
  /// segment, and when this button rejoined the bottom bar the two sat four inches apart
  /// wearing the same picture — a reader looking at that bar saw one icon twice and had no way
  /// to tell which one showed the pools for today and which one showed all of them. `Icon`
  /// exists to make that visible, and `glyphsAreDistinct` now makes it fail a build.
  ///
  /// A grid rather than another list: the roster is every pool at once, not a ranked answer.
  static let allPools = "square.grid.2x2"
  /// The colour legend — an explanation, not a question.
  static let legend = "info.circle"
  static let favourite = "heart"
  static let unfavourite = "heart.slash"
  static let favouriteMark = "heart.fill"
  static let expand = "chevron.down"
  static let collapse = "chevron.up"
  static let storeError = "xmark.icloud"
  static let beyondHorizon = "calendar.badge.exclamationmark"
  static let fairWeather = "sun.max"
  static let selected = "checkmark"
  /// The two ways of looking at ONE answer. Never a third glyph for "the list": the browse
  /// button already owns `allPools`, and the segmented control switches between these two.
  static let map = "map"
  static let list = "list.bullet"
  /// The three things a swimmer standing on the pavement actually wants from a pool's screen.
  /// They are ACTIONS, so they are filled glyphs — the app's plain-outline set is for state.
  static let directions = "arrow.triangle.turn.up.right.circle.fill"
  static let call = "phone.fill"
  static let website = "safari.fill"
  /// A pool, on a map.
  static let pin = "mappin.circle.fill"
}

/// The day strip's own colours, kept here with the rest.
///
/// `idle` used to be `TierPast` at 12% — a day chip painted in the colour that means "this
/// session has already finished", for every chip that simply was not selected. Colour is a
/// vocabulary in this app; borrowing a word from it because the shade looked right is how a
/// vocabulary stops meaning anything. `ChipIdle` is a neutral of its own.
enum ChipColor {
  static let selected = Color("ChipSelected")
  static let idle = Color("ChipIdle")
  static let today = Color("ChipToday")
  /// The tint strengths. A TINTED background rather than a filled one, so the label keeps
  /// `.primary` and its contrast stays the system's problem in both appearances.
  static let selectedFill = 0.22
  static let idleFill = 0.12
}

extension Tier {
  /// The tier's accent. Colour is never the ONLY channel: the section heading says the same
  /// thing in words, and the row's glyph says it a third way — which is what
  /// `accessibilityDifferentiateWithoutColor` needs to be true by construction.
  var accent: Color {
    switch self {
    case .now: return Color("TierNow")
    case .soon: return Color("TierSoon")
    case .past: return Color("TierPast")
    case .scheduled: return Color("TierScheduled")
    case .unknown: return Color("TierUnknown")
    case .closed: return Color("TierClosed")
    }
  }

  /// The SF Symbol that carries the same distinction without colour.
  var symbol: String {
    switch self {
    case .now: return "figure.pool.swim"
    case .soon: return "clock"
    case .past: return "moon.zzz"
    // A calendar, not a clock: this tier exists precisely because no clock claim can be made
    // about the day it describes.
    case .scheduled: return "calendar"
    case .unknown: return "questionmark.circle"
    case .closed: return "lock"
    }
  }
}

extension UIMark {
  var accent: Color {
    switch self {
    case .attend: return Color("MarkAttend")
    case .check: return Color("MarkCheck")
    case .no: return Color("MarkNo")
    }
  }

  /// `check` is NEVER merged with `no`: a different glyph, a different colour and a different
  /// sentence, because "we cannot tell" and "you may not" are different answers.
  var symbol: String {
    switch self {
    case .attend: return "checkmark.circle.fill"
    case .check: return "questionmark.circle.fill"
    case .no: return "xmark.circle.fill"
    }
  }
}

extension BannerModel.Kind {
  var accent: Color {
    switch self {
    case .warning: return Color("BannerWarning")
    case .notice: return Color("BannerNotice")
    }
  }

  var symbol: String {
    switch self {
    case .warning: return "exclamationmark.triangle"
    case .notice: return "quote.bubble"
    }
  }
}

/// The colour family, resolved from the Asset Catalog. Inside a `Canvas` a named colour still
/// resolves correctly through `GraphicsContext.environment`, which is why the ribbon can obey
/// dark mode and contrast settings without a single channel value in this file.
func familyColor(_ family: String) -> Color {
  switch family {
  case "public": return Color("FamPublic")
  case "lane": return Color("FamLane")
  case "family": return Color("FamFamily")
  case "women": return Color("FamWomen")
  case "seniors": return Color("FamSeniors")
  case "adults": return Color("FamAdults")
  case "school": return Color("FamSchool")
  case "club": return Color("FamClub")
  case "girls": return Color("FamGirls")
  case "diverse": return Color("FamDiverse")
  case "accompanied": return Color("FamAccompanied")
  case "closed": return Color("FamClosed")
  case "unknown": return Color("FamUnknown")
  // The web maps an unknown access class onto its PUBLIC colour. This does not, deliberately:
  // painting a session nobody has classified in the open-to-all hue is the "looks open to you"
  // lie the whole family vocabulary exists to prevent.
  default: return Color("FamOther")
  }
}
