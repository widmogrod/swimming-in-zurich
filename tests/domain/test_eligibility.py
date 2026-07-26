"""Eligibility is explainable: allowed + rule + reason for every access variant."""

from __future__ import annotations

from typing import get_args

from swimzh.domain.access import (
    ACCESS_TYPES,
    REPRESENTATIVE_ACCESS,
    AdultsOnly,
    ClubReserved,
    FamilyTime,
    LaneSwim,
    PublicSwim,
    ReasonCode,
    SchoolReserved,
    SeniorsOnly,
    SessionAccess,
    WomenOnly,
    eligibility,
)
from swimzh.domain.person import Gender, Person

ADULT = Person(gender=Gender.MALE, age=40)
WOMAN = Person(gender=Gender.FEMALE, age=40)
SENIOR = Person(gender=Gender.FEMALE, age=70)
DIVERSE = Person(gender=Gender.DIVERSE, age=40)
CHILD = Person(gender=Gender.FEMALE, age=10)
UNKNOWN = Person()


def test_public_lane_family_open_to_all() -> None:
    for access in (PublicSwim(), LaneSwim(), FamilyTime()):
        for person in (ADULT, WOMAN, UNKNOWN):
            result = eligibility(person, access)
            assert result.allowed is True
            assert result.code in {
                ReasonCode.PUBLIC,
                ReasonCode.LANE_SWIM,
                ReasonCode.FAMILY,
            }


def test_women_only() -> None:
    assert eligibility(WOMAN, WomenOnly()).allowed is True
    assert eligibility(ADULT, WomenOnly()).allowed is False
    # Non-binary and unspecified are not silently assumed either way.
    diverse = eligibility(DIVERSE, WomenOnly())
    assert diverse.allowed is False
    assert diverse.code is ReasonCode.WOMEN_ONLY_CONFIRM
    unknown = eligibility(UNKNOWN, WomenOnly())
    assert unknown.allowed is False
    assert unknown.code is ReasonCode.WOMEN_ONLY_NEEDS_GENDER


def test_seniors_only() -> None:
    assert eligibility(SENIOR, SeniorsOnly(min_age=60)).allowed is True
    assert eligibility(ADULT, SeniorsOnly(min_age=60)).allowed is False
    unknown_age = eligibility(Person(gender=Gender.MALE), SeniorsOnly(min_age=60))
    assert unknown_age.allowed is False
    assert unknown_age.code is ReasonCode.SENIORS_ONLY_NEEDS_AGE


def test_reserved_sessions_are_not_public() -> None:
    school = eligibility(ADULT, SchoolReserved())
    assert school.allowed is False
    assert school.rule == "school-reserved"
    club = eligibility(ADULT, ClubReserved(club="SC Uster"))
    assert club.allowed is False
    # The club name is DATA, not copy — it rides as a param so a translated sentence
    # can place it.
    assert club.code is ReasonCode.CLUB_RESERVED
    assert club.params == {"club": "SC Uster"}


def test_adults_only() -> None:
    assert eligibility(ADULT, AdultsOnly()).allowed is True
    # The core correctness trap: a child must NOT be told "you can swim".
    child = eligibility(CHILD, AdultsOnly())
    assert child.allowed is False
    assert child.rule == "adults-only"
    assert child.code is ReasonCode.ADULTS_ONLY_TOO_YOUNG
    assert child.params == {"min_age": 18}
    unknown_age = eligibility(Person(gender=Gender.MALE), AdultsOnly())
    assert unknown_age.allowed is False
    assert unknown_age.code is ReasonCode.ADULTS_ONLY_NEEDS_AGE


def test_result_reports_rule_name() -> None:
    assert eligibility(ADULT, PublicSwim()).rule == "public"
    assert eligibility(WOMAN, WomenOnly()).rule == "women-only"


def test_access_types_covers_every_session_access_arm() -> None:
    # The ACCESS_TYPES silent gap: a new `SessionAccess` arm is compile-enforced at the
    # match/assert_never sites but NOT in the representative tuple — this closes that gap.
    # Members are derived from the union type itself, not hand-listed a second time.
    union_members = set(get_args(SessionAccess.__value__))
    assert {type(a) for a in REPRESENTATIVE_ACCESS} == union_members
    # And every representative yields a distinct legend entry (no arm shadows another).
    assert len({info.key for info in ACCESS_TYPES}) == len(union_members)


