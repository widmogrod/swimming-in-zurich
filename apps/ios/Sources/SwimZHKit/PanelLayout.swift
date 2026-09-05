// PanelLayout.swift — the rules behind the pool screen's facts panel.
//
// The pool screen is a map with the facts in a panel over its lower part. The panel has three
// resting heights and is dragged between them; this file decides the heights, how a drag past
// either end is softened, and which height a lifted finger lands on. The view owns the gesture
// and the drawing; the DECISIONS live here, where a test can state them.
//
// WHY NOT THE SYSTEM SHEET. The first version presented the facts as a `.sheet` with detents,
// and the driven app found three things wrong with it: dismissed together with the screen, the
// sheet lingered over the list for the length of its own animation after the pop had finished;
// at its largest size it stopped being glass and went opaque (black, in dark mode); and it had
// to be presented, which meant nothing could show until the screen had something to present.
// A panel that is part of the screen pops with it, looks the same at every height, and can
// stand on the map with the pool's name while the facts are still loading.

import Foundation

/// The three heights the panel rests at, as fractions of the screen it sits in.
///
/// `peek` shows the pool's name, its answer and its actions and leaves the map the point of the
/// screen; `half` shows the first facts; `tall` is for reading, and leaves a band of map at the
/// top so the screen never stops being a map.
public enum PanelDetent: CaseIterable, Sendable, Equatable {
  case peek
  case half
  case tall

  public var fraction: Double {
    switch self {
    case .peek: return 0.36
    case .half: return 0.55
    case .tall: return 0.9
    }
  }

  /// The panel's height at this rest, on a screen `total` points tall.
  public func height(in total: Double) -> Double {
    total * fraction
  }
}

/// How far past its lowest or highest rest the panel may be dragged, as a share of the excess:
/// a finger that drags 100 points past the end moves the panel 25. The panel follows the finger
/// enough to feel held and little enough to say "this is the end".
public let panelOverdragShare: Double = 0.25

/// The panel's visible height during a drag.
///
/// `resting` is the height of the detent the drag started from; `drag` is the finger's vertical
/// travel, positive DOWNWARD (so a downward drag shrinks the panel). Between the lowest and the
/// highest rest the panel follows the finger exactly; beyond either it follows at
/// `panelOverdragShare`, so it can never be dragged off the screen or over the top of it.
public func panelVisibleHeight(resting: Double, drag: Double, in total: Double) -> Double {
  let floor = PanelDetent.peek.height(in: total)
  let ceiling = PanelDetent.tall.height(in: total)
  let wanted = resting - drag
  if wanted > ceiling { return ceiling + (wanted - ceiling) * panelOverdragShare }
  if wanted < floor { return floor - (floor - wanted) * panelOverdragShare }
  return wanted
}

/// The rest a lifted finger lands the panel on: the detent nearest to where the drag was HEADED,
/// not where it was — `projectedDrag` is the finger's travel extrapolated by its velocity, the
/// way the scroll view's own deceleration would carry it. A quick flick therefore skips a rest
/// the finger never reached, which is what a flick means.
public func panelDetent(
  from detent: PanelDetent, projectedDrag: Double, in total: Double
) -> PanelDetent {
  let wanted = detent.height(in: total) - projectedDrag
  return PanelDetent.allCases.min {
    abs($0.height(in: total) - wanted) < abs($1.height(in: total) - wanted)
  } ?? detent
}

/// How far below the lowest rest a drag must be HEADED before letting go leaves the screen.
///
/// The drawer is the way out as well as the way in: pulled down from its smallest size and let
/// go past this, the pool screen goes back to the list, the way a place card in Maps does. The
/// distance is a finger's, not the panel's (the panel follows only a quarter of it down there),
/// and is well clear of the wobble of a drag that merely meant "back to the smallest".
public let panelDismissBeyond: Double = 120

/// What letting go does: settle on a rest, or leave the screen.
public enum PanelRelease: Equatable, Sendable {
  case settle(PanelDetent)
  case dismiss
}

/// Where a lifted finger leaves the panel. `dismiss` only from the LOWEST rest, and only when
/// the drag was headed further than `panelDismissBeyond` below it; otherwise the nearest rest,
/// as `panelDetent`. Two pulls to leave, never one: a big pull from higher up lands on the
/// smallest size and stops there, so a reader closing the facts to see the map cannot overshoot
/// out of the screen — "to the minimal size first, then to the list when pulled further".
public func panelRelease(
  from detent: PanelDetent, projectedDrag: Double, in total: Double
) -> PanelRelease {
  let wanted = detent.height(in: total) - projectedDrag
  if detent == .peek, wanted < PanelDetent.peek.height(in: total) - panelDismissBeyond {
    return .dismiss
  }
  return .settle(panelDetent(from: detent, projectedDrag: projectedDrag, in: total))
}

/// How far the facts list must be pulled past its top, at the tallest rest, before letting go
/// brings the panel down a step. Larger than a bounce, smaller than a deliberate pull.
public let panelCollapsePull: Double = 60

/// Whether a pull past the top of the facts list, now released, steps the panel down.
public func panelCollapses(listPull: Double) -> Bool {
  listPull >= panelCollapsePull
}
