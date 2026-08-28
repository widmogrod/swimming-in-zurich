// Pricing.swift — the port of `src/swimzh/domain/pricing.py`.
//
// The price bracket depends on the person's age, so it is the second thing the export
// cannot bake. `price` is deliberately NOT a table in the export: the pool's whole tariff
// rides as one `prices_doc` JSON blob and the bracket is picked here.
//
// This is not a tariff engine. Prices come from HTML, go stale, and carry liability if
// computed wrong, so each entry stores a dated display string, an amount, and the PUBLISHED
// lower age bound it was printed under (`Erwachsene (ab 20 J.)` -> minAge 20). `priceFor`
// picks the entry whose bound the person clears; it never guesses. An age below every
// published bound (Zürich prints nothing for under-6) yields nil: unknown is not the adult
// rate.

import Foundation

public enum PriceCategory: String, Equatable, Hashable, Sendable {
  case child
  case youth
  case adult
}

public struct PriceEntry: Equatable, Hashable, Sendable {
  public let category: PriceCategory
  public let amountCHF: Double
  public let display: String
  /// The lower bound the tariff itself prints for this entry; nil if it prints none, in
  /// which case the entry is not age-resolvable at all and `priceFor` skips it rather than
  /// treating it as universal.
  public let minAge: Int?

  public init(category: PriceCategory, amountCHF: Double, display: String, minAge: Int?) {
    self.category = category
    self.amountCHF = amountCHF
    self.display = display
    self.minAge = minAge
  }
}

/// The tariff table as the export stores it (`_price_doc` in `etl/ios_export.py`).
public struct PriceDoc: Equatable, Sendable {
  public let entries: [PriceEntry]
  public let validAsOf: String?
  public let sourceURL: String?

  public init(entries: [PriceEntry], validAsOf: String? = nil, sourceURL: String? = nil) {
    self.entries = entries
    self.validAsOf = validAsOf
    self.sourceURL = sourceURL
  }
}

/// What the pool charges at all — `domain/admission.Admission`, as `pool.admission_state`
/// plus, for a tariff, its `prices_doc`.
public enum Admission: Equatable, Sendable {
  case tariff(PriceDoc)
  case free
  case unknown
}

/// The entry with the GREATEST published `minAge` this person's age clears.
///
/// An unknown age takes the entry with the greatest bound — the unreduced rate, the one
/// answer that can never undercharge. No age clears a bound it is below, so a table whose
/// lowest band starts at 6 returns nil for a 3-year-old.
///
/// The tie rule is `max(..., key=)`'s: Python keeps the FIRST maximal element, and
/// `Sequence.max(by:)` keeps the LAST, so the loop below is written by hand with a strict
/// `>` comparison. A duplicated bound in one tariff is rare, not impossible, and a silent
/// disagreement about which of two identically-bounded rows is charged is exactly the kind
/// of drift the golden fixture would not necessarily catch.
public func priceFor(_ doc: PriceDoc, _ person: Person) -> PriceEntry? {
  var best: PriceEntry?
  for entry in doc.entries {
    guard let bound = entry.minAge else { continue }
    if let age = person.age, bound > age { continue }
    if let current = best, let currentBound = current.minAge, bound <= currentBound { continue }
    best = entry
  }
  return best
}

/// The person's bracket for a pool, whatever the pool's admission state. A free or
/// unpriced pool has no bracket — and no bracket is nil, never a zero-franc entry.
public func priceFor(_ admission: Admission, _ person: Person) -> PriceEntry? {
  guard case .tariff(let doc) = admission else { return nil }
  return priceFor(doc, person)
}

// MARK: - Decoding the stored document

extension PriceDoc {
  private struct Wire: Decodable {
    struct Entry: Decodable {
      let category: String
      let amountCHF: Double
      let display: String
      let minAge: Int?

      private enum CodingKeys: String, CodingKey {
        case category
        case amountCHF = "amount_chf"
        case display
        case minAge = "min_age"
      }
    }

    let entries: [Entry]
    let validAsOf: String?
    let sourceURL: String?

    private enum CodingKeys: String, CodingKey {
      case entries
      case validAsOf = "valid_as_of"
      case sourceURL = "source_url"
    }
  }

  /// Parses `pool.prices_doc`. Returns nil for a malformed document — the caller reports it
  /// as a decode failure rather than serving a pool with a silently empty tariff.
  ///
  /// An unrecognised `category` is a malformed document, not a defaultable field. The
  /// domain enum is closed (child / youth / adult), so a fourth value can only mean the
  /// store is newer than this binary; coercing it to `adult` would quietly draw the
  /// unreduced rate against a band the app cannot read.
  public static func decode(json: String) -> PriceDoc? {
    guard let data = json.data(using: .utf8),
      let wire = try? JSONDecoder().decode(Wire.self, from: data)
    else { return nil }
    var entries: [PriceEntry] = []
    entries.reserveCapacity(wire.entries.count)
    for entry in wire.entries {
      guard let category = PriceCategory(rawValue: entry.category) else { return nil }
      entries.append(
        PriceEntry(
          category: category,
          amountCHF: entry.amountCHF,
          display: entry.display,
          minAge: entry.minAge
        )
      )
    }
    return PriceDoc(entries: entries, validAsOf: wire.validAsOf, sourceURL: wire.sourceURL)
  }
}
