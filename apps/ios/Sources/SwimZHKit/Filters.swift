// Filters.swift — everything the filter bar holds, and the local-only favourites.
//
// The web keeps the same state in `filterstate.js` (`DEFAULT_FILTER` + a pure `merge`), and
// the two agree on the value domains that matter: gender is Any/female/male/diverse, age is a
// representative number per band rather than a range, and "any" is the absence of a value, not
// a magic one. Two things the web has no control for and the phone does, per the plan's S3a:
// an ELIGIBLE-ONLY toggle and a KIND filter.
//
// It lives here rather than in the app target for the usual reason: every predicate below is a
// rule, and a rule in a `body` is a rule nothing measures.

import Foundation

/// One age band's representative age. The tariff and the access bounds are both step
/// functions, so a band only ever needs one number inside it — and a number the user picked
/// from a list is honest in a way a slider is not, because we then never claim to know an age
/// nobody entered.
public struct AgeBand: Equatable, Hashable, Sendable, Identifiable {
  public let id: String
  public let label: Message
  /// nil = "any age": every age-gated session answers "check", never a guess.
  public let age: Int?

  public init(id: String, label: Message, age: Int?) {
    self.id = id
    self.label = label
    self.age = age
  }

  /// The same five bands and the same representative ages the web toolbar offers
  /// (`DEFAULT_AGE_CHIPS`), so the two clients cannot answer differently for "Adult".
  public static let all: [AgeBand] = [
    AgeBand(id: "any", label: Message("toolbar.age.any"), age: nil),
    AgeBand(id: "child", label: Message("toolbar.age.child"), age: 8),
    AgeBand(id: "teen", label: Message("toolbar.age.teen"), age: 16),
    AgeBand(id: "adult", label: Message("toolbar.age.adult"), age: 34),
    AgeBand(id: "senior", label: Message("toolbar.age.senior"), age: 70),
  ]

  /// The band an age falls in, for restoring a saved filter. An age outside every band's
  /// representative value still resolves to the nearest band's LABEL while keeping the real
  /// age — the label is a caption, never the input to eligibility.
  public static func band(for age: Int?) -> AgeBand {
    guard let age else { return all[0] }
    return all.dropFirst().last { band in (band.age ?? 0) <= age } ?? all[1]
  }
}

/// A named point to measure distance from.
public struct Place: Equatable, Hashable, Sendable, Identifiable {
  public let id: String
  /// Two of the three presets are bare proper nouns and stay verbatim; the station carries a
  /// parenthetical gloss ("main station") that IS prose and so is a message.
  public let label: Wording
  public let point: GeoPoint
  /// How these coordinates were arrived at. See `PlaceSource` in `Located.swift` — it travels
  /// WITH the point rather than beside it, so a label and a position that disagree about where
  /// they came from cannot be constructed.
  public let source: PlaceSource

  public init(id: String, label: Wording, point: GeoPoint, source: PlaceSource = .preset) {
    self.id = id
    self.label = label
    self.point = point
    self.source = source
  }
}

/// The typeahead's candidates.
///
/// A STATIC list, and that is a design constraint rather than a shortcut: the app is offline by
/// construction (no networking code exists in either target, asserted by a lint), so a geocoder
/// is not available to it. These are the web's own three presets.
///
/// THE DEVICE'S OWN POSITION IS NOT ONE OF THESE, and it is not absent either — see
/// `Located.swift`. This note used to say device location was left unbuilt because Core Location
/// would be the app's only new framework and the plan ruled out MapKit to keep it offline. The
/// map mode links MapKit now, so that premise is gone; the seam this note predicted turned out
/// to be the right one, and `Places.me(at:)` is exactly the "one more `Place`" it described.
public enum Places {
  public static let presets: [Place] = [
    Place(id: "hb", label: .key("place.hb"), point: GeoPoint(lat: 47.3779, lon: 8.5403)),
    Place(id: "bellevue", label: .verbatim("Bellevue"), point: GeoPoint(lat: 47.3671, lon: 8.5451)),
    Place(
      id: "zuerichhorn", label: .verbatim("Zürichhorn"), point: GeoPoint(lat: 47.3606, lon: 8.551)),
  ]

  /// The default origin, matching the web's `PLACE_PRESETS[0]`.
  public static var `default`: Place { presets[0] }

  /// Presets whose label matches `query`, diacritic- and case-insensitively.
  ///
  /// Diacritic folding is not a nicety here: the presets are Zürich place names and a phone
  /// keyboard makes "Zurich" far likelier than "Zürich". An empty query lists everything,
  /// which is what a combobox opening on focus needs.
  ///
  /// It matches against the RENDERED label, which is why it needs a `Localized` at all: a
  /// French reader searching "gare" should find the station, and matching the key or the
  /// English would silently fail for four of the five languages.
  public static func matching(_ query: String, in localized: Localized) -> [Place] {
    presets.filter { localized($0.label).matchesSearch(query) }
  }
}

