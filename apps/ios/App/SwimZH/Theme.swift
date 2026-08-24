// Theme.swift — every colour the app draws, resolved from the Asset Catalog.
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

  var voiceOverLabel: String {
    switch self {
    case .attend: return "You may attend"
    case .check: return "Check with the pool"
    case .no: return "Not open to you"
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
