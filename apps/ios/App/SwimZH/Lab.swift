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
  /// HOW a day chip ARRIVES as the strip is scrolled. A picker: see `StripEntry`. Read as a
  /// `String`, so a test's `-lab.stripEntry none` needs no retyping.
  static let stripEntry = "lab.stripEntry"
  /// WHERE the filter control lives around the tab bar. A picker: see `FilterPlace`.
  static let filterPlace = "lab.filterPlace"
  /// The map's pin card is Liquid Glass rather than a material.
  static let glassCard = "lab.glassCard"
  /// SF Symbol motion: the favourite heart bounces, the filter glyph bounces when narrowed.
  static let symbolMotion = "lab.symbolMotion"
  /// WHERE a web link opens. A picker: the question is how much of the app stays in view
  /// while the reader looks at the pool's own page. See `LinkOpener`.
  static let linkOpener = "lab.linkOpener"

  // THE PERFORMANCE REVIEW'S THREE (2026-09-06). Each answers one complaint with two or three
  // behaviours to feel side by side; none changes what the app knows, only when it moves.

  /// WHEN a row moves after its heart is toggled. A picker: see `FavouriteMove`.
  static let favouriteMove = "lab.favouriteMove"
  /// WHEN the pool screen's map is built: in the pushed screen's first frame, or once the
  /// push has landed. A picker: see `PoolMapArrival`.
  static let poolMapArrival = "lab.poolMapArrival"
  /// The keyboard is loaded once, unseen, after the answer is on screen, so the first tap on
  /// search does not pay UIKit's first-keyboard bill. See `KeyboardWarmup`.
  static let keyboardWarmup = "lab.keyboardWarmup"

  // DECIDED, and deleted as the header says a decided switch must be: `lab.heroExtends` (the
  // pool screen's hero map under the bar) and `lab.heroStage` (that map opening to fill the
  // screen). The owner chose the open map as the pool screen itself — see `PoolStage` — so
  // there is no picture left for either switch to compare.

  /// The BOOLEAN switches — the ones `typeLaunchArguments` retypes. The string pickers are
  /// deliberately not here: `("none" as NSString).boolValue` is `false`, which would turn a
  /// named choice into a `Bool` no reader ever asked for.
  static let keys = [glassCard, symbolMotion, keyboardWarmup]

  /// A boolean switch, read outside a view — `@AppStorage` is for bodies. Absent means ON,
  /// which is the header's rule: a fresh install shows the proposal.
  static func isOn(_ key: String, in defaults: UserDefaults = .standard) -> Bool {
    defaults.object(forKey: key) == nil ? true : defaults.bool(forKey: key)
  }

  /// What happens to a row when its heart is toggled. The complaint: swipe a row to favourite
  /// it mid-list, and the whole list rebuilds with that row sorted to the front of its tier — it
  /// leaves the screen, and every row under it jumps up by its height.
  ///  * `hold` — the heart appears in place and NOTHING moves. The favourites-first order is
  ///    applied the next time the reader is not mid-list: when they scroll back to the top,
  ///    change the day or a filter, or relaunch. The default: a swipe changes one row.
  ///  * `move` — the row moves to the front of its tier at once, as before, but ANIMATED so it
  ///    is seen to slide rather than to vanish. Kept for comparison: the old behaviour minus
  ///    the cut.
  ///  * `never` — favourites never lead. The heart and the favourites-only filter are the
  ///    whole feature; the list stays nearest-first whatever is marked.
  enum FavouriteMove: String, CaseIterable {
    case hold, move, never
    static let `default`: FavouriteMove = .hold

    /// Read outside a view, on each toggle, so a change in Settings applies to the next swipe.
    static func current(in defaults: UserDefaults = .standard) -> FavouriteMove {
      defaults.string(forKey: Lab.favouriteMove).flatMap(FavouriteMove.init) ?? .default
    }
  }

  /// When the pool screen builds its map. The complaint: tapping a row pauses before the push.
  /// SwiftUI must render the destination's FIRST frame before the push can begin, and that
  /// frame held a live `Map` — MapKit's renderer, tiles and the location dot — so the pause
  /// was the map, paid before anything moved.
  ///  * `afterPush` — the screen pushes at once over a plain ground in the launch colour; the
  ///    map is built once the push has landed and fades in. The tap answers immediately, and
  ///    the map arrives a beat later. The default.
  ///  * `withPush` — the map is in the first frame, as before. Nothing fades in, and the tap
  ///    waits for the map.
  enum PoolMapArrival: String, CaseIterable {
    case afterPush, withPush
    static let `default`: PoolMapArrival = .afterPush
  }

  /// How a chip arrives when the strip is scrolled and a new day comes on screen. DECIDED
  /// on the same day the day strip's glass was: the morphing selection stays; what the owner
  /// missed from the discarded system-button variant was the way its glass MATERIALISED as a
  /// new chip scrolled in — the morph's chips simply popped.
  ///  * `materialize` — the chip's glass uses the system's materialize transition, the one a
  ///    `GlassButtonStyle` gets for free: it fades in with the glass ripple. The default. It
  ///    also governs the tap's own glass swap, so a selection change materialises too.
  ///  * `scroll` — a scroll transition instead: a chip entering from either edge scales and
  ///    fades up as it arrives, driven by the scroll itself (the carousel feel of the App Store
  ///    and Photos). Preferable if the materialise is too subtle or fights the morph.
  ///  * `none` — chips pop in, as the morph strip did before. The control.
  enum StripEntry: String, CaseIterable {
    case materialize, scroll, none
    static let `default`: StripEntry = .materialize
  }

  /// Where the filter control sits, now that the find screen's bottom is a system tab bar
  /// (List, Map, Search) rather than a toolbar. Apple's own apps put a control like this in one
  /// of two places, and which one FEELS right is the question:
  ///  * `accessory` — a pill ABOVE the tab bar, the slot Music's mini-player uses
  ///    (`tabViewBottomAccessory`). Always one tap away on every tab; it carries the current
  ///    filter summary, and collapses beside the minimised bar as the list scrolls. The
  ///    default: the filters are the answer's context, and context rides with the bar.
  ///  * `tab` — Filters is a TAB of its own, a page rather than a sheet: List, Map, Filters,
  ///    Search. The bar is pure and every control in it is a tab; the glyph fills when
  ///    something is narrowed. Preferable if the pill reads as clutter over the list.
  enum FilterPlace: String, CaseIterable {
    case accessory, tab
    static let `default`: FilterPlace = .accessory
  }

  /// The four places a pool's web page can open. `external` is what the app shipped with:
  /// `openURL` handed the address to Safari, the app went to the background, and coming back
  /// was a swipe up and a tap on the right card. The three others keep the reader IN the app,
  /// which is what Apple's own apps do (Mail, Messages, News all open links in place) and what
  /// the HIG asks for when the page is a detour, not a destination.
  ///  * `safari` — `SFSafariViewController`, full screen. Safari's engine, Safari's cookies
  ///    and passwords, Reader, content blockers, the reader's own Safari settings; on iOS 26+
  ///    the system draws its bars in Liquid Glass. Done closes it; the app is still where it
  ///    was. The default: the most capable browser and the least code.
  ///  * `sheet` — the same controller as a page sheet. The pool screen stays visible behind
  ///    it, and a pull down closes it — the lightest way to glance at a page and come back.
  ///    Cost: a sheet is shorter than the screen, and the page's own header eats some of it.
  ///  * `web` — SwiftUI's `WebView` (WebKit) inside the app's own navigation stack: our bar,
  ///    our Done, back/forward/reload and share in a bottom bar the system draws in glass, the
  ///    page's title in the bar, a progress line while it loads. Cost: no shared Safari
  ///    cookies or passwords, no Reader, and every control is ours to keep right.
  ///  * `external` — the Safari app, as before. For comparison.
  enum LinkOpener: String, CaseIterable {
    case safari, sheet, web, external
    static let `default`: LinkOpener = .safari
    /// Whether the opener is `SFSafariViewController`, which is the one worth prewarming.
    var usesSafariController: Bool { self == .safari || self == .sheet }
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
