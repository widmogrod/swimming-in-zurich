"""Session access rules (a tagged union) and *explainable* eligibility.

`eligibility(...)` never returns a bare bool: it returns which rule applied and why, so a
UI can explain "not this session, because it is women-only" and so gender/age edge cases
are auditable rather than hidden inside a boolean.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
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


@dataclass(frozen=True, slots=True)
class AdultsOnly:
    """Public window restricted to adults at or above `min_age` (school-pool evening swims)."""

    min_age: int = 18
    note: str = ""


type SessionAccess = (
    PublicSwim
    | LaneSwim
    | FamilyTime
    | WomenOnly
    | SeniorsOnly
    | SchoolReserved
    | ClubReserved
    | AdultsOnly
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
        case AdultsOnly(min_age):
            return AccessInfo(
                "adults-only",
                "Adults only",
                f"Adults-only public window — reserved for guests aged {min_age} and over "
                "(typical for school-pool evening swims).",
            )
        case _ as unreachable:
            assert_never(unreachable)


# One representative instance of every access type, for a UI legend / the /access-types API.
# The completeness test asserts this tuple covers every `SessionAccess` union member —
# adding an arm without a representative here is a silent gap the compiler cannot see.
REPRESENTATIVE_ACCESS: tuple[SessionAccess, ...] = (
    PublicSwim(),
    LaneSwim(),
    FamilyTime(),
    WomenOnly(),
    SeniorsOnly(),
    SchoolReserved(),
    ClubReserved(),
    AdultsOnly(),
)

ACCESS_TYPES: tuple[AccessInfo, ...] = tuple(access_info(a) for a in REPRESENTATIVE_ACCESS)


class ReasonCode(StrEnum):
    """The message identity of an eligibility outcome — the i18n key space.

    Distinct from `rule`, which names the ACCESS TYPE and is therefore too coarse to key a
    message on: a women-only session yields four different sentences (welcome / excluded /
    confirm with the venue / tell us your gender) that all share `rule="women-only"`.
    Keying on `rule` would silently render "you're welcome" for "you're not".

    Every arm of `eligibility()` returns exactly one of these, and
    `tests/domain/test_eligibility.py` asserts the enum is fully reachable — a code nobody
    produces is dead, and an outcome without one cannot exist because the compiler-checked
    `assert_never` below covers every access type.
    """

    PUBLIC = "public"
    LANE_SWIM = "lane_swim"
    FAMILY = "family"

    WOMEN_ONLY_WELCOME = "women_only_welcome"
    WOMEN_ONLY_EXCLUDED = "women_only_excluded"
    WOMEN_ONLY_CONFIRM = "women_only_confirm"
    WOMEN_ONLY_NEEDS_GENDER = "women_only_needs_gender"

    SENIORS_ONLY_WELCOME = "seniors_only_welcome"
    SENIORS_ONLY_TOO_YOUNG = "seniors_only_too_young"
    SENIORS_ONLY_NEEDS_AGE = "seniors_only_needs_age"

    ADULTS_ONLY_WELCOME = "adults_only_welcome"
    ADULTS_ONLY_TOO_YOUNG = "adults_only_too_young"
    ADULTS_ONLY_NEEDS_AGE = "adults_only_needs_age"

    SCHOOL_RESERVED = "school_reserved"
    CLUB_RESERVED = "club_reserved"


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    allowed: bool
    #: The ACCESS TYPE this outcome came from. Kept for grouping/debugging; it is NOT a
    #: message key — four women-only outcomes share `rule="women-only"`.
    rule: str
    #: The message key + its interpolation values. The English `reason` prose this
    #: replaced was retired in S5: the server no longer decides the answer's language.
    code: ReasonCode = ReasonCode.PUBLIC
    params: Mapping[str, str | int] = field(default_factory=dict)


def eligibility(person: Person, access: SessionAccess) -> EligibilityResult:
    """Decide whether `person` may attend a session with the given `access` rule.

    Unknown person attributes yield `allowed=False` with a "not determinable" reason
    rather than an assumption — the caller can prompt for the missing detail.
    """
    match access:
        case PublicSwim():
            return EligibilityResult(True, "public", ReasonCode.PUBLIC)
        case LaneSwim():
            return EligibilityResult(True, "lane-swim", ReasonCode.LANE_SWIM)
        case FamilyTime():
            return EligibilityResult(True, "family", ReasonCode.FAMILY)
        case WomenOnly():
            return _women_only(person)
        case SeniorsOnly(min_age):
            return _seniors_only(person, min_age)
        case SchoolReserved():
            return EligibilityResult(
                False,
                "school-reserved",
                ReasonCode.SCHOOL_RESERVED,
            )
        case ClubReserved(club):
            # The club name rides as a PARAM, not spliced into a sentence — a translated
            # message decides where the name goes.
            return EligibilityResult(
                False,
                "club-reserved",
                ReasonCode.CLUB_RESERVED,
                {"club": club} if club else {},
            )
        case AdultsOnly(min_age):
            return _adults_only(person, min_age)
        case _ as unreachable:
            assert_never(unreachable)


def _women_only(person: Person) -> EligibilityResult:
    rule = "women-only"
    match person.gender:
        case Gender.FEMALE:
            return EligibilityResult(True, rule, ReasonCode.WOMEN_ONLY_WELCOME)
        case Gender.MALE:
            return EligibilityResult(False, rule, ReasonCode.WOMEN_ONLY_EXCLUDED)
        case Gender.DIVERSE:
            return EligibilityResult(
                False,
                rule,
                ReasonCode.WOMEN_ONLY_CONFIRM,
            )
        case None:
            return EligibilityResult(
                False,
                rule,
                ReasonCode.WOMEN_ONLY_NEEDS_GENDER,
            )


def _adults_only(person: Person, min_age: int) -> EligibilityResult:
    rule = "adults-only"
    if person.age is None:
        return EligibilityResult(
            False,
            rule,
            ReasonCode.ADULTS_ONLY_NEEDS_AGE,
            {"min_age": min_age},
        )
    if person.age >= min_age:
        return EligibilityResult(
            True,
            rule,
            ReasonCode.ADULTS_ONLY_WELCOME,
            {"min_age": min_age},
        )
    return EligibilityResult(
        False,
        rule,
        ReasonCode.ADULTS_ONLY_TOO_YOUNG,
        {"min_age": min_age},
    )


def _seniors_only(person: Person, min_age: int) -> EligibilityResult:
    rule = "seniors-only"
    if person.age is None:
        return EligibilityResult(
            False,
            rule,
            ReasonCode.SENIORS_ONLY_NEEDS_AGE,
            {"min_age": min_age},
        )
    if person.age >= min_age:
        return EligibilityResult(
            True,
            rule,
            ReasonCode.SENIORS_ONLY_WELCOME,
            {"min_age": min_age},
        )
    return EligibilityResult(
        False,
        rule,
        ReasonCode.SENIORS_ONLY_TOO_YOUNG,
        {"min_age": min_age},
    )
