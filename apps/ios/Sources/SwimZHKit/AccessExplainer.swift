// AccessExplainer.swift — the access-types legend, ported rather than fetched.
//
// The web serves this from `/access-types`. The phone has no network at all (a lint says so),
// so it ships its own copy — and a copy of prose is a copy that drifts. The drift would be
// invisible, too: both sides would stay self-consistent while telling swimmers different things
// about who may enter a girls-only session.
//
// So the copy is GENERATED-CONTRACT-BACKED: `scripts/ios_fixtures.py` writes
// `Fixtures/access_types.json` straight from `domain.access.ACCESS_TYPES`, and
// `AccessExplainerTests` asserts this table reproduces it key for key and word for word. The
// English is deliberate and temporary, exactly as `DayWarning.rendered`'s is: it is the parity
// witness. S4 keys the sentences off `key` and renders them from the catalog.

import Foundation

/// One access type, explained.
public struct AccessExplanation: Equatable, Sendable, Identifiable {
  /// The class name the export writes in `session.access_kind` — the only thing a session row
  /// can be joined on.
  public let className: String
  /// The web's own key for this type (`/access-types`), and S4's message key.
  public let key: String
  public let label: String
  public let description: String

  public var id: String { className }
}

/// The whole legend, in the domain's own order (`REPRESENTATIVE_ACCESS`).
public let accessExplanations: [AccessExplanation] = [
  AccessExplanation(
    className: "PublicSwim", key: "public", label: "Public swim",
    description: "Open public swimming — anyone may enter during these hours."),
  AccessExplanation(
    className: "LaneSwim", key: "lane-swim", label: "Lane swim",
    description:
      "Lane swimming (Bahnenschwimmen) — public, organised into lanes for laps/training."),
  AccessExplanation(
    className: "FamilyTime", key: "family", label: "Family time",
    description: "Family/children session — public, oriented to families and kids."),
  AccessExplanation(
    className: "WomenOnly", key: "women-only", label: "Women only",
    description: "Women-only session (Frauenbad / Frauenschwimmen) — reserved for women."),
  AccessExplanation(
    className: "SeniorsOnly", key: "seniors-only", label: "Seniors only",
    description: "Seniors session — reserved for guests aged 60 and over."),
  AccessExplanation(
    className: "SchoolReserved", key: "school-reserved", label: "School reserved",
    description: "Reserved for school classes — not open to the public."),
  AccessExplanation(
    className: "ClubReserved", key: "club-reserved", label: "Club reserved",
    description: "Reserved for a club/association — not open to the public."),
  AccessExplanation(
    className: "AdultsOnly", key: "adults-only", label: "Adults only",
    description:
      "Adults-only public window — reserved for guests aged 18 and over (typical for "
      + "school-pool evening swims)."),
  AccessExplanation(
    className: "GirlsOnly", key: "girls-only", label: "Girls only",
    description:
      "Girls-only session (für Mädchen) — the pool publishes no age cutoff, so confirm with "
      + "the venue."),
  AccessExplanation(
    className: "GenderDiverse", key: "gender-diverse", label: "Trans and non-binary",
    description: "Session open to trans and non-binary people aged 16 and over."),
  AccessExplanation(
    className: "AccompaniedChildren", key: "accompanied-children",
    label: "Children with an adult",
    description:
      "For children only when accompanied by an adult (für Kinder nur mit Erwachsenen)."),
]

/// The explanation for one access class, or nil for one this binary has never heard of.
///
/// Nil rather than a generic "public swimming" fallback: a store built by a newer export can
/// carry an arm this app does not know, and describing it as open to everyone is precisely the
/// welcome-by-default failure the eligibility vocabulary exists to prevent.
public func accessExplanation(for className: String) -> AccessExplanation? {
  accessExplanations.first { $0.className == className }
}
