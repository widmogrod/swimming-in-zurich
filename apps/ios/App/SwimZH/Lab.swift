// Lab.swift — the switches for the wide-screen (unfolded) layout review.
//
// The pattern is the one the iOS 27 Liquid Glass review used and then deleted once every switch
// was decided: a `UserDefaults` key read through `@AppStorage`, so a view re-renders the moment
// it changes; the reader picks in the SYSTEM Settings app (`Settings.bundle`, under SwimZH), and
// a test launches with `-lab.wideLayout phone`. Nothing in the app draws a settings screen of its
// own — that would need five languages of copy for a control that exists only until one variant
// is chosen.
//
// WHAT "WIDE" MEANS HERE. Apple ships no fold API in the iOS 27 SDK (checked: nothing in the
// SwiftUI or UIKit interfaces names a hinge, a fold or a posture). What an unfolded phone will
// report is what every wide window reports today: a REGULAR horizontal size class. So the app
// keys its layout off the size class and nothing else — never the device idiom, never a screen
// size — and the same code is what an iPad, a Split View window and an unfolded phone all get.
// When the phone folds mid-session the size class flips and the layout follows, keeping the
// pushed screen (see `TodayView.contentPath`).
//
// A SPLIT layout — the list in a system sidebar, the map in the detail column, a tapped pool
// pushed over the map as the phone's pool screen — was built first and deleted on 2026-09-06
// after the owner saw it: the sidebar was not a floating glass surface while the pin card over
// the map was, and a tap opened a second map over the first instead of moving the one already
// there. The stage is what they asked for instead.
//
// When a variant is decided, delete the key, the `Settings.bundle` row and the losing branches —
// a flag left behind is a second code path nothing measures.

import SwiftUI
import SwimZHKit

enum Lab {
  /// How the find screen uses a regular-width window. A picker: see `WideLayout`.
  static let wideLayout = "lab.wideLayout"
  /// How far the map flies in when a pool is opened on the stage. A picker: see `WideFocus`.
  static let wideFocus = "lab.wideFocus"
  /// Where search and the filters live in a wide window. A picker: see `WideChrome`.
  static let wideChrome = "lab.wideChrome"

  /// The two ways a wide window can be laid out. Identical to one another — and to today's
  /// app — in a compact window: every difference below is gated on the size class.
  ///  * `stage` — the map IS the screen, edge to edge, and the list floats over its leading
  ///    side as a glass card. A tapped pool's facts take the card and the map flies to the
  ///    pool, its neighbours' pins still on it; the map's own pin card opens the same facts in
  ///    the same card. Apple Maps on iPad. The default. The Map tab is gone because the map
  ///    is always there.
  ///  * `phone` — the phone layout, stretched. The control: what the app does with no wide
  ///    code at all, so the stage can be judged against it under the same conditions.
  enum WideLayout: String, CaseIterable {
    case stage, phone
    static let `default`: WideLayout = .stage
  }

  /// Where the stage's controls are. The system draws a regular-width `TabView` as a bar
  /// floating at the TOP CENTRE of the window, which is exactly where the stage's column wants
  /// to be — "list and filters are in the centre and take the sidebar's space" (owner,
  /// 2026-09-06). There is no API to move that bar, so the choice is whether to have it.
  ///  * `column` — no tab bar in a wide window. The column's own bar holds the search field
  ///    and a Filters button; the filters open as a POPOVER from that button, sized as a form
  ///    and not as a screen. The card reaches the top of the window. Apple Maps' card on iPad.
  ///    The default.
  ///  * `tabs` — the system tab bar, as a phone has it: List, Filters, Search. The control.
  ///    Its filter page is narrowed to a form's width so it no longer stretches across an
  ///    iPad; the bar itself still sits over the column's top.
  enum WideChrome: String, CaseIterable {
    case column, tabs
    static let `default`: WideChrome = .column
  }

  /// How close the stage's map goes when a pool is opened.
  ///  * `neighbourhood` — the answer's own minimum span (1.5 km), centred on the pool: the
  ///    pool is plainly the one meant, and the pools around it stay on the map to compare.
  ///    The default, and what the owner asked for ("keep showing other pools' pins").
  ///  * `pool` — the phone's pool-screen span (700 m): the block, the entrance, the stops.
  ///    Closer, at the cost of the neighbours.
  enum WideFocus: String, CaseIterable {
    case neighbourhood, pool
    static let `default`: WideFocus = .neighbourhood

    var spanMetres: Double {
      switch self {
      case .neighbourhood: return minimumMapSpanMetres
      case .pool: return poolMapSpanMetres
      }
    }
  }
}
