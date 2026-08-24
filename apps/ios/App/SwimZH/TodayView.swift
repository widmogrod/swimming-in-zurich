// The walking skeleton's one screen: today's real options, from the bundled store.
//
// S3a builds the actual phone UI (filters, day strip, ribbons). This exists to prove the
// end-to-end path — bundle -> actor -> answer -> pixels — with no network anywhere, which
// is the property the whole plan rests on.
//
// Two decisions here are already the plan's, not placeholders:
//  * `List`, not `LazyVStack` — for `.swipeActions` and system row/section styling later.
//  * a pool with NO sessions is rendered as its own honest state, never as "closed". The
//    four-state vocabulary (closed / awaiting_scrape / no_source / open_unscheduled) is
//    what protects a pool whose schedule is UNKNOWN from being reported shut.
//
// Strings are English literals for now. S4 fills `Localizable.xcstrings` in the PACKAGE and
// the lint it brings will catch anything left behind here.

import SwiftUI
import SwimZHKit

struct TodayView: View {
  @State private var model = TodayModel()

  var body: some View {
    NavigationStack {
      content
        .navigationTitle("Today")
    }
    .task { await model.load() }
  }

  @ViewBuilder
  private var content: some View {
    switch model.state {
    case .loading:
      ProgressView()
    case .failed(let message):
      ContentUnavailableView(
        "Cannot read the pool data", systemImage: "xmark.icloud", description: Text(message)
      )
      // The launch is over even though there is no data: leaving the extended measurement
      // open would never end it, and every failed launch would silently poison the field
      // numbers rather than showing up as a slow one.
      .onAppear { LaunchSignpost.shared.dataOnScreen() }
    case .ready(let answer, let metadata):
      answerList(answer, metadata)
        // Here, and nowhere earlier: this is the first moment REAL data is on screen. The
        // `.loading` spinner above is a frame the user cannot read, and closing the
        // measurement there would report an excellent launch and a false one.
        .onAppear { LaunchSignpost.shared.dataOnScreen() }
    }
  }

  private func answerList(_ answer: Answer, _ metadata: StoreMetadata) -> some View {
    List {
      if !answer.warnings.isEmpty {
        Section("Please note") {
          ForEach(answer.warnings, id: \.code) { warning in
            Text(warning.rendered).font(.footnote)
          }
        }
      }
      if !answer.notices.isEmpty {
        Section("From the pool") {
          ForEach(answer.notices, id: \.text) { notice in
            Text(notice.text).font(.footnote)
          }
        }
      }
      Section("Open — \(answer.options.count) sessions") {
        ForEach(answer.options) { option in
          optionRow(option)
        }
      }
      Section("No sessions listed") {
        ForEach(answer.statuses) { status in
          statusRow(status)
        }
      }
      Section {
        LabeledContent("Data from", value: metadata.goldValidAsOf)
        LabeledContent("Answers through", value: metadata.horizonEnd)
      }
    }
  }

  private func optionRow(_ option: SwimOption) -> some View {
    // The row and everything it can expand into stay inside ONE container: a `ForEach`
    // element that resolves to a variable number of views forces `List` to build every
    // row's body just to learn the identifiers (WWDC23 10160), which is the laziness this
    // screen must not lose as it grows.
    VStack(alignment: .leading, spacing: 4) {
      HStack {
        Text(option.poolName).font(.headline)
        Spacer()
        Text(mark(option.mark)).accessibilityLabel(markLabel(option.mark))
      }
      Text("\(option.window.start.hhmm)–\(option.window.end.hhmm) · \(option.basinName)")
        .font(.subheadline)
        .foregroundStyle(.secondary)
      if option.openAtQueryTime {
        Text("Open now").font(.caption).foregroundStyle(.tint)
      }
      if let price = option.price {
        Text(price.display).font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private func statusRow(_ status: PoolDayStatus) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(status.poolName).font(.headline)
      Text(Self.statusLabel(status: status.status, closureCode: status.closureCode))
        .font(.subheadline)
        .foregroundStyle(.secondary)
    }
  }

  /// The four states, each said as itself. A schedule-less pool is NOT closed — we simply
  /// do not know its hours, and saying "closed" would be a claim the data never made.
  ///
  /// Deliberately `static` and taking the two fields it reads rather than the whole status:
  /// that makes the mapping drivable from the app-hosted test across all four states, which
  /// is how the never-render-a-ghost-as-closed rule is asserted instead of asserted-in-prose.
  static func statusLabel(status: String, closureCode: String?) -> String {
    switch status {
    case "closed":
      switch closureCode {
      case "out_of_season": return "Closed — outside its season"
      case "no_sessions": return "Closed today"
      default: return "Closed — \(closureCode ?? "reason not stated")"
      }
    case "awaiting_scrape": return "Hours not published yet"
    case "no_source": return "No schedule source for this pool"
    case "open_unscheduled": return "Open, but hours are not listed"
    default: return status
    }
  }

  private func mark(_ mark: UIMark) -> String {
    switch mark {
    case .attend: return "✓"
    case .check: return "?"
    case .no: return "✕"
    }
  }

  private func markLabel(_ mark: UIMark) -> String {
    switch mark {
    case .attend: return "You may attend"
    case .check: return "Check with the pool"
    case .no: return "Not open to you"
    }
  }
}

#Preview {
  TodayView()
}
