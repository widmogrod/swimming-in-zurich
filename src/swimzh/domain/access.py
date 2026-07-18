"""Session access rules (a tagged union) and *explainable* eligibility.

`eligibility(...)` never returns a bare bool: it returns which rule applied and why, so a
UI can explain "not this session, because it is women-only" and so gender/age edge cases
are auditable rather than hidden inside a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from swimzh.domain.person import Gender, Person


@dataclass(frozen=True, slots=True)
class PublicSwim:
    """Open public swimming — anyone may attend."""


@dataclass(frozen=True, slots=True)
class LaneSwim:
    """Public, but organised into lanes (Bahnenschwimmen). Open to anyone."""

    note: str = ""


@dataclass(frozen=True, slots=True)
class FamilyTime:
    """Public family/child-focused session. Open to anyone."""

    note: str = ""


@dataclass(frozen=True, slots=True)
class WomenOnly:
    """Women-only session (Frauenbad / Frauenschwimmen)."""

    note: str = ""


@dataclass(frozen=True, slots=True)
class SeniorsOnly:
    """Session reserved for seniors at or above `min_age`."""

    min_age: int = 60


@dataclass(frozen=True, slots=True)
class SchoolReserved:
    """Reserved for school use — not open to the public."""


@dataclass(frozen=True, slots=True)
class ClubReserved:
    """Reserved for a club/association — not open to the public."""

    club: str = ""


type SessionAccess = (
    PublicSwim | LaneSwim | FamilyTime | WomenOnly | SeniorsOnly | SchoolReserved | ClubReserved
)


@dataclass(frozen=True, slots=True)
class AccessInfo:
    """A human-readable explanation of an access type (for a UI legend / API)."""

    key: str
    label: str
    description: str


def access_info(access: SessionAccess) -> AccessInfo:
    """Explain what an access type means, for the specific session."""
    match access:
        case PublicSwim():
            return AccessInfo(
                "public",
                "Public swim",
                "Open public swimming — anyone may enter during these hours.",
            )
        case LaneSwim():
            return AccessInfo(
                "lane-swim",
                "Lane swim",
                "Lane swimming (Bahnenschwimmen) — public, organised into lanes for laps/training.",
            )
        case FamilyTime():
            return AccessInfo(
                "family",
                "Family time",
                "Family/children session — public, oriented to families and kids.",
            )
        case WomenOnly():
            return AccessInfo(
                "women-only",
                "Women only",
                "Women-only session (Frauenbad / Frauenschwimmen) — reserved for women.",
            )
        case SeniorsOnly(min_age):
            return AccessInfo(
                "seniors-only",
                "Seniors only",
                f"Seniors session — reserved for guests aged {min_age} and over.",
            )
        case SchoolReserved():
            return AccessInfo(
                "school-reserved",
                "School reserved",
                "Reserved for school classes — not open to the public.",
            )
        case ClubReserved(club):
            who = f" ({club})" if club else ""
            return AccessInfo(
                "club-reserved",
                "Club reserved",
                f"Reserved for a club/association{who} — not open to the public.",
            )
        case _ as unreachable:
            assert_never(unreachable)


# One representative instance of every access type, for a UI legend / the /access-types API.
ACCESS_TYPES: tuple[AccessInfo, ...] = (
    access_info(PublicSwim()),
    access_info(LaneSwim()),
    access_info(FamilyTime()),
    access_info(WomenOnly()),
    access_info(SeniorsOnly()),
    access_info(SchoolReserved()),
    access_info(ClubReserved()),
)


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    allowed: bool
    rule: str
    reason: str


def eligibility(person: Person, access: SessionAccess) -> EligibilityResult:
    """Decide whether `person` may attend a session with the given `access` rule.

    Unknown person attributes yield `allowed=False` with a "not determinable" reason
    rather than an assumption — the caller can prompt for the missing detail.
    """
    match access:
        case PublicSwim():
            return EligibilityResult(True, "public", "public swimming — open to all")
        case LaneSwim():
            return EligibilityResult(True, "lane-swim", "lane swimming — open to all")
        case FamilyTime():
            return EligibilityResult(True, "family", "family session — open to all")
        case WomenOnly():
            return _women_only(person)
        case SeniorsOnly(min_age):
            return _seniors_only(person, min_age)
        case SchoolReserved():
            return EligibilityResult(False, "school-reserved", "reserved for schools — not public")
        case ClubReserved(club):
            who = f" ({club})" if club else ""
            return EligibilityResult(
                False, "club-reserved", f"reserved for a club{who} — not public"
            )
        case _ as unreachable:
            assert_never(unreachable)


def _women_only(person: Person) -> EligibilityResult:
    rule = "women-only"
    match person.gender:
        case Gender.FEMALE:
            return EligibilityResult(True, rule, "women-only session")
        case Gender.MALE:
            return EligibilityResult(False, rule, "women-only session")
        case Gender.DIVERSE:
            return EligibilityResult(
                False, rule, "women-only session — please confirm admission with the venue"
            )
        case None:
            return EligibilityResult(
                False, rule, "women-only session — specify gender to determine eligibility"
            )


def _seniors_only(person: Person, min_age: int) -> EligibilityResult:
    rule = "seniors-only"
    if person.age is None:
        return EligibilityResult(
            False,
            rule,
            f"seniors-only session (age {min_age}+) — specify age to determine eligibility",
        )
    if person.age >= min_age:
        return EligibilityResult(True, rule, f"seniors-only session (age {min_age}+)")
    return EligibilityResult(False, rule, f"seniors-only session — requires age {min_age}+")
