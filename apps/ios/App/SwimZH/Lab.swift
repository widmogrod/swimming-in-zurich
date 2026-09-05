// Lab.swift — the switches for the iOS 27 Liquid Glass experiments.
//
// Each switch is a `UserDefaults` key read through `@AppStorage`, so a view re-renders the
// moment it flips. The reader flips it in the SYSTEM Settings app (`Settings.bundle` ships the
// toggles under SwimZH) or a test launches with `-lab.glassStrip NO`. Nothing in the app draws
// a settings screen of its own: that would need five languages of copy for a control that
// exists only until one variant is chosen, and the review is the place to choose.
//
// Every switch defaults to the NEW variant, so a fresh install shows the proposal and the
// old look is one toggle away for comparison. When a variant is decided, delete its key, its
// `Settings.bundle` row and the branch it guarded — a flag left behind is a second code path
// nothing measures.

import SwiftUI

enum Lab {
  /// HOW the day strip's chips are drawn — a PICKER, not a switch, because the question is not
  /// "glass or flat" but which of three glass behaviours feels right under a finger. See
  /// `StripStyle`. Read as a `String`, so a test's `-lab.stripStyle flat` needs no retyping.
  static let stripStyle = "lab.stripStyle"
  /// HOW the find screen's bottom bar is built. A picker, like `stripStyle`, and for the same
  /// reason: the press-and-drag feel of the bar is the thing under review. See `BottomBar`.
  static let bottomBar = "lab.bottomBar"
  /// The map's pin card is Liquid Glass rather than a material.
  static let glassCard = "lab.glassCard"
  /// SF Symbol motion: the favourite heart bounces, the filter glyph bounces when narrowed.
  static let symbolMotion = "lab.symbolMotion"

  // DECIDED, and deleted as the header says a decided switch must be: `lab.heroExtends` (the
  // pool screen's hero map under the bar) and `lab.heroStage` (that map opening to fill the
  // screen). The owner chose the open map as the pool screen itself — see `PoolStage` — so
  // there is no picture left for either switch to compare.

  /// The BOOLEAN switches — the ones `typeLaunchArguments` retypes. `stripStyle` is a string
  /// and is deliberately not here: `"flat" as NSString).boolValue` is `false`, which would turn
  /// a named style into a `Bool` no reader ever asked for.
  static let keys = [glassCard, symbolMotion]

  /// The three bottom bars. The reader's complaint was that the bar's controls do not press
  /// and drag like Apple's own in iOS 27: the list/map segmented picker draws a flat thumb
  /// inside the bar's glass, which is glass over glass and the one control on the screen with
  /// no lens.
  ///  * `toolbar` — the bar as shipped: system bottom toolbar, search + segmented picker +
  ///    two buttons. The default, because every driven test pins this bar's contract.
  ///  * `toggle` — the same toolbar, but list/map is ONE glass button whose glyph swaps (the
  ///    Maps pattern). Every control in the bar is then the same kind of button with the same
  ///    press. Cost: a changing glyph says where you would go, not where you are.
  ///  * `tabs` — a system tab bar: Find, Map, All pools, and a search tab. The selection is
  ///    the tab bar's own glass lens, which slides and can be dragged across tabs — Apple's
  ///    iOS 26/27 interaction exactly. The filter rides above it as the bottom accessory, and
  ///    the bar minimises as the list scrolls down.
  enum BottomBar: String, CaseIterable {
    case toolbar, toggle, tabs
    static let `default`: BottomBar = .toolbar
  }

  /// The four ways the day strip can draw its chips. `flat` is the look the app shipped with;
  /// the three others are Liquid Glass and differ ONLY in what a tap does, which is the thing
  /// a reader has to feel rather than read about:
  ///  * `morph` — the selected tint is its own glass view that flies chip to chip. Every tap
  ///    also swaps the tapped chip's own glass OFF and the old chip's ON, so three glass
  ///    transitions run at once. The press lens never shows: the selected chip has no glass.
  ///  * `tint` — every chip is the SAME interactive glass, always; the selected one is tinted.
  ///    A tap cross-fades the tint and nothing else. The lens works on every chip, because the
  ///    glass under the finger never goes away. The default.
  ///  * `button` — the system's own `GlassButtonStyle`, which is what Apple's bars use. Same
  ///    tint rule as `tint`. The system decides padding and press feel; the chips come out a
  ///    little wider than the layout asked for.
  enum StripStyle: String, CaseIterable {
    case flat, morph, tint, button
    static let `default`: StripStyle = .tint
    var isGlass: Bool { self != .flat }
  }

  /// Make a launch argument count. `-lab.glassStrip NO` lands in the defaults' ARGUMENT domain
  /// as the STRING "NO", and `@AppStorage<Bool>` reads an object that is not a `Bool` as
  /// absent — so every test that switched a lab off was photographing it on, and both
  /// screenshot sets came out identical. The value is rewritten as a real `Bool` in the same
  /// VOLATILE domain: it still wins on read, and it is still never persisted, so a run with
  /// the switches off cannot leave the next launch off.
  static func typeLaunchArguments(in defaults: UserDefaults = .standard) {
    var arguments = defaults.volatileDomain(forName: UserDefaults.argumentDomain)
    for key in keys {
      if let text = arguments[key] as? String {
        arguments[key] = (text as NSString).boolValue
      }
    }
    defaults.setVolatileDomain(arguments, forName: UserDefaults.argumentDomain)
  }
}
