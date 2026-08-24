// TimeAxis.swift — ONE time→x mapping, and the three things that must agree about it.
//
// The plan's S3b acceptance 6, and the reason it is a criterion at all: a `Canvas` gives you no
// hit-testing and no accessibility, so BOTH have to be built by hand — and the moment the
// renderer, the tap handler and the VoiceOver layout each derive their own x from a time, they
// drift, and a tap lands on the wrong session while VoiceOver reads a fourth one. So there is
// one function, `TimeAxis.x(of:)`, and three consumers:
//
//   * `RibbonCanvas` draws with it,
//   * `RibbonCanvas`'s tap gesture inverts it (`block(at:)`),
//   * `a11yBlocks(for:width:)` lays the VoiceOver elements out with it.
//
// The web has the same rule and the same single module (`timescale.js`), and this is its port:
//   X(min) = ((min − lo) / (hi − lo)) · width
//
// THE WINDOW IS [06:00, 22:30], not [06:00, 22:00]. The extra half hour is not slack: a session
// that ends at 22:00 needs somewhere to end, and against a flush right edge it reads as
// "running past the end of the day" rather than as closing. `daytail.ts` made the same choice
// for the same reason, and the two surfaces must agree or the encoding is not shared.

import Foundation

/// The tail's day window, in hours. Shared with `blocks/daytail.ts` (`TAIL_DAY0`/`TAIL_DAY1`).
public let dayTailStartHour = 6.0
public let dayTailEndHour = 22.5

/// The hours the canvas MARKS. The labelled set is every three hours — six labels is what fits
/// a 320-point phone without the `HH:00` texts touching — minus 06:00 itself, because a rule on
/// the plot's left edge paints over the border and reads as a frame rather than as a time.
public let dayTailLabelHours = [6, 9, 12, 15, 18, 21]
public let dayTailTickHours = dayTailLabelHours.filter { $0 != Int(dayTailStartHour) }

/// The linear mapping from a time of day to a position across a plot.
public struct TimeAxis: Equatable, Sendable {
  public let startMinutes: Int
  public let endMinutes: Int
  public let width: Double

  /// A zero or negative width would divide by zero (and a NaN x paints nothing, silently), so
  /// the width is clamped to a positive floor at construction. A row is never really 0 wide,
  /// but SwiftUI hands out a 0-size proposal during layout more often than one expects.
  public init(startHour: Double = dayTailStartHour, endHour: Double = dayTailEndHour, width: Double)
  {
    self.startMinutes = Int(startHour * 60)
    self.endMinutes = Int(endHour * 60)
    self.width = max(1, width)
  }

  public var spanMinutes: Int { max(1, endMinutes - startMinutes) }

  /// Minutes since midnight → x. NOT clamped: a session outside the window is drawn outside the
  /// plot and clipped by the canvas, which is honest, where clamping would pile it against an
  /// edge as if it happened at 22:30.
  public func x(ofMinutes minutes: Int) -> Double {
    (Double(minutes - startMinutes) / Double(spanMinutes)) * width
  }

  public func x(of time: TimeOfDay) -> Double {
    x(ofMinutes: time.minutesSinceMidnight)
  }

  /// The width of `window` on the plot, floored at one point so a very short session is still
  /// visible rather than sub-pixel.
  public func width(of window: TimeWindow) -> Double {
    max(1, x(of: window.end) - x(of: window.start))
  }

  /// x → minutes since midnight. The inverse the tap handler uses.
  ///
  /// ROUNDED, not truncated. `x(of:)` then `minutes(atX:)` on the same time comes back a
  /// fraction of a minute low often enough to matter — 12:59 for 13:00 — and truncation turns
  /// that into a real off-by-one: a tap on the first pixel of a session would land in the gap
  /// before it.
  public func minutes(atX position: Double) -> Int {
    startMinutes + Int(((position / width) * Double(spanMinutes)).rounded())
  }

  public func time(atX position: Double) -> TimeOfDay {
    TimeOfDay(minutesSinceMidnight: min(max(minutes(atX: position), 0), 24 * 60))
  }
}

/// Where an hour sits across the window, as a FRACTION. The labels live in SwiftUI text above
/// the canvas and the marks are painted inside it; both position through this, so a label can
/// never sit over the wrong mark — the width factor cancels, which is also why the strip needs
/// no layout measurement to line up.
public func tickFraction(hour: Int) -> Double {
  TimeAxis(width: 1).x(ofMinutes: hour * 60)
}

// MARK: - The ribbon's own geometry

/// Half-height of a ribbon band, about the row's mid-line.
///
/// `0.4 * height` is full capacity; `thickness` (the public fraction) scales it, and a pinch
/// takes another 28% off wherever any lane is reserved. The pinch is a SECOND, non-colour
/// channel for "someone else is in the water" — which is what makes the encoding survive
/// `accessibilityDifferentiateWithoutColor`. Floored at one point so a fully reserved band is
/// still a line rather than nothing.
public func ribbonHalfHeight(thickness: Double, pinched: Bool, height: Double) -> Double {
  max(1, height * 0.4 * thickness * (pinched ? 0.72 : 1))
}

