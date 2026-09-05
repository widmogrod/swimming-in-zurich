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
  /// The day strip's chips are Liquid Glass, and the selection morphs from chip to chip.
  static let glassStrip = "lab.glassStrip"
  /// The map's pin card is Liquid Glass rather than a material.
  static let glassCard = "lab.glassCard"
  /// SF Symbol motion: the favourite heart bounces, the filter glyph bounces when narrowed.
  static let symbolMotion = "lab.symbolMotion"

  // DECIDED, and deleted as the header says a decided switch must be: `lab.heroExtends` (the
  // pool screen's hero map under the bar) and `lab.heroStage` (that map opening to fill the
  // screen). The owner chose the open map as the pool screen itself — see `PoolStage` — so
  // there is no picture left for either switch to compare.

  static let keys = [glassStrip, glassCard, symbolMotion]

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
