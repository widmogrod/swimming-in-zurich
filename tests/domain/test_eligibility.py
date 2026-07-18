"""Eligibility is explainable: allowed + rule + reason for every access variant."""

from __future__ import annotations

from swimzh.domain.access import (
    ClubReserved,
    FamilyTime,
    LaneSwim,
    PublicSwim,
    SchoolReserved,
    SeniorsOnly,
    WomenOnly,
    eligibility,
)
from swimzh.domain.person import Gender, Person

ADULT = Person(gender=Gender.MALE, age=40)
WOMAN = Person(gender=Gender.FEMALE, age=40)
SENIOR = Person(gender=Gender.FEMALE, age=70)
DIVERSE = Person(gender=Gender.DIVERSE, age=40)
UNKNOWN = Person()


def test_public_lane_family_open_to_all() -> None:
    for access in (PublicSwim(), LaneSwim(), FamilyTime()):
        for person in (ADULT, WOMAN, UNKNOWN):
            result = eligibility(person, access)
            assert result.allowed is True
            assert result.reason


def test_women_only() -> None:
    assert eligibility(WOMAN, WomenOnly()).allowed is True
    assert eligibility(ADULT, WomenOnly()).allowed is False
    # Non-binary and unspecified are not silently assumed either way.
    diverse = eligibility(DIVERSE, WomenOnly())
    assert diverse.allowed is False
    assert "confirm" in diverse.reason
    unknown = eligibility(UNKNOWN, WomenOnly())
    assert unknown.allowed is False
    assert "specify gender" in unknown.reason


def test_seniors_only() -> None:
    assert eligibility(SENIOR, SeniorsOnly(min_age=60)).allowed is True
    assert eligibility(ADULT, SeniorsOnly(min_age=60)).allowed is False
    unknown_age = eligibility(Person(gender=Gender.MALE), SeniorsOnly(min_age=60))
    assert unknown_age.allowed is False
    assert "specify age" in unknown_age.reason


def test_reserved_sessions_are_not_public() -> None:
    school = eligibility(ADULT, SchoolReserved())
    assert school.allowed is False
    assert school.rule == "school-reserved"
    club = eligibility(ADULT, ClubReserved(club="SC Uster"))
    assert club.allowed is False
    assert "SC Uster" in club.reason


def test_result_reports_rule_name() -> None:
    assert eligibility(ADULT, PublicSwim()).rule == "public"
    assert eligibility(WOMAN, WomenOnly()).rule == "women-only"
