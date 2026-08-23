// The one piece of state the walking skeleton needs: load the bundled store, ask it for
// today, publish the result.
//
// It holds no RULES. Everything it shows — which sessions exist, whether each is open at
// this minute, what a schedule-less pool's honest state is — is decided in `SwimZHKit` and
// tested there. This type only sequences the call and names the three states a screen can
// be in, which is why the app target stays outside the CRAP gate without hiding anything.

import Foundation
import SwimZHKit

@MainActor
@Observable
final class TodayModel {
  enum State {
    case loading
    case ready(Answer, StoreMetadata)
    /// The store could not be opened or read. Shown as itself — never as an empty list,
    /// which would read as "nothing is open today".
    case failed(String)
  }

  private(set) var state: State = .loading
  private var store: Store?

  func load(now: Date = Date()) async {
    do {
      let store = try self.store ?? Store.bundled()
      self.store = store
      let metadata = try await store.metadata()
      let answer = try await store.answer(on: now, at: now, for: Person())
      state = .ready(answer, metadata)
    } catch {
      state = .failed(String(describing: error))
    }
  }
}