# --- S2: the reason-code key space -------------------------------------------------------


def _all_outcomes() -> list[ReasonCode]:
    """Every code produced by sweeping every access type against every person shape.

    The person axes are exhaustive by construction: gender is the full `Gender` enum plus
    `None`, age covers below/at/above every threshold plus `None`.
    """
    people = [
        Person(gender=g, age=a) for g in (*Gender, None) for a in (None, 8, 17, 18, 34, 59, 60, 70)
    ]
    return [eligibility(p, a).code for a in REPRESENTATIVE_ACCESS for p in people]


def test_every_reason_code_is_reachable() -> None:
    """No dead codes: a key nobody emits would sit untranslated in five catalogs forever.

    The mirror of the `REPRESENTATIVE_ACCESS` completeness test — a silent gap the compiler
    cannot see, made visible.
    """
    assert set(_all_outcomes()) == set(ReasonCode)


def test_women_only_discriminates_all_four_outcomes() -> None:
    """The reason `rule` alone could not key a message on.

    All four share `rule="women-only"` yet mean opposite things; keying on `rule` would
    render "you're welcome" for "you're not". This is why ReasonCode exists.
    """
    codes = {
        g: eligibility(Person(gender=g, age=30), WomenOnly()).code
        for g in (Gender.FEMALE, Gender.MALE, Gender.DIVERSE, None)
    }
    assert codes[Gender.FEMALE] is ReasonCode.WOMEN_ONLY_WELCOME
    assert codes[Gender.MALE] is ReasonCode.WOMEN_ONLY_EXCLUDED
    assert codes[Gender.DIVERSE] is ReasonCode.WOMEN_ONLY_CONFIRM
    assert codes[None] is ReasonCode.WOMEN_ONLY_NEEDS_GENDER
    assert len(set(codes.values())) == 4
    assert {eligibility(Person(gender=g, age=30), WomenOnly()).rule for g in codes} == {
        "women-only"
    }


def test_allowed_and_code_never_disagree() -> None:
    """A code that reads as welcoming must not carry allowed=False (and vice versa)."""
    welcoming = {
        ReasonCode.PUBLIC,
        ReasonCode.LANE_SWIM,
        ReasonCode.FAMILY,
        ReasonCode.WOMEN_ONLY_WELCOME,
        ReasonCode.SENIORS_ONLY_WELCOME,
        ReasonCode.ADULTS_ONLY_WELCOME,
    }
    people = [Person(gender=g, age=a) for g in (*Gender, None) for a in (None, 8, 34, 70)]
    for access in REPRESENTATIVE_ACCESS:
        for person in people:
            got = eligibility(person, access)
            assert got.allowed is (got.code in welcoming), (got.code, got.allowed)


def test_age_gated_codes_carry_the_threshold_as_a_param() -> None:
    """Params are what let a translation say "60+" without the number being baked into
    English prose. Every age-gated outcome carries `min_age`; the ungated ones carry none."""
    for access, code in (
        (SeniorsOnly(), ReasonCode.SENIORS_ONLY_TOO_YOUNG),
        (AdultsOnly(), ReasonCode.ADULTS_ONLY_TOO_YOUNG),
    ):
        got = eligibility(Person(gender=None, age=5), access)
        assert got.code is code
        assert got.params == {"min_age": 18 if code.startswith("adults") else 60}

    assert eligibility(Person(gender=None, age=30), PublicSwim()).params == {}


def test_club_reserved_carries_the_club_name_as_a_param() -> None:
    """The club is DATA (a German proper noun), not copy — it must reach the UI as a
    parameter so a translated sentence can place it, never as part of the message."""
    got = eligibility(Person(gender=None, age=30), ClubReserved(club="SC Zürich"))
    assert got.code is ReasonCode.CLUB_RESERVED
    assert got.params == {"club": "SC Zürich"}
    assert eligibility(Person(gender=None, age=30), ClubReserved()).params == {}


def test_the_server_no_longer_decides_the_answers_language() -> None:
    """S5: the English prose is GONE. An outcome is a code + params; only the client
    turns it into words, so the same API serves every locale."""
    got = eligibility(Person(gender=Gender.MALE, age=30), WomenOnly())
    assert got.code is ReasonCode.WOMEN_ONLY_EXCLUDED
    assert not hasattr(got, "reason")