/// Full-capacity half-height — the faint sheath the thickness is read against. Without it a
/// thin ribbon and a narrow pool look the same.
public func sheathHalfHeight(height: Double) -> Double {
  height * 0.4
}

// MARK: - One row's ribbons

/// Every ribbon for one pool's day, in paint order: statuses first (the background closed and
/// ghost states) and options on top, exactly as `ribbonsFor` orders them for the browser.
public struct DayRibbon: Equatable, Sendable {
  public let poolID: String
  public let poolName: String
  public let ribbons: [Ribbon]

  public init(poolID: String, poolName: String, ribbons: [Ribbon]) {
    self.poolID = poolID
    self.poolName = poolName
    self.ribbons = ribbons
  }
}

/// The ribbons for one list row: one per session, or one for the row's ghost/closed state.
///
/// A row is either sessions OR a state — `listModel` builds it that way — so exactly one of the
/// two loops below ever produces anything.
public func dayRibbon(for row: PoolRow) -> DayRibbon {
  var ribbons: [Ribbon] = []
  if let state = row.state {
    ribbons.append(statusRibbon(state.ribbonInput(facility: row.poolName)))
  }
  ribbons += row.options.map { optionRibbon($0.ribbonInput) }
  return DayRibbon(poolID: row.poolID, poolName: row.poolName, ribbons: ribbons)
}

extension SwimOption {
  /// This option as the ribbon model reads it — the app's path into the same function the
  /// golden fixture drives from a `/swim` payload.
  public var ribbonInput: RibbonOptionInput {
    RibbonOptionInput(
      access: access.kind,
      start: window.start.hhmm,
      end: window.end.hhmm,
      facility: poolName,
      basin: basinName,
      laneTimeline: laneTimeline.map(RibbonTimelineInput.init(timeline:)),
      laneDayView: laneDayView.map(RibbonDayViewInput.init(day:)),
      laneBestPublic: laneBestPublic.map(RibbonPublicWindow.init(window:))
    )
  }
}

extension DayState {
  /// The state as a status ribbon's input. `detail` carries the pool's own words when it has
  /// any, which is what keeps an unmapped closure from rendering as a bare "closed".
  func ribbonInput(facility: String) -> RibbonStatusInput {
    RibbonStatusInput(
      facility: facility,
      status: isClosureClaim ? "closed" : "unknown",
      detail: dayStateLabel(self)
    )
  }
}

extension RibbonTimelineInput {
  init(timeline: LaneTimeline) {
    self.init(
      segments: timeline.segments.map { slot in
        Segment(
          start: slot.window.start.hhmm,
          end: slot.window.end.hhmm,
          laneCount: slot.availability.laneCount,
          publicLanes: slot.availability.publicLanes,
          reservedLanes: slot.availability.reservedLanes,
          partial: slot.availability.partial
        )
      })
  }
}

extension RibbonDayViewInput {
  init(day: LaneDay) {
    self.init(
      weekday: day.weekday,
      laneCount: day.laneCount,
      strips: day.strips.map { strip in
        Strip(
          lane: strip.lane,
          segments: strip.holds.map { hold in
            Segment(
              start: hold.window.start.hhmm,
              end: hold.window.end.hhmm,
              access: hold.accessKind,
              owner: hold.owner
            )
          })
      })
  }
}

extension RibbonPublicWindow {
  init(window: PublicWindow) {
    self.init(
      start: window.window.start.hhmm,
      end: window.window.end.hhmm,
      publicLanes: window.publicLanes
    )
  }
}

// MARK: - Accessibility

/// One secondary fact, read by VoiceOver on request rather than in the main label.
public struct A11yFact: Equatable, Sendable {
  public let label: String
  public let value: String
}

/// One VoiceOver element standing in for one painted block.
///
/// `Canvas` offers NO accessibility for individual elements — Apple states it twice — so
/// without these a ribbon is one opaque rectangle to a screen reader. `x`/`width` are in the
/// canvas's own coordinates; the view turns them into frames.
public struct A11yBlock: Equatable, Sendable, Identifiable {
  public let id: String
  public let x: Double
  public let width: Double
  public let label: String
  public let customContent: [A11yFact]
}

/// The VoiceOver layout for one row's ribbons — one element per painted block, positioned by
/// the SAME axis the renderer draws with.
///
/// EVERY LABEL HERE IS DAY-AGNOSTIC. A ribbon is painted for whichever day the strip selects,
/// and the strip spans the whole horizon, so a sentence containing "today" or "now" would be
/// read out on ninety-odd future dates. That bug has already been found twice in this app (see
/// the plan's S3a notes); `a11yLabelsAreDayAgnostic` pins it here.
public func a11yBlocks(for day: DayRibbon, width: Double) -> [A11yBlock] {
  let axis = TimeAxis(width: width)
  return day.ribbons.enumerated().map { index, ribbon in
    let span = ribbon.window
    return A11yBlock(
      id: "\(day.poolID)|\(index)",
      // A ribbon with no window is a whole-day state (closed, or hours unknown), so its
      // element spans the whole plot: there is no narrower thing for it to point at.
      x: span.map { axis.x(of: $0.start) } ?? 0,
      width: span.map { axis.width(of: $0) } ?? axis.width,
      label: a11yLabel(for: ribbon),
      customContent: a11yFacts(for: ribbon)
    )
  }
}

