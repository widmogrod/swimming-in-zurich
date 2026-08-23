// Eligibility.swift — the port of `src/swimzh/domain/access.py`.
//
// Eligibility is one of the three things the export deliberately does NOT bake: it depends
// on the person, not on the date. So it is re-implemented here — and a re-implementation of
// a rule drifts unless something stops it. `EligibilityContractTests` replays
// `apps/web/tests/fixtures/eligibility_contract.json`, the SAME generated file the browser
// module replays, so the Python domain, the browser badge and this file cannot disagree
// about any (access × gender × age) cell without a red test on both sides.
//
// The verdict is never a bare Bool. `allowed=false` covers two very different situations —
// "you may not attend" and "we cannot tell from what you told us" — and merging them is the
// exact harm `access.py` was written to avoid. `ReasonCode` keeps them apart, and `UIMark`
// draws them apart.

import Foundation

public enum Gender: String, Equatable, Sendable, CaseIterable {
  case female
  case male
  case diverse
}

public struct Person: Equatable, Sendable {
  public let gender: Gender?
  public let age: Int?

  public init(gender: Gender? = nil, age: Int? = nil) {
    self.gender = gender
    self.age = age
  }
}

/// The tagged union of `domain/access.SessionAccess`, with each arm's own fields.
///
/// `unknown` has no Python counterpart on purpose: the domain union is closed and
/// exhaustively matched, but this app reads a STORE, and a store built by a newer export
/// can carry an arm this binary has never heard of. `eligibility` answers "check with the
/// pool" for it — never "you may attend" — mirroring the documented fallback in
/// `eligibility.js`, which exists because an earlier "default to open" drew a welcome tick
/// on a girls-only session the server had already refused.
public enum SessionAccess: Equatable, Hashable, Sendable {
  case publicSwim
  case laneSwim(note: String)
  case familyTime(note: String)
  case womenOnly(note: String)
  case seniorsOnly(minAge: Int)
  case schoolReserved
  case clubReserved(club: String)
  case adultsOnly(minAge: Int, note: String)
  case girlsOnly
  case genderDiverse(minAge: Int)
  case accompaniedChildren
  case unknown(kind: String)

  /// The class name the export stores in `session.access_kind`
  /// (`type(session.access).__name__`), which is also what `/swim` emits.
  public var kind: String {
    switch self {
    case .publicSwim: return "PublicSwim"
    case .laneSwim: return "LaneSwim"
    case .familyTime: return "FamilyTime"
    case .womenOnly: return "WomenOnly"
    case .seniorsOnly: return "SeniorsOnly"
    case .schoolReserved: return "SchoolReserved"
    case .clubReserved: return "ClubReserved"
    case .adultsOnly: return "AdultsOnly"
    case .girlsOnly: return "GirlsOnly"
    case .genderDiverse: return "GenderDiverse"
    case .accompaniedChildren: return "AccompaniedChildren"
    case .unknown(let kind): return kind
    }
  }
}

/// The parameters an access arm carries in `session.access_params`, as the export writes
/// them (`dataclasses.asdict(access)`): `min_age`, `club`, `note` — each present only on the
/// arms that declare it.
public struct AccessParams: Decodable, Equatable, Sendable {
  public let minAge: Int?
  public let club: String?
  public let note: String?

  public init(minAge: Int? = nil, club: String? = nil, note: String? = nil) {
    self.minAge = minAge
    self.club = club
    self.note = note
  }

  private enum CodingKeys: String, CodingKey {
    case minAge = "min_age"
    case club
    case note
  }

  public static func decode(json: String) -> AccessParams {
    guard let data = json.data(using: .utf8),
      let params = try? JSONDecoder().decode(AccessParams.self, from: data)
    else {
      return AccessParams()
    }
    return params
  }
}

extension SessionAccess {
  /// The `(access_kind, access_params)` pair the export stores, back into the union.
  ///
  /// NO arm invents a published age bound. `access.py` gives `SeniorsOnly` and `AdultsOnly`
  /// dataclass defaults (60 and 18), but a default is what the DOMAIN falls back to when a
  /// page states nothing — it is not what a CLIENT may assume when the store omits the
  /// field, because the export always writes it. A missing bound therefore means the row is
  /// unreadable, and the honest answer is `.unknown` (which resolves to "check with the
  /// pool") rather than a threshold nobody published. That is precisely the harm the browser
  /// module documents at length about its own hardcoded 60 / 18 / 16.
  ///
  /// `note` and `club` are different: they are display text, not decision inputs, so their
  /// absence is defaulted to empty and decides nothing.
  public static func decode(kind: String, params: AccessParams) -> SessionAccess {
    switch kind {
    case "PublicSwim": return .publicSwim
    case "LaneSwim": return .laneSwim(note: params.note ?? "")
    case "FamilyTime": return .familyTime(note: params.note ?? "")
    case "WomenOnly": return .womenOnly(note: params.note ?? "")
    case "SeniorsOnly":
      guard let minAge = params.minAge else { return .unknown(kind: kind) }
      return .seniorsOnly(minAge: minAge)
    case "SchoolReserved": return .schoolReserved
    case "ClubReserved": return .clubReserved(club: params.club ?? "")
    case "AdultsOnly":
      guard let minAge = params.minAge else { return .unknown(kind: kind) }
      return .adultsOnly(minAge: minAge, note: params.note ?? "")
    case "GirlsOnly": return .girlsOnly
    case "GenderDiverse":
      guard let minAge = params.minAge else { return .unknown(kind: kind) }
      return .genderDiverse(minAge: minAge)
    case "AccompaniedChildren": return .accompaniedChildren
    default: return .unknown(kind: kind)
    }
  }
}

