// LocatedTests.swift — the rules that keep a position we do not have off the screen.

import Foundation
import Testing

@testable import SwimZHKit

@Suite("Where the reader is, and what may be claimed from it")
struct LocatedTests {
  static let bellevue = GeoPoint(lat: 47.3671, lon: 8.5451)

  // MARK: - The invariant

  @Test("a fix becomes a place, carrying where it came from")
  func aFixBecomesAPlace() {
    let place = try! #require(devicePlace(.fixed(Self.bellevue)))
    #expect(place.point == Self.bellevue)
    #expect(place.source == .device)
    #expect(place.id == devicePlaceID)
  }

  @Test("every state that is not a fix installs NOTHING")
  func nothingElseInstallsAPlace() {
    // THE INVARIANT, and the whole reason this function exists rather than an `if let` at the
    // call site. `.locating` is the tempting one — the reader has just asked, and a spinner
    // wants somewhere to live — but there is no coordinate yet, so anything installed here
    // would be a position the app does not have, rendered as a distance to fifty-seven pools.
    //
    // Swept over `LocationState.allStates` rather than a literal list, so a state added to the
    // enum arrives here without an edit. The literal it replaces could not have caught one.
    for state in LocationState.allStates(fixedAt: Self.bellevue) {
      guard case .fixed = state else {
        #expect(devicePlace(state) == nil, "\(state) installed a place")
        continue
      }
      #expect(devicePlace(state) != nil, "a fix must still install one")
    }
  }

  @Test("a preset is never mistaken for the device")
  func presetsSayTheyArePresets() {
    // The pair travels together: a `Place` cannot be built with a "My location" label over a
    // curated point, because the label and the source come from the same constructor call.
    for preset in Places.presets {
      #expect(preset.source == .preset, "\(preset.id)")
      #expect(preset.id != devicePlaceID, "a preset is claiming the device's id")
    }
  }

  @Test("walking a few metres does not make it a different place")
  func theDevicePlaceKeepsItsIdentity() {
    // A `Place` id derived from the coordinates would make `Filters` unequal on every fix, and
    // `TodayModel` reloads the whole answer when the filters change — so a phone on a windowsill
    // would rebuild fifty-seven rows every time the last decimal moved.
    let here = devicePlace(.fixed(Self.bellevue))
    let aStepAway = devicePlace(.fixed(GeoPoint(lat: 47.36711, lon: 8.54511)))
    #expect(here?.id == aStepAway?.id)
  }

  // MARK: - What gets said

  @Test("nothing is explained when there is nothing to explain")
  func silenceWhereSilenceIsRight() {
    // `.idle` has not happened yet and `.fixed` worked; a sentence under either would be noise
    // in the one place the reader is choosing something.
    #expect(locationNote(.idle) == nil)
    #expect(locationNote(.fixed(Self.bellevue)) == nil)
  }

  @Test("every state that is not a fix says WHY, and says something different")
  func everyRefusalHasItsOwnSentence() {
    // Three causes, three remedies, three sentences. A reader told the wrong one is sent
    // somewhere that cannot help them: Settings fixes `denied`, cannot fix `restricted`, and
    // will look entirely correct for `unavailable`.
    var seen: Set<String> = []
    for state in [LocationState.locating] + LocationRefusal.allCases.map(LocationState.refused) {
      let note = try! #require(locationNote(state), "\(state) explains nothing")
      #expect(seen.insert(note.key).inserted, "\(state) reuses another state's sentence")
    }
  }

  @Test("only a denial can be fixed in Settings")
  func settingsIsOfferedOnlyWhereItHelps() {
    #expect(settingsCanFix(.refused(.denied)))
    // ...and NOTHING else, swept rather than listed. `restricted` is Screen Time or a managed
    // device — the switch exists and this reader may not move it — and `unavailable` is
    // Location Services off device-wide, for which this app's own Settings page would look
    // entirely correct. A fourth refusal reaches this sweep through `allCases` and must state
    // its own answer here before it can ship an "Open Settings" button that leads nowhere.
    for state in LocationState.allStates(fixedAt: Self.bellevue) where state != .refused(.denied) {
      #expect(!settingsCanFix(state), "\(state) offers Settings")
    }
  }

  // MARK: - Launch

  @Test("the choice sticks, and launch never prompts")
  func launchLocatesOnlyWhenBothAreTrue() {
    // Either half alone is a defect rather than a lesser version of the feature. Preferred
    // without authorised is the cold-start permission dialog — the pattern that teaches people
    // to press Don't Allow, and the one this app can least afford, since its whole promise is
    // an answer the moment it opens. Authorised without preferred is taking a fix for a reader
    // who asked for the station.
    #expect(shouldLocateOnLaunch(preferred: true, alreadyAuthorised: true))
    #expect(!shouldLocateOnLaunch(preferred: true, alreadyAuthorised: false))
    #expect(!shouldLocateOnLaunch(preferred: false, alreadyAuthorised: true))
    #expect(!shouldLocateOnLaunch(preferred: false, alreadyAuthorised: false))
  }

  // MARK: - The sentences exist

  @Test("every sentence a refusal can produce is really in the catalog")
  func theRefusalSentencesResolve() {
    // `locationNote` builds its key by INTERPOLATION (`place.refused.\(rawValue)`), which the
    // lint that checks literal keys cannot see and which `interpolatedKeysHaveARealPrefix` can
    // only check the prefix of. So the cases are enumerated here, where the enum is: a fourth
    // refusal added without its sentence would render as the key itself, which on screen reads
    // as a design choice rather than as a missing string. `allCases` is what makes that true:
    // the array literal this loop used to walk did not grow when the enum did.
    //
    // Only KEY existence, not five-language parity: that is the web catalogs' own gate
    // (`locales/parity.test.ts`), and re-checking it here would be a second, weaker copy.
    for refusal in LocationRefusal.allCases {
      let note = try! #require(locationNote(.refused(refusal)))
      #expect(Catalog.entries[note.key] != nil, "no sentence for \(refusal)")
    }
    for key in ["place.locating", "place.myLocation", "place.useMyLocation", "action.openSettings"]
    {
      #expect(Catalog.entries[key] != nil, "\(key) is not in the catalog")
    }
  }
}