/// The block's spoken headline: when, and what kind of session.
func a11yLabel(for ribbon: Ribbon) -> String {
  guard let window = ribbon.window else {
    // A status ribbon already carries the state's own sentence, which `dayStateLabel` wrote
    // and `stateLabelsAreDayAgnostic` polices.
    return ribbon.detail ?? "Hours not listed"
  }
  let hours = "\(window.start.hhmm) to \(window.end.hhmm)"
  return "\(hours), \(accessDescription(ribbon.access))"
}

/// The secondary facts. `.accessibilityCustomContent` reads these on request, which is what
/// keeps the headline short enough to scan by ear while nothing is dropped.
func a11yFacts(for ribbon: Ribbon) -> [A11yFact] {
  var facts: [A11yFact] = []
  if let basin = ribbon.basin, !basin.isEmpty {
    facts.append(A11yFact(label: "Basin", value: basin))
  }
  if let segments = ribbon.segments, let first = segments.first {
    facts.append(
      A11yFact(
        label: "Lanes open to the public",
        value: "\(first.publicLanes) of \(first.laneCount)"))
    if first.partial == true {
      facts.append(A11yFact(label: "Lane data", value: "incomplete for this basin"))
    }
  }
  if let stack = ribbon.strips {
    facts.append(A11yFact(label: "Lanes", value: "\(stack.count)"))
    let owners = stack.flatMap { $0.segments.compactMap(\.owner) }
    if let owner = owners.first {
      facts.append(
        A11yFact(
          label: "Reserved by",
          value: Set(owners).count > 1 ? "\(owner) and others" : owner))
    }
  }
  if let best = ribbon.bestPublic {
    facts.append(
      A11yFact(
        label: "Most lanes free",
        value: "\(best.start) to \(best.end), \(best.publicLanes) lanes"))
  }
  if ribbon.variant == "unpublished" {
    facts.append(A11yFact(label: "Lane split", value: "not published for this pool"))
  }
  return facts
}

/// A spoken name for an access class. Never "open" for an arm this binary does not know: an
/// unheard-of class is a reason to say "check with the pool", exactly as `eligibility` does.
func accessDescription(_ access: String?) -> String {
  switch access {
  case "PublicSwim": return "Public swimming"
  case "LaneSwim": return "Lane swimming"
  case "FamilyTime": return "Family time"
  case "WomenOnly": return "Women only"
  case "SeniorsOnly": return "Seniors only"
  case "AdultsOnly": return "Adults only"
  case "SchoolReserved": return "Reserved for schools"
  case "ClubReserved": return "Reserved for a club"
  case "GirlsOnly": return "Girls only"
  case "GenderDiverse": return "Gender-diverse session"
  case "AccompaniedChildren": return "Accompanied children"
  default: return "Session — check with the pool"
  }
}

// MARK: - Hit testing

/// Which block a tap at `position` selects — the third consumer of the one axis.
///
/// THE TIE RULE, and it is a rule rather than an accident: the NARROWEST block containing the
/// point wins, and among equals the LAST in paint order. Narrowest first because a short
/// session drawn over a long one is the specific thing the tap is aiming at; last-in-paint
/// order because that is the block on top, which is what the finger is actually touching. Two
/// blocks with the same span are genuinely indistinguishable by x alone — two basins with
/// identical hours — so the rule picks the one drawn last rather than pretending otherwise.
public func block(at position: Double, in day: DayRibbon, width: Double) -> A11yBlock? {
  let blocks = a11yBlocks(for: day, width: width)
  var best: A11yBlock?
  for candidate in blocks
  where candidate.x <= position && position < candidate.x + candidate.width {
    if let current = best, current.width < candidate.width { continue }
    best = candidate
  }
  return best
}

// MARK: - The animation policy

/// The scene phases the app can be in, as the KIT sees them. The kit may not reach for the
/// SwiftUI framework at all (a lint forbids it), so the app bridges `ScenePhase` onto this —
/// the same shape `TypeSizeBridge` already uses for `DynamicTypeSize`.
public enum ScenePhaseKind: String, CaseIterable, Equatable, Sendable {
  case active
  case inactive
  case background
}

/// Whether the "now" cursor's `TimelineView` should be PAUSED.
///
/// Two reasons, and neither is optional. Reduced motion is an accessibility setting: a line
/// creeping across the screen once a minute is exactly the kind of unrequested movement it
/// turns off. And a scene that is not active must not schedule redraws — whether `TimelineView`
/// self-pauses off-screen or in the background is UNDOCUMENTED, and a CPU budget resting on
/// undocumented behaviour is not a budget. So the policy is explicit, pure, and driven across
/// every combination by a test.
public func animationPaused(scenePhase: ScenePhaseKind, reduceMotion: Bool) -> Bool {
  scenePhase != .active || reduceMotion
}
