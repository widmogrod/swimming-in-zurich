// LaneGanttView.swift — the expanded per-lane Gantt, and the ONE place Swift Charts is used.
//
// WHY CHARTS HERE AND CANVAS THERE (S3b acceptance 8). Charts gives per-mark VoiceOver for
// free and documents `BarMark(xStart:xEnd:y:)` for exactly this shape. But there are credible
// reports of 100% CPU and 50–150 ms hangs at 500–2000 points, and 57 live charts inside a
// `List` is precisely that shape. So the 57 ribbons stay `Canvas` and pay for their
// accessibility explicitly (`a11yBlocks`), while the Gantt — built ONE AT A TIME, only for the
// row the user expanded, and off the scrolling path — takes the free version.
//
// "One at a time" is enforced by where this view is used, not by hope: `PoolRowView` builds it
// only inside its expanded branch, and `TodayModel` keeps a SINGLE expanded row id, so
// expanding a second row collapses the first. A lint asserts `Chart` appears in this file only.
//
// The x axis is MINUTES since midnight, not `Date`. A `Date` axis would drag in a calendar and
// a locale to answer "where does 09:00 go", which is the mapping `TimeAxis` already owns — and
// the two disagreeing by an hour across a DST boundary is a real failure mode. The domain is
// the same [06:00, 22:30] window the ribbon uses, so a bar here sits under the ribbon block it
// expands.

import Charts
import SwiftUI
import SwimZHKit

/// One drawable hold, flattened for Charts.
struct GanttBar: Identifiable {
  let id: String
  let lane: String
  let start: Double
  let end: Double
  let isPublic: Bool
  /// What VoiceOver reads for this mark — composed in `SwimZHKit`
  /// (`LaneHold.spoken(lane:in:)`), where `a11yLabelsAreDayAgnostic` polices it in all five
  /// languages. The panel is reachable from any date in the horizon, so a sentence saying
  /// "today" would be read out on ninety-odd of them.
  let spoken: Message
}

struct LaneGanttView: View {
  @Environment(\.localized) private var localized
  let panel: LanePanel

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      header
      chart
      caveat
    }
    .padding(.top, 4)
  }

  private var header: some View {
    Text(Message("gantt.title"), localized)
      .font(.caption.weight(.semibold))
      .foregroundStyle(.secondary)
  }

  private var chart: some View {
    Chart(bars) { bar in
      BarMark(
        xStart: .value("From", bar.start),
        xEnd: .value("To", bar.end),
        y: .value("Lane", bar.lane),
        height: .fixed(10)
      )
      .foregroundStyle(bar.isPublic ? Color("LanePublic") : Color("LaneReserved"))
      .cornerRadius(2)
      // Charts' free per-mark accessibility — the reason this one view is a chart at all.
      .accessibilityLabel(Text(bar.spoken, localized))
    }
    .chartXScale(domain: Double(dayTailStartHour * 60)...Double(dayTailEndHour * 60))
    .chartXAxis { xAxis }
    .chartYAxis { yAxis }
    .chartLegend(.hidden)
    .frame(height: chartHeight)
  }

  private var xAxis: some AxisContent {
    AxisMarks(values: dayTailLabelHours.map { Double($0 * 60) }) { value in
      AxisGridLine()
      AxisValueLabel {
        Text(verbatim: hourLabel(value.as(Double.self)))
          .font(.caption2)
          .monospacedDigit()
      }
    }
  }

  private var yAxis: some AxisContent {
    AxisMarks(preset: .aligned, position: .leading) { _ in
      AxisValueLabel().font(.caption2)
    }
  }

  /// The lane rows, tallest-first so the chart does not collapse to nothing on a one-lane
  /// basin and does not fill the screen on an eight-lane one.
  private var chartHeight: Double {
    min(220, max(60, Double(panel.day.laneCount) * 22 + 24))
  }

  private var bars: [GanttBar] {
    panel.day.strips.flatMap { strip in
      strip.holds.map { hold in
        GanttBar(
          id: "\(strip.lane)|\(hold.window.start.hhmm)|\(hold.window.end.hhmm)",
          lane: localized(Message("gantt.lane", ["lane": localized.format.integer(strip.lane)])),
          start: Double(hold.window.start.minutesSinceMidnight),
          end: Double(hold.window.end.minutesSinceMidnight),
          isPublic: hold.isPublic,
          spoken: hold.spoken(lane: strip.lane, in: localized))
      }
    }
  }

  /// A lane the plan could not read is stated, never quietly drawn as empty.
  ///
  /// Both the TOKEN and the SENTENCE are the package's (`LaneDay.incompleteLanesCaveat`). They
  /// were written here as well, and the two copies had opposite polarities — this asked
  /// `confidence != "complete"` while the detail sheet asked `== "partial"` — so a token that
  /// was neither made the sheet stay silent while this shouted, about one basin.
  @ViewBuilder
  private var caveat: some View {
    if let sentence = panel.day.incompleteLanesCaveat {
      Text(sentence, localized)
        .font(.caption2)
        .foregroundStyle(.secondary)
    }
  }

  private func hourLabel(_ minutes: Double?) -> String {
    guard let minutes else { return "" }
    return TimeOfDay(minutesSinceMidnight: Int(minutes)).hhmm
  }
}
