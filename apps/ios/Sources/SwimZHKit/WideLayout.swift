// WideLayout.swift — the numbers behind the wide-window (unfolded) layouts.
//
// The app decides WHETHER a window is wide from its size class — a SwiftUI fact the kit cannot
// see. What it lays out once it is wide is arithmetic, and arithmetic in a `body` is a rule
// nothing measures, so the widths live here where a test can state them.

import Foundation

/// The narrowest a list column may be and still hold a pool row's name, verdict and ribbon
/// without wrapping the verdict — the phone's own narrowest width.
public let listColumnMinimumWidth: Double = 320
/// The widest a list column is worth: past this a row's ribbon stretches into a bar with nothing
/// more to say, and the map beside it is what the extra width is for.
public let listColumnMaximumWidth: Double = 440
/// The share of a wide window the list column takes between those two bounds. Under half, so
/// the map — the reason the window's width is worth having — is always the larger part.
public let listColumnShare: Double = 0.44

/// How tall the filters popover is: the whole form — three sections and their headers — at
/// the default text size, so opening it never opens onto a scroll.
public let formPopoverHeight: Double = 560

/// How wide the list column is in a window `windowWidth` points wide.
///
/// The STAGE layout's floating column. One answer to "how much of the screen is list", so a
/// change of window — a fold, a Split View drag — changes the map's share and not the list's
/// legibility.
public func listColumnWidth(in windowWidth: Double) -> Double {
  min(listColumnMaximumWidth, max(listColumnMinimumWidth, windowWidth * listColumnShare))
}

// MARK: - The column's own gestures: which side it is on

/// The column's three rests are `Detent` under `DetentScale.column` — the phone drawer's own
/// rules (`detentVisibleHeight`, `detentLanding`), anchored to the BOTTOM of the window with the
/// content laid out once at full height, so a shorter column shows the TOP of the list — the day
/// strip, the headline — and gives the rest of its height back to the map.

/// Which edge of the window the column sits against.
public enum ColumnSide: Sendable, Equatable {
  case leading, trailing
}

/// Where a lifted finger leaves the column: on the side its CENTRE was headed for. The centre
/// after the projected drag is compared with the window's middle, so a flick across the screen
/// changes side and a nudge that stays on its own half does not, however long it was.
public func columnSide(
  from side: ColumnSide, projectedDrag: Double, columnWidth: Double, margin: Double,
  in windowWidth: Double
) -> ColumnSide {
  let restingCentre =
    switch side {
    case .leading: margin + columnWidth / 2
    case .trailing: windowWidth - margin - columnWidth / 2
    }
  return restingCentre + projectedDrag < windowWidth / 2 ? .leading : .trailing
}

// MARK: - The column's controls, hidden until pulled for

/// How far past its top the list must be pulled before the column's search row appears — a
/// deliberate pull, well clear of the bounce a scroll to the top ends in.
public let columnControlsPull: Double = 40
/// How far INTO the list a scroll must go before the row hides again. Past zero, not at it: a
/// pull lets go and settles at zero, and the row it revealed must survive that settling.
public let columnControlsHideBeyond: Double = 8

/// Whether the column's search row is on screen. Hidden by default — the card opens on the
/// day strip and the rows, with no chrome above them ("there is still negative space; make
/// search hidden, and only shown when the user pulls down") — revealed by a pull past the top,
/// and put away again by scrolling on into the list. `pinned` holds it: while the field has
/// focus or a query, the list may move under it and the row must not vanish mid-word.
public func columnControlsShouldShow(scrolled: Double, showing: Bool, pinned: Bool) -> Bool {
  if pinned { return true }
  if scrolled < -columnControlsPull { return true }
  if scrolled > columnControlsHideBeyond { return false }
  return showing
}
