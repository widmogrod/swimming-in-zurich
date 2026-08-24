// PoolBrowser.swift — the all-pools roster, filtered.
//
// The find screen answers "where can I swim on this date", which is narrowed by a radius, a
// kind and a search — so a pool can be entirely absent from it while still being a pool. The
// browser is the roster itself, and the two rules it applies live here rather than in the view
// for the usual reason: they are rules, and the app target is not measured.
//
// The SEARCH is deliberately the same predicate the list screen uses (`matchesSearch`), so a
// query that finds a pool on one screen finds it on the other. That equality is the whole
// reason this is one function instead of a `filter` in each view.

import Foundation

/// The roster, narrowed by kind and by name. `nil` kind means every kind — the absence of a
/// filter, which is not the same as a kind called "all".
public func browsePools(_ pools: [PoolRecord], kind: String?, search: String) -> [PoolRecord] {
  pools
    .filter { pool in
      (kind == nil || pool.kind == kind) && pool.name.matchesSearch(search)
    }
    .sorted { $0.name < $1.name }
}

/// Every kind present in the roster, in a stable order.
///
/// From the ROSTER, never from a day's answer: an answer is already narrowed by the radius, so
/// a kind list built from one would silently lose the kinds that happen to be far away today.
public func poolKinds(_ pools: [PoolRecord]) -> [String] {
  Set(pools.map(\.kind)).sorted()
}

/// The WFS roster's kind vocabulary, said in words.
///
/// A kind this binary has never seen is shown as ITSELF, never folded into "indoor": the store
/// can be newer than the app, and a mislabelled pool sends somebody to the wrong kind of water.
public func poolKindLabel(_ kind: String) -> Message {
  switch kind {
  case "indoor", "outdoor", "lake", "river", "thermal", "school", "paddling":
    return Message("poolKind.\(kind)")
  default:
    // The unknown kind rides through a passthrough message rather than being shown bare, so
    // the surrounding punctuation is still the catalog's — and so the lint that says every
    // rendered literal is a catalog key stays true of this path too.
    return Message(
      "poolKind.unknown", ["kind": kind.replacingOccurrences(of: "_", with: " ").capitalized])
  }
}
