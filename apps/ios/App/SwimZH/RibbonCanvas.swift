// RibbonCanvas.swift — the day tail: one row's sessions as a ribbon, and the "now" cursor.
//
// TWO OVERLAPPING CANVASES, and the split is structural rather than tidy (S3b acceptance 7).
// A `Canvas` redraws in FULL on every invalidation, so a moving cursor inside the ribbon's
// canvas would repaint 57 ribbons once a minute. Published measurements put a full redraw at
// animation rate around 30% CPU and a static/dynamic split around 6% — a ~5× difference, and
// the reason the cursor is its own thin canvas stacked on top rather than one more thing the
// ribbon draws. (Those are third-party figures: they motivate the structure; they are not
// asserted by it. The CPU check itself is a device measurement at the pause gate.)
//
// `drawingGroup()` appears NOWHERE here. `Canvas` is already Metal-backed, so it would add an
// offscreen render pass and buy nothing; a lint asserts its absence.
//
// A CANVAS HAS ZERO ACCESSIBILITY. Apple states it twice: "A canvas doesn't offer interactivity
// or accessibility for individual elements." So both are ours to build, and both come from the
// package: `a11yBlocks(for:width:)` lays the VoiceOver elements out and `block(at:in:width:)`
// resolves a tap — each through the SAME `TimeAxis` this file draws with. Three consumers, one
// mapping (acceptance 6). A lint asserts every `Canvas` in this target carries
// `accessibilityChildren`.

import SwiftUI
import SwimZHKit

struct RibbonCanvas: View {
  let day: DayRibbon
  /// Whether this row is showing the day the user is standing in. The cursor is a claim about
  /// the present, so it is drawn ONLY on today — the same rule that stops the list from saying
  /// "Open now" about a date four months out.
  let isToday: Bool
  /// The block the reader last tapped, held by the ROW. It carries the whole block rather than
  /// its id, because the point of the hit test is the block's own sentence — an id is a thing
  /// nothing can render, which is what made this tap dead for two slices.
  let selection: Binding<A11yBlock?>
  /// Passed IN rather than read from the environment: the canvas's VoiceOver layout is built
  /// by `a11yBlocks`, which needs the renderer, and a row already holds one.
  let localized: Localized

