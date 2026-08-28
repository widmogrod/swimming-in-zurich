// AccessExplainer.swift — the access-types legend, ported rather than fetched.
//
// The web serves this from `/access-types`. The phone has no network at all (a lint says so),
// so it ships its own copy — and a copy of prose is a copy that drifts. The drift would be
// invisible, too: both sides would stay self-consistent while telling swimmers different things
// about who may enter a girls-only session.
//
// So the copy is GENERATED-CONTRACT-BACKED: `scripts/ios_fixtures.py` writes
// `Fixtures/access_types.json` straight from `domain.access.ACCESS_TYPES`, and
// `AccessExplainerTests` asserts this table reproduces it key for key and word for word.
//
// S4 turned the sentences into catalog keys and DEMOTED THE PYTHON PROSE TO THE TEST'S ORACLE:
// the table below names messages, and the parity test renders them through the ENGLISH catalog
// before comparing to `access_types.json`. That is a stronger check than the string equality it
// replaced — it proves the English catalog still says what the domain says AND that all five
// languages carry the key, where before it only proved a Swift literal matched a JSON literal.

import Foundation

/// One access type, explained.
public struct AccessExplanation: Equatable, Sendable, Identifiable {
  /// The class name the export writes in `session.access_kind` — the only thing a session row
  /// can be joined on.
  public let className: String
  /// The web's own key for this type (`/access-types`). It is NOT the catalog key: the catalog
  /// uses `access.women`, the API `women-only`, and conflating them would tie the message
  /// namespace to an HTTP surface this app never calls.
  public let key: String
  public let label: Message
  public let description: Message

  public var id: String { className }
}

/// The whole legend, in the domain's own order (`REPRESENTATIVE_ACCESS`).
public let accessExplanations: [AccessExplanation] = [
  explanation("PublicSwim", api: "public", catalog: "access.public"),
  explanation("LaneSwim", api: "lane-swim", catalog: "access.lane"),
  explanation("FamilyTime", api: "family", catalog: "access.family"),
  explanation("WomenOnly", api: "women-only", catalog: "access.women"),
  explanation("SeniorsOnly", api: "seniors-only", catalog: "access.seniors"),
  explanation("SchoolReserved", api: "school-reserved", catalog: "access.school"),
  explanation("ClubReserved", api: "club-reserved", catalog: "access.club"),
  explanation("AdultsOnly", api: "adults-only", catalog: "access.adults"),
  explanation("GirlsOnly", api: "girls-only", catalog: "access.girls"),
  explanation("GenderDiverse", api: "gender-diverse", catalog: "access.genderDiverse"),
  explanation("AccompaniedChildren", api: "accompanied-children", catalog: "access.accompanied"),
]

/// The label/description pair for one access class.
///
/// The `.desc` suffix is a CONVENTION the catalog keeps (`access.women` / `access.women.desc`)
/// and this is the only place that relies on it, so a key that broke it would fail
/// `AccessExplainerTests` immediately rather than rendering a raw key on the legend screen.
private func explanation(_ className: String, api: String, catalog: String) -> AccessExplanation {
  AccessExplanation(
    className: className,
    key: api,
    label: Message(catalog),
    description: Message("\(catalog).desc")
  )
}

/// The explanation for one access class, or nil for one this binary has never heard of.
///
/// Nil rather than a generic "public swimming" fallback: a store built by a newer export can
/// carry an arm this app does not know, and describing it as open to everyone is precisely the
/// welcome-by-default failure the eligibility vocabulary exists to prevent.
public func accessExplanation(for className: String) -> AccessExplanation? {
  accessExplanations.first { $0.className == className }
}
