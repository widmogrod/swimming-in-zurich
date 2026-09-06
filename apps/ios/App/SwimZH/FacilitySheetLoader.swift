// FacilitySheetLoader.swift — one pool's screen, loading its facts after the push.
//
// This used to live at the bottom of the all-pools browser's file; the browser was removed on
// 2026-09-06 (the find list already holds every pool for the day, nearest first), and the loader
// is what both lists had actually shared.

import SwiftUI
import SwimZHKit

/// The sheet, loaded when it is opened rather than with the list.
///
/// One pool's detail is six reads; doing them for 57 pools to fill a list nobody has tapped
/// would spend the memory budget the list model has already half spent.
struct FacilitySheetLoader: View {
  let poolID: String
  /// The pool's name, from the roster — known before its facts are, so the screen can say it
  /// while they load.
  let name: String
  let day: String
  let person: Person
  /// The answer's row for this pool, when the screen was reached from an answer. Nil from the
  /// all-pools browser: the roster has no verdict, and inventing one there is the whole class
  /// of bug this app keeps finding. See `PoolHeader`.
  let row: PoolRow?
  /// Where the pool is, from the roster — the detail payload carries an address and no
  /// coordinates.
  let point: GeoPoint?
  let isToday: Bool
  let load: (String) async -> FacilityDetail?
  let live: (String?) async -> LiveTemp

  @Environment(\.scenePhase) private var scenePhase

  @State private var detail: FacilityDetail?
  /// The live reading, or the honest reason there is none. It starts nil — meaning "not asked
  /// yet" — and the sheet omits the row entirely until the answer arrives, because a row that
  /// said "unavailable" for the first 300 ms and then a temperature would be two claims.
  @State private var reading: LiveTemp?
  /// The instant the reading's AGE is stated as of. It is `@State` rather than `Date()` at the
  /// point of use because that is the difference between "measured 3 min ago" being true when
  /// the sheet opened and being true now: SwiftUI re-evaluates a body when its state changes,
  /// not when the clock moves, so a sheet left open would go on printing the age it had at
  /// load. Moving this is what makes the sentence re-render.
  @State private var asOf = Date()

  var body: some View {
    content
      .task {
        let detail = await load(poolID)
        self.detail = detail
        // ONE fetch, after the sheet has something to show. It cannot fail visibly: every
        // failure inside `LiveClient` is already an `.unavailable` state with its own sentence.
        await reask()
        // ...and then once a minute for as long as the sheet is on screen, because the age it
        // prints is a fact about the clock. Structured concurrency cancels this when the view
        // goes away, and most iterations are served from `LiveClient`'s cache, so the cost is
        // one re-worded sentence per minute rather than a request.
        while !Task.isCancelled {
          try? await Task.sleep(for: .seconds(LiveClient.reaskInterval))
          guard !Task.isCancelled else { return }
          await reask()
        }
      }
      // Time passes while the app is in the background too, and `Task.sleep` is not a promise
      // about wall-clock. Coming back to the foreground is the one moment a stale age is
      // certain, so it is re-asked there as well.
      .onChange(of: scenePhase) { _, phase in
        guard phase == .active else { return }
        Task { await reask() }
      }
  }

  /// Ask again, and restate the age as of now.
  private func reask() async {
    reading = await live(detail?.baditickerPOIID)
    asOf = Date()
  }

  /// The screen, at once. The map and the pool's name come from the roster and need no read;
  /// the facts fill the panel when `detail` lands. A spinner where the screen should be is
  /// what this used to show for the first few hundred milliseconds of every pool.
  private var content: some View {
    FacilitySheet(
      detail: detail, name: name, day: day, person: person, live: reading, asOf: asOf, row: row,
      point: point, isToday: isToday)
  }
}