  @Environment(\.scenePhase) private var scenePhase
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @ScaledMetric(relativeTo: .caption) private var height = 46
  /// The hour labels' row. It SCALES: these were `.system(size: 9)`, the one fixed-size type in
  /// the app, so the only text a reader with large type could not enlarge was the axis that
  /// says what the picture means.
  @ScaledMetric(relativeTo: .caption2) private var labelHeight = 12

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      hourLabels
      plot
    }
  }

  /// The hour labels live in SwiftUI text, not in the canvas: a lane stack fills 0.8 of the
  /// row, leaving about four points of gutter, and no readable type fits there. They are
  /// positioned by `tickFraction`, the same mapping the marks are painted with, so a label can
  /// never sit over the wrong mark.
  private var hourLabels: some View {
    GeometryReader { proxy in
      ForEach(dayTailLabelHours, id: \.self) { hour in
        Text(verbatim: String(format: "%02d", hour))
          .font(.rowNote)
          .monospacedDigit()
          .minimumScaleFactor(0.8)
          .foregroundStyle(.secondary)
          .position(
            x: tickFraction(hour: hour) * proxy.size.width, y: proxy.size.height / 2)
      }
    }
    .frame(height: labelHeight)
    .accessibilityHidden(true)
  }

  private var plot: some View {
    GeometryReader { proxy in
      ZStack(alignment: .topLeading) {
        ribbons
        cursor
      }
      .contentShape(Rectangle())
      // A SPATIAL tap: `onTapGesture` reports no location, and the whole point of the hit test
      // is which block the finger was over. The x is inverted by the same `TimeAxis` the
      // renderer drew with — the third consumer of the one mapping.
      .gesture(
        SpatialTapGesture().onEnded { tap in
          let tapped = block(
            at: tap.location.x, in: day, width: proxy.size.width, localized: localized)
          // Tapping the SAME block again puts the caption away. A selection with no way back
          // is a row that grows once and never shrinks.
          selection.wrappedValue = tapped?.id == selection.wrappedValue?.id ? nil : tapped
        }
      )
      .accessibilityChildren {
        // The canvas's accessibility, built by hand because there is none. Each element is a
        // real view laid out over the block it stands for, so VoiceOver's focus rectangle lands
        // where the ribbon was painted.
        ForEach(a11yBlocks(for: day, width: proxy.size.width, in: localized)) { block in
          Color.clear
            .frame(width: block.width, height: proxy.size.height)
            .position(x: block.x + block.width / 2, y: proxy.size.height / 2)
            .accessibilityLabel(Text(block.label, localized))
            .accessibilityFacts(block, localized)
        }
      }
    }
    .frame(height: height)
    .accessibilityIdentifier("ribbon")
  }

  /// The STATIC half: everything that changes only when the answer does.
  private var ribbons: some View {
    Canvas(opaque: false, rendersAsynchronously: false) { context, size in
      let axis = TimeAxis(width: size.width)
      for ribbon in day.ribbons {
        draw(ribbon, in: &context, axis: axis, size: size)
      }
      // Marks LAST: under an opaque lane band a hairline is invisible, so a mark drawn first
      // simply is not there on the rows that need it most.
      drawTicks(in: &context, axis: axis, size: size)
    }
    .accessibilityChildren {
      // The painted ribbons are described by the overlay above; this canvas itself must not
      // also present them, or VoiceOver would read every block twice.
      EmptyView()
    }
  }

  /// The MOVING half: one hairline, redrawn once a minute and only when it can be seen.
  private var cursor: some View {
    // `.animation(minimumInterval:paused:)` rather than `.everyMinute`: the two schedule at the
    // same rate here, but `.everyMinute` takes NO `paused:` parameter — it is a bare static
    // property — and pausing is the entire point. `paused:` comes from a pure policy in the
    // package, driven across every combination by a test, because whether `TimelineView`
    // self-pauses off-screen or in the background is UNDOCUMENTED, and a CPU budget resting on
    // undocumented behaviour is not a budget.
    TimelineView(
      .animation(
        minimumInterval: 60,
        paused: animationPaused(scenePhase: scenePhase.kind, reduceMotion: reduceMotion))
    ) { timeline in
      Canvas(opaque: false, rendersAsynchronously: false) { context, size in
        guard isToday else { return }
        let axis = TimeAxis(width: size.width)
        let x = axis.x(of: ZurichClock.timeOfDay(of: timeline.date))
        guard x >= 0, x <= size.width else { return }
        context.fill(
          Path(CGRect(x: x - 0.5, y: 0, width: 1, height: size.height)),
          with: .color(Color("CursorNow")))
      }
      .accessibilityChildren {
        // The cursor says "now", which the list already states in words on every row it
        // applies to. A second spoken element for a moving line would be noise.
        EmptyView()
      }
    }
  }

  // MARK: - Painting

  private func draw(
    _ ribbon: Ribbon,
    in context: inout GraphicsContext,
    axis: TimeAxis,
    size: CGSize
  ) {
    switch ribbon.variant {
    case "lanestack": drawStack(ribbon, in: &context, axis: axis, size: size)
    case "lanes": drawLanes(ribbon, in: &context, axis: axis, size: size)
    case "closed", "ghost": drawState(ribbon, in: &context, size: size)
    default: drawUnpublished(ribbon, in: &context, axis: axis, size: size)
    }
  }

  /// The lane stack: one sub-row per lane, public against reserved.
  private func drawStack(
    _ ribbon: Ribbon,
    in context: inout GraphicsContext,
    axis: TimeAxis,
    size: CGSize
  ) {
    let lanes = ribbon.strips ?? []
    guard !lanes.isEmpty else { return }
    let band = size.height * 0.8 / Double(lanes.count)
    let top = size.height * 0.1
    for (index, lane) in lanes.enumerated() {
      for hold in lane.segments {
        guard let window = hold.window else { continue }
        context.opacity = hold.isPublic ? 0.9 : 0.75
        context.fill(
          Path(
            CGRect(
              x: axis.x(of: window.start), y: top + Double(index) * band,
              width: axis.width(of: window), height: max(1, band - 1))),
          with: .color(hold.isPublic ? Color("LanePublic") : Color("LaneReserved")))
      }
    }
    context.opacity = 1
  }

  /// The lane ribbon: thickness is the public fraction about the mid-line, over the faint
  /// full-capacity sheath, pinched wherever a lane is reserved.
  ///
  /// KEPT DELIBERATELY, THOUGH NO ROW IN TODAY'S EXPORT REACHES IT. `optionRibbon` returns the
  /// `lanes` variant only when an option has a `lane_timeline` but NO usable `lane_day_view`,
  /// and `Store.options` derives both from the same `lane_day` row — so the only way in is a
  /// row with `lane_count = 0`, which the export schema permits and no basin currently has
  /// (all six carry 6). The variant is not dead code in the model: it is a faithful port of
  /// `blocks/ribbonmodel.ts`, the golden fixture asserts it, and the web renders it. Deleting
  /// this arm would send such a row to `drawUnpublished` — "split not published" — for a basin
  /// that did publish one, which is the class of lie this whole vocabulary exists to prevent.
  private func drawLanes(
    _ ribbon: Ribbon,
    in context: inout GraphicsContext,
    axis: TimeAxis,
    size: CGSize
  ) {
    let mid = size.height / 2
    let sheath = sheathHalfHeight(height: size.height)
    for segment in ribbon.segments ?? [] {
      guard let window = segment.window else { continue }
      let x = axis.x(of: window.start)
      let width = axis.width(of: window)
      context.opacity = 0.35
      context.fill(
        Path(CGRect(x: x, y: mid - sheath, width: width, height: sheath * 2)),
        with: .color(Color("RibbonSheath")))
      let half = ribbonHalfHeight(
        thickness: segment.thickness, pinched: segment.pinched, height: size.height)
      context.opacity = 0.85
      context.fill(
        Path(
          roundedRect: CGRect(x: x, y: mid - half, width: width, height: half * 2),
          cornerRadius: min(half, 3)),
        with: .color(familyColor(ribbon.family)))
    }
    context.opacity = 1
  }

  /// A pool whose hours are known but whose lane split is not. Its own state — never the
  /// "no lanes free" a pinched-shut ribbon would read as.
  private func drawUnpublished(
    _ ribbon: Ribbon,
    in context: inout GraphicsContext,
    axis: TimeAxis,
    size: CGSize
  ) {
    guard let window = ribbon.window else { return }
    let mid = size.height / 2
    let half = size.height * 0.18
    context.opacity = 0.8
    context.fill(
      Path(
        roundedRect: CGRect(
          x: axis.x(of: window.start), y: mid - half, width: axis.width(of: window),
          height: half * 2),
        cornerRadius: half),
      with: .color(familyColor(ribbon.family)))
    context.opacity = 1
  }

  /// A closed day is DASHED and a schedule-less one is DOTTED — two different states, drawn
  /// two different ways, which is the invariant the four-state vocabulary exists to protect.
  private func drawState(
    _ ribbon: Ribbon,
    in context: inout GraphicsContext,
    size: CGSize
  ) {
    let mid = size.height / 2
    var path = Path()
    path.move(to: CGPoint(x: 0, y: mid))
    path.addLine(to: CGPoint(x: size.width, y: mid))
    let dashes: [CGFloat] = ribbon.style == "dashed" ? [6, 4] : [1.5, 3.5]
    context.stroke(
      path,
      with: .color(familyColor(ribbon.family)),
      style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: dashes))
  }

  private func drawTicks(in context: inout GraphicsContext, axis: TimeAxis, size: CGSize) {
    for hour in dayTailTickHours {
      // Half-point offset: a 1-point rule centred on an integer x straddles two device columns
      // and renders as a 2-point smudge.
      let x = axis.x(ofMinutes: hour * 60).rounded() + 0.5
      context.opacity = 0.5
      context.fill(
        Path(CGRect(x: x, y: 0, width: 1, height: size.height)),
        with: .color(Color("RibbonHair")))
    }
    context.opacity = 1
  }
}