/// The message identity of an eligibility outcome — the i18n key space, mirroring
/// `access.ReasonCode` value for value.
///
/// Distinct from `rule`, which names the ACCESS TYPE and is too coarse to key a message on:
/// a women-only session yields four different sentences that all share `rule`.
public enum ReasonCode: String, Equatable, Hashable, Sendable, CaseIterable {
  case publicSwim = "public"
  case laneSwim = "lane_swim"
  case family = "family"

  case womenOnlyWelcome = "women_only_welcome"
  case womenOnlyExcluded = "women_only_excluded"
  case womenOnlyConfirm = "women_only_confirm"
  case womenOnlyNeedsGender = "women_only_needs_gender"

  case seniorsOnlyWelcome = "seniors_only_welcome"
  case seniorsOnlyTooYoung = "seniors_only_too_young"
  case seniorsOnlyNeedsAge = "seniors_only_needs_age"

  case adultsOnlyWelcome = "adults_only_welcome"
  case adultsOnlyTooYoung = "adults_only_too_young"
  case adultsOnlyNeedsAge = "adults_only_needs_age"

  case schoolReserved = "school_reserved"
  case clubReserved = "club_reserved"

  case girlsOnlyExcluded = "girls_only_excluded"
  case girlsOnlyConfirm = "girls_only_confirm"
  case girlsOnlyNeedsGender = "girls_only_needs_gender"

  case genderDiverseTooYoung = "gender_diverse_too_young"
  case genderDiverseConfirm = "gender_diverse_confirm"

  case accompaniedChildrenConfirm = "accompanied_children_confirm"

  /// The client-only arm, for an access kind this binary does not know. It has no Python
  /// counterpart because the domain union is closed; see `SessionAccess.unknown`.
  case unknownAccessConfirm = "unknown_access_confirm"
}

/// An interpolation value for a reason message. `access.py`'s params are
/// `Mapping[str, str | int]`, and collapsing the int to a string here would make the
/// contract comparison lossy in exactly the place (`min_age`) it matters.
public enum ReasonParam: Equatable, Hashable, Sendable {
  case int(Int)
  case string(String)
}

public struct EligibilityResult: Equatable, Sendable {
  public let allowed: Bool
  /// The ACCESS TYPE this outcome came from. Kept for grouping/debugging; it is NOT a
  /// message key — four women-only outcomes share `rule = "women-only"`.
  public let rule: String
  public let code: ReasonCode
  public let params: [String: ReasonParam]

  public init(
    allowed: Bool,
    rule: String,
    code: ReasonCode,
    params: [String: ReasonParam] = [:]
  ) {
    self.allowed = allowed
    self.rule = rule
    self.code = code
    self.params = params
  }
}

/// Decide whether `person` may attend a session with the given `access` rule.
///
/// Unknown person attributes yield `allowed = false` with a "not determinable" reason rather
/// than an assumption — the caller can prompt for the missing detail.
public func eligibility(_ person: Person, _ access: SessionAccess) -> EligibilityResult {
  switch access {
  case .publicSwim:
    return EligibilityResult(allowed: true, rule: "public", code: .publicSwim)
  case .laneSwim:
    return EligibilityResult(allowed: true, rule: "lane-swim", code: .laneSwim)
  case .familyTime:
    return EligibilityResult(allowed: true, rule: "family", code: .family)
  case .womenOnly:
    return womenOnly(person)
  case .seniorsOnly(let minAge):
    return seniorsOnly(person, minAge)
  case .schoolReserved:
    return EligibilityResult(allowed: false, rule: "school-reserved", code: .schoolReserved)
  case .clubReserved(let club):
    // The club name rides as a PARAM, not spliced into a sentence — a translated message
    // decides where the name goes.
    return EligibilityResult(
      allowed: false,
      rule: "club-reserved",
      code: .clubReserved,
      params: club.isEmpty ? [:] : ["club": .string(club)]
    )
  case .adultsOnly(let minAge, _):
    return adultsOnly(person, minAge)
  case .girlsOnly:
    return girlsOnly(person)
  case .genderDiverse(let minAge):
    return genderDiverse(person, minAge)
  case .accompaniedChildren:
    // Accompaniment is not an attribute of `Person`, so this is never decidable:
    // `allowed = false` here means "check with the pool", never "you are excluded".
    return EligibilityResult(
      allowed: false,
      rule: "accompanied-children",
      code: .accompaniedChildrenConfirm
    )
  case .unknown:
    return EligibilityResult(allowed: false, rule: "unknown", code: .unknownAccessConfirm)
  }
}

