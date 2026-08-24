// S3a acceptance 2: the four day states render DISTINCTLY, none of them as a plain "closed",
// and a date past `horizon_end` is a fifth state distinct from all four.
//
// The rule under test is the one the data model forbids breaking: a schedule-less pool is
// never "closed". `awaiting_scrape`, `no_source` and `open_unscheduled` are three different
// admissions that we do not know a pool's hours; `closed` is a claim the source made. Telling
// a swimmer a pool is shut when it may well be open is the harm, and it is a one-word edit
// away at all times — hence a test rather than a comment.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("The five day states")
struct DayStateTests {
  static let fourStates = ["closed", "awaiting_scrape", "no_source", "open_unscheduled"]

  @Test("the store's vocabulary maps one-to-one onto the state union")
  func vocabularyMaps() {
    #expect(dayState(status: "closed", closureCode: "no_sessions") == .closed(.noSessions))
    #expect(dayState(status: "closed", closureCode: "out_of_season") == .closed(.outOfSeason))
    #expect(dayState(status: "closed", closureCode: "unmapped") == .closed(.unmapped(text: "")))
    #expect(
      dayState(
        status: "closed", closureCode: "unmapped", detailParams: ["text": " Sommerpause "]
      ) == .closed(.unmapped(text: "Sommerpause"))
    )
    #expect(dayState(status: "closed", closureCode: "revision") == .closed(.other("revision")))
    #expect(dayState(status: "closed", closureCode: nil) == .closed(.unstated))
    #expect(dayState(status: "closed", closureCode: "") == .closed(.unstated))
    #expect(dayState(status: "awaiting_scrape", closureCode: nil) == .awaitingScrape)
    #expect(dayState(status: "no_source", closureCode: nil) == .noSource)
    #expect(dayState(status: "open_unscheduled", closureCode: nil) == .openUnscheduled)
    #expect(dayState(status: "teleported", closureCode: nil) == .unrecognised("teleported"))
  }

  @Test("NO state that is not `closed` renders as closed")
  func ghostStatesAreNeverClosed() {
    // The assertion is on the WORD, in both cases, because that is what a user reads. A future
    // edit that worded `no_source` as "Closed — no timetable" would be exactly the regression
    // this exists to catch, and it would satisfy any structural check.
    for status in Self.fourStates where status != "closed" {
      let label = dayStateLabel(dayState(status: status, closureCode: nil)).lowercased()
      #expect(!label.contains("closed"), "\(status) renders as \(label)")
      #expect(!label.contains("shut"))
    }
    let beyond = dayStateLabel(.beyondHorizon).lowercased()
    #expect(!beyond.contains("closed"))
    #expect(!dayStateLabel(.unrecognised("teleported")).lowercased().contains("closed"))
  }

  @Test("every state renders a DISTINCT sentence")
  func statesRenderDistinctly() {
    let labels = [
      dayStateLabel(.closed(.outOfSeason)),
      dayStateLabel(.closed(.noSessions)),
      dayStateLabel(.closed(.unmapped(text: "Sommerpause"))),
      dayStateLabel(.closed(.unmapped(text: ""))),
      dayStateLabel(.closed(.unstated)),
      dayStateLabel(.awaitingScrape),
      dayStateLabel(.noSource),
      dayStateLabel(.openUnscheduled),
      dayStateLabel(.beyondHorizon),
    ]
    #expect(Set(labels).count == labels.count, "two states share a sentence: \(labels)")
    #expect(labels.allSatisfy { !$0.isEmpty })
  }

  @Test("an unmapped closure QUOTES the pool's own words, never a paraphrase")
  func unmappedClosuresQuoteTheSource() {
    // The point of `unmapped` is that nobody classified the closure — so the pool's own sentence
    // in `detail_params["text"]` is the ONLY thing that can be said about it. A label that
    // merely promised "see the pool's own words" without showing them left the row asserting
    // "closed" with nothing behind the claim.
    let label = dayStateLabel(.closed(.unmapped(text: "Wegen Revision geschlossen")))
    #expect(label.contains("Wegen Revision geschlossen"))
    // Verbatim and UNTRANSLATED: the pool wrote it, in its own language.
    #expect(!label.contains("Revision closure"))
    // A row that carries no text says so plainly rather than borrowing a classified reason.
    #expect(dayStateLabel(.closed(.unmapped(text: ""))) == "Closed — reason not classified")
  }

  @Test("the pool's words reach the label through the STATUS, not just the enum")
  func unmappedTextFlowsFromTheRow() {
    let row = PoolDayStatus(
      poolID: "p", poolName: "P", poolKind: "indoor", status: "closed",
      detailCode: "d", closureCode: "unmapped", detailParams: ["text": "Sommerpause"],
      distanceKm: nil
    )
    let meta = StoreMetadata(
      schemaVersion: 1, builtAt: "", horizonStart: "2026-01-01", horizonEnd: "2027-01-01",
      goldValidAsOf: "", contentHash: ""
    )
    #expect(
      dayStateLabel(dayState(status: row, on: "2026-06-01", horizon: meta))
        .contains("Sommerpause")
    )
  }

  @Test("NO day-state label makes a temporal claim")
  func stateLabelsAreDayAgnostic() {
    // Ghost and closed rows are built WITHOUT reference to which day is today — a `day` row
    // exists for every date in the ~400-day horizon — so any temporal word in these labels is
    // rendered on every future date the strip can reach. "Closed today" was exactly that, and
    // the day strip made it reachable on ninety-odd future dates in the committed store.
    let labels = [
      dayStateLabel(.closed(.outOfSeason)),
      dayStateLabel(.closed(.noSessions)),
      dayStateLabel(.closed(.unmapped(text: "Sommerpause"))),
      dayStateLabel(.closed(.unmapped(text: ""))),
      dayStateLabel(.closed(.other("revision"))),
      dayStateLabel(.closed(.unstated)),
      dayStateLabel(.awaitingScrape),
      dayStateLabel(.noSource),
      dayStateLabel(.openUnscheduled),
      dayStateLabel(.beyondHorizon),
    ]
    for label in labels {
      let said = label.lowercased()
      for temporal in ["today", "tonight", "right now", " now", "this morning"] {
        #expect(!said.contains(temporal), "\"\(label)\" claims \"\(temporal)\"")
      }
    }
  }

  @Test("a closure claim and unknown hours are the two disjoint families")
  func familiesPartitionTheUnion() {
    let states: [DayState] = [
      .closed(.outOfSeason), .closed(.unmapped(text: "x")), .awaitingScrape, .noSource,
      .openUnscheduled, .beyondHorizon,
      .unrecognised("x"),
    ]
    for state in states {
      #expect(!(state.isClosureClaim && state.isUnknownHours), "\(state) is in both families")
    }
    #expect(DayState.closed(.noSessions).isClosureClaim)
    // The horizon state belongs to NEITHER: it is about the date, not about the pool.
    #expect(!DayState.beyondHorizon.isClosureClaim)
    #expect(!DayState.beyondHorizon.isUnknownHours)
  }

  @Test("a date past horizon_end is the fifth state, not a closure")
  func beyondHorizonIsItsOwnState() async throws {
    let meta = try await Store.bundled().metadata()
    let past = try #require(ZurichClock.day(meta.horizonEnd, plus: 1))
    #expect(!meta.covers(day: past))
    let closedRow = PoolDayStatus(
      poolID: "p", poolName: "P", poolKind: "indoor", status: "closed",
      detailCode: "d", closureCode: "no_sessions", detailParams: [:], distanceKm: nil
    )
    // The horizon wins over the row: past the horizon there ARE no rows, so anything a caller
    // hands in is stale, and reporting it would claim knowledge the store does not have.
    #expect(dayState(status: closedRow, on: past, horizon: meta) == .beyondHorizon)
    #expect(dayState(status: nil, on: past, horizon: meta) == .beyondHorizon)
    #expect(dayState(status: closedRow, on: meta.horizonEnd, horizon: meta) == .closed(.noSessions))
  }

  @Test("every status the REAL store carries is a state this binary knows")
  func theStoreCarriesNoUnknownStatus() async throws {
    // The unit tests above drive the vocabulary from a literal list; this drives it from the
    // committed store, so a status the export starts emitting cannot pass unnoticed.
    let store = try Store.bundled()
    let meta = try await store.metadata()
    var seen: Set<String> = []
    for offset in stride(from: 0, to: 140, by: 7) {
      guard let day = ZurichClock.day(meta.horizonStart, plus: offset), meta.covers(day: day)
      else { continue }
      let answer = try await store.answer(
        onDay: day, at: TimeOfDay(hour: 12, minute: 0), for: Person())
      for status in answer.statuses {
        seen.insert(status.status)
        let state = dayState(status: status.status, closureCode: status.closureCode)
        if case .unrecognised(let raw) = state {
          Issue.record("the store carries an unknown status: \(raw)")
        }
      }
    }
    #expect(seen.isSubset(of: Set(Self.fourStates)), "unexpected statuses: \(seen.sorted())")
    // ...and it really did read something, so the loop above cannot pass by reading nothing.
    #expect(seen.contains("closed"))
    #expect(seen.contains("no_source"))
  }
}