extension String {
  /// Case- and diacritic-insensitive containment, with a whitespace-only query meaning "no
  /// filter". `localizedStandardContains` would be locale-dependent in a way a test cannot
  /// pin, so the folding is explicit.
  func matchesSearch(_ query: String) -> Bool {
    let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !needle.isEmpty else { return true }
    return
      folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
      .contains(needle.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil))
  }
}

/// Everything the filter bar holds.
public struct Filters: Equatable, Sendable {
  /// The Zurich calendar day being asked about (`yyyy-MM-dd`) — the day strip's selection.
  public var day: String
  public var gender: Gender?
  public var age: Int?
  /// Hide sessions this person may not attend. Off by default, matching the web board, which
  /// shows every session and annotates it: a ✕ badge teaches more than an absence does.
  public var eligibleOnly: Bool
  /// Facility kinds to keep. EMPTY MEANS ALL — an empty set is the natural "no filter", and it
  /// also means a kind added to the roster upstream shows up without a code change here.
  public var kinds: Set<String>
  public var search: String
  public var place: Place?
  /// nil = no radius limit, which is NOT the same as 0. `Store` applies this.
  public var radiusKm: Double?
  public var favouritesOnly: Bool

  /// Whether the list is showing less than everything. The DAY is not a narrowing — every
  /// answer is about some day, so counting it would make the control read as "on" always and
  /// tell a reader nothing. Search is not one either: while you are typing, the field itself
  /// is the visible evidence.
  public var isNarrowed: Bool {
    gender != nil || age != nil || eligibleOnly || !kinds.isEmpty || place != nil
      || radiusKm != nil || favouritesOnly
  }

  public init(
    day: String,
    gender: Gender? = nil,
    age: Int? = nil,
    eligibleOnly: Bool = false,
    kinds: Set<String> = [],
    search: String = "",
    place: Place? = Places.default,
    radiusKm: Double? = nil,
    favouritesOnly: Bool = false
  ) {
    self.day = day
    self.gender = gender
    self.age = age
    self.eligibleOnly = eligibleOnly
    self.kinds = kinds
    self.search = search
    self.place = place
    self.radiusKm = radiusKm
    self.favouritesOnly = favouritesOnly
  }

  /// The person these filters describe. Absent gender or age stays absent: `eligibility`
  /// answers "check with the pool" for what it was not told, and a defaulted adult male would
  /// be a fabricated answer.
  public var person: Person { Person(gender: gender, age: age) }

  public var origin: GeoPoint? { place?.point }

  /// Whether the pool browser's kind filter admits a kind.
  public func admits(kind: String) -> Bool {
    kinds.isEmpty || kinds.contains(kind)
  }

  /// The short captions the filter bar shows when it is collapsed. Only non-default values
  /// appear — a summary that always says "Any age" teaches nothing.
  public var summaryTags: [Wording] {
    var tags: [Wording] = []
    if let place { tags.append(place.label) }
    if let gender { tags.append(.key("toolbar.gender.\(gender.rawValue)")) }
    if age != nil { tags.append(.message(AgeBand.band(for: age).label)) }
    if eligibleOnly { tags.append(.key("filter.eligibleOnly")) }
    if favouritesOnly { tags.append(.key("filter.favourites")) }
    // Kind tokens go through `poolKindLabel` rather than being joined raw. They used to be
    // pasted in as the export's own words ("no_source"-shaped tokens like `school`), which was
    // a domain token on screen — and would have become an UNTRANSLATED domain token on screen
    // the moment the rest of this bar was localised.
    tags += kinds.sorted().map { .message(poolKindLabel($0)) }
    return tags
  }
}

/// The user's locally-saved pools. Local only — there is no account and no sync, which is why
/// the privacy manifest declares UserDefaults with reason `CA92.1` and nothing else.
///
/// A value type with an explicit encoding, so the app layer stores one plain `String` in
/// `UserDefaults` and every rule about ordering, deduplication and malformed input is testable
/// here rather than buried in a property wrapper.
public struct Favourites: Equatable, Sendable {
  public private(set) var ids: Set<String>

  public init(_ ids: Set<String> = []) {
    self.ids = ids
  }

  public func contains(_ poolID: String) -> Bool { ids.contains(poolID) }

  public mutating func toggle(_ poolID: String) {
    if ids.contains(poolID) {
      ids.remove(poolID)
    } else {
      ids.insert(poolID)
    }
  }

  /// Newline-separated ids, sorted — so the stored string is stable and two devices that
  /// favourited the same pools produce the same value.
  public var encoded: String { ids.sorted().joined(separator: "\n") }

  /// Tolerant by design: this reads a string a previous VERSION of the app wrote, and an
  /// unparseable entry must cost the user one favourite, never the whole list.
  public static func decode(_ raw: String) -> Favourites {
    Favourites(
      Set(
        raw.split(separator: "\n")
          .map { $0.trimmingCharacters(in: .whitespaces) }
          .filter { !$0.isEmpty }
      )
    )
  }
}