private func womenOnly(_ person: Person) -> EligibilityResult {
  let rule = "women-only"
  switch person.gender {
  case .female:
    return EligibilityResult(allowed: true, rule: rule, code: .womenOnlyWelcome)
  case .male:
    return EligibilityResult(allowed: false, rule: rule, code: .womenOnlyExcluded)
  case .diverse:
    return EligibilityResult(allowed: false, rule: rule, code: .womenOnlyConfirm)
  case nil:
    return EligibilityResult(allowed: false, rule: rule, code: .womenOnlyNeedsGender)
  }
}

/// A *"für Mädchen"* session. Only the exclusion is decidable: the city publishes no age
/// cutoff for "Mädchen", so an adult woman cannot be told she may attend — that is a
/// confirm, the same shape as the women-only one.
private func girlsOnly(_ person: Person) -> EligibilityResult {
  let rule = "girls-only"
  switch person.gender {
  case .female:
    return EligibilityResult(allowed: false, rule: rule, code: .girlsOnlyConfirm)
  case .male, .diverse:
    return EligibilityResult(allowed: false, rule: rule, code: .girlsOnlyExcluded)
  case nil:
    return EligibilityResult(allowed: false, rule: rule, code: .girlsOnlyNeedsGender)
  }
}

/// NEVER a hard deny on gender: being trans is not a value of `Person.gender` (a trans
/// woman's gender is *female*), so deciding this session from that enum would wrongly
/// exclude her. The published age is the one checkable fact, and above it the honest answer
/// is "check", not "welcome".
private func genderDiverse(_ person: Person, _ minAge: Int) -> EligibilityResult {
  let rule = "gender-diverse"
  let params: [String: ReasonParam] = ["min_age": .int(minAge)]
  if let age = person.age, age < minAge {
    return EligibilityResult(
      allowed: false,
      rule: rule,
      code: .genderDiverseTooYoung,
      params: params
    )
  }
  return EligibilityResult(allowed: false, rule: rule, code: .genderDiverseConfirm, params: params)
}

private func adultsOnly(_ person: Person, _ minAge: Int) -> EligibilityResult {
  ageGate(
    person, minAge, rule: "adults-only", welcome: .adultsOnlyWelcome,
    tooYoung: .adultsOnlyTooYoung, needsAge: .adultsOnlyNeedsAge)
}

private func seniorsOnly(_ person: Person, _ minAge: Int) -> EligibilityResult {
  ageGate(
    person, minAge, rule: "seniors-only", welcome: .seniorsOnlyWelcome,
    tooYoung: .seniorsOnlyTooYoung, needsAge: .seniorsOnlyNeedsAge)
}

/// `_adults_only` and `_seniors_only` are the same three-way decision over a published
/// bound; only the reason codes differ. One implementation, so a fix to the boundary
/// (`>=`, never `>`) cannot land on one arm and miss the other.
private func ageGate(
  _ person: Person,
  _ minAge: Int,
  rule: String,
  welcome: ReasonCode,
  tooYoung: ReasonCode,
  needsAge: ReasonCode
) -> EligibilityResult {
  let params: [String: ReasonParam] = ["min_age": .int(minAge)]
  guard let age = person.age else {
    return EligibilityResult(allowed: false, rule: rule, code: needsAge, params: params)
  }
  if age >= minAge {
    return EligibilityResult(allowed: true, rule: rule, code: welcome, params: params)
  }
  return EligibilityResult(allowed: false, rule: rule, code: tooYoung, params: params)
}

// MARK: - The three marks a UI draws

/// The three badge states. `allowed = false` splits in two here, and the split is the whole
/// point: `.check` is NEVER merged with `.no`.
public enum UIMark: String, Equatable, Sendable {
  case attend = "in"
  case check = "chk"
  case no
}

/// `allowed = false` outcomes that genuinely EXCLUDE the person — the ✕ mark. Mirrors
/// `_HARD_DENIAL` in `apps/web/tests/test_eligibility_ui_contract.py`, which is the one
/// place this translation is defined for the web.
private let hardDenial: Set<ReasonCode> = [
  .womenOnlyExcluded,
  .seniorsOnlyTooYoung,
  .adultsOnlyTooYoung,
  .schoolReserved,
  .clubReserved,
  .girlsOnlyExcluded,
  .genderDiverseTooYoung,
]

/// The single badge for one session. Every non-allowed outcome that is not a hard denial is
/// "check with the pool" — including the unknown-access arm, which is why a store from the
/// future can never draw a welcome tick this binary did not reason about.
public func uiMark(_ result: EligibilityResult) -> UIMark {
  if result.allowed { return .attend }
  return hardDenial.contains(result.code) ? .no : .check
}

/// The single badge for a whole row (a pool's day): `attend > check > no`, so a row with any
/// attendable session is ✓, a row of only "check" sessions is ? (crucially NOT ✕), and only
/// an all-✕ row — or an empty one — is ✕. Mirrors `dayEligibility` in `eligibility.js`.
public func dayEligibility(_ marks: [UIMark]) -> UIMark {
  if marks.contains(.attend) { return .attend }
  if marks.contains(.check) { return .check }
  return .no
}