extension RibbonSegment {
  var window: TimeWindow? {
    guard let lower = TimeOfDay(hhmm: start), let upper = TimeOfDay(hhmm: end) else { return nil }
    return TimeWindow(start: lower, end: upper)
  }
}

extension RibbonStackBlock {
  var window: TimeWindow? {
    guard let lower = TimeOfDay(hhmm: start), let upper = TimeOfDay(hhmm: end) else { return nil }
    return TimeWindow(start: lower, end: upper)
  }
}

extension ScenePhase {
  /// SwiftUI's phase, as the package sees it. The kit may not reach for a UI framework at all
  /// (a lint forbids it), so the bridge lives here — the same shape `TypeSizeBridge` uses.
  var kind: ScenePhaseKind {
    switch self {
    case .active: return .active
    case .inactive: return .inactive
    case .background: return .background
    // A phase this SDK adds later is NOT treated as active: pausing an animation we did not
    // expect to be running is harmless, where animating in an unknown state is not.
    @unknown default: return .inactive
    }
  }
}

extension View {
  /// `.accessibilityCustomContent` for each of a block's secondary facts.
  ///
  /// A loop rather than a literal chain because the facts are DATA: how many there are depends
  /// on whether the basin has a lane plan, a best-public window, or an incomplete one — so a
  /// fixed chain of modifiers could not carry them.
  func accessibilityFacts(_ block: A11yBlock, _ localized: Localized) -> some View {
    block.customContent.reduce(AnyView(self)) { view, fact in
      AnyView(
        view.accessibilityCustomContent(
          Text(fact.label, localized), Text(fact.value, localized)))
    }
  }
}
