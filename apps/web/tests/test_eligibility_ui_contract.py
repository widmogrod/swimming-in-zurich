"""The UI's eligibility badge must say what the SERVER decided — a generated contract.

`apps/web/static/js/eligibility.js` re-implements `swimzh.domain.access.eligibility` in the
browser, because the badge has to react to the gender/age controls without a round-trip.
Two implementations of one rule drift, and they did: the JS `eligForAccess` ended with
*"Unknown / new access type: default to open"*, so the moment S1 added `GirlsOnly` the board
painted ✓ on a girls-only session that `/swim` had already refused — the UI contradicting
both the domain and its own pool ranking (which reads the server's `eligible`).

The fix is not prose. This module GENERATES `fixtures/eligibility_contract.json` from the
Python `eligibility()` itself and asserts the committed file still matches; `eligibility.test.js`
replays the same file through `eligForAccess`. Neither side can move without the other.

Regenerate after a deliberate domain change::

    SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT=1 uv run pytest \
        apps/web/tests/test_eligibility_ui_contract.py

The server answers `allowed: bool` + a `ReasonCode`; the UI has three marks. `_ui_state`
below is the ONE place that translation lives:

    allowed=True                  -> 'in'   (✓ you may attend)
    allowed=False, a hard denial  -> 'no'   (✕ you may not)
    allowed=False, anything else  -> 'chk'  (? check with the pool — NEVER merged with ✕)
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app
from swimzh.domain.access import (
    REPRESENTATIVE_ACCESS,
    AdultsOnly,
    EligibilityResult,
    GenderDiverse,
    ReasonCode,
    SeniorsOnly,
    SessionAccess,
    eligibility,
)
from swimzh.domain.person import Gender, Person

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "eligibility_contract.json"
_REGENERATE = os.environ.get("SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT") == "1"

#: `allowed=False` outcomes that genuinely EXCLUDE the person — the ✕ mark.
_HARD_DENIAL: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.WOMEN_ONLY_EXCLUDED,
        ReasonCode.SENIORS_ONLY_TOO_YOUNG,
        ReasonCode.ADULTS_ONLY_TOO_YOUNG,
        ReasonCode.SCHOOL_RESERVED,
        ReasonCode.CLUB_RESERVED,
        ReasonCode.GIRLS_ONLY_EXCLUDED,
        ReasonCode.GENDER_DIVERSE_TOO_YOUNG,
    }
)

#: `allowed=False` outcomes that are NOT determinable — the ? mark. Listed rather than
#: derived by complement so a new code has to be classified by a human, not defaulted.
_NOT_DETERMINABLE: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.WOMEN_ONLY_CONFIRM,
        ReasonCode.WOMEN_ONLY_NEEDS_GENDER,
        ReasonCode.SENIORS_ONLY_NEEDS_AGE,
        ReasonCode.ADULTS_ONLY_NEEDS_AGE,
        ReasonCode.GIRLS_ONLY_CONFIRM,
        ReasonCode.GIRLS_ONLY_NEEDS_GENDER,
        ReasonCode.GENDER_DIVERSE_CONFIRM,
        ReasonCode.ACCOMPANIED_CHILDREN_CONFIRM,
    }
)

#: `allowed=True` outcomes — the ✓ mark, listed only so the partition below is total.
_WELCOME: frozenset[ReasonCode] = frozenset(set(ReasonCode) - _HARD_DENIAL - _NOT_DETERMINABLE)

# The `/swim` gender query values, exactly as the UI's filter emits them.
_GENDERS: tuple[tuple[str, Gender | None], ...] = (
    ("", None),
    ("female", Gender.FEMALE),
    ("male", Gender.MALE),
    ("diverse", Gender.DIVERSE),
)
# Ages that straddle every published bound AND sit exactly ON it: unknown, child, then the
# (bound-1, bound) pair for each of the three thresholds (16 gender-diverse, 18 adults,
# 60 seniors), plus a plain adult. The ON-threshold values are the point: without 16/18/60
# a browser-side `age > threshold` where the domain says `>=` would satisfy every other row
# in this matrix and still deny an 18-year-old an adults-only session.
_AGES: tuple[int | None, ...] = (None, 8, 15, 16, 17, 18, 40, 59, 60, 65)

#: The PARAMETERISED arms at a bound that is NOT their dataclass default.
#:
#: `REPRESENTATIVE_ACCESS` hands the legend one instance per access type, so every case the
#: contract used to carry was drawn at `SeniorsOnly(60)`, `AdultsOnly(18)`,
#: `GenderDiverse(16)`. A client that hardcodes those three numbers — `eligibility.js` did
#: exactly that, and says so at length — then satisfies all 440 cells while disagreeing with
#: the server about every session whose page publishes a different bound. Live data already
#: exercises this: `AdultsOnly(min_age=18)` is what the scraper happens to emit today, but
#: nothing pins it there.
#:
#: Each arm appears at default ± 1, so a client reading the bound from `access_params` passes
#: and a client reading it from a constant fails on both sides of its own threshold.
_PARAMETERISED_ACCESS: tuple[SessionAccess, ...] = (
    SeniorsOnly(min_age=59),
    SeniorsOnly(min_age=61),
    AdultsOnly(min_age=17),
    AdultsOnly(min_age=19),
    GenderDiverse(min_age=15),
    GenderDiverse(min_age=17),
)

#: Every access instance the contract covers: one per type for the legend, plus the
#: off-default parameterised arms above.
_CONTRACT_ACCESS: tuple[SessionAccess, ...] = REPRESENTATIVE_ACCESS + _PARAMETERISED_ACCESS


def _ui_state(result: EligibilityResult) -> str:
    if result.allowed:
        return "in"
    return "no" if result.code in _HARD_DENIAL else "chk"


def _matrix() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for access in _CONTRACT_ACCESS:
        # The arm's OWN fields, exactly as the iOS export writes them into
        # `session.access_params` (`_access_doc` in `etl/ios_export.py`). A client that reads
        # the bound from here agrees with the server for any bound a page publishes; one that
        # reads it from a constant only agrees by luck.
        params = dataclasses.asdict(access)
        for label, gender in _GENDERS:
            for age in _AGES:
                result = eligibility(Person(gender=gender, age=age), access)
                cases.append(
                    {
                        "access": type(access).__name__,
                        "access_params": params,
                        "gender": label,
                        "age": age,
                        "allowed": result.allowed,
                        "code": str(result.code),
                        "ui": _ui_state(result),
                    }
                )
    return cases


def test_every_reason_code_is_classified_as_one_ui_mark() -> None:
    """A new `ReasonCode` must be given a mark here, not silently inherit one.

    The three buckets partition the enum: overlapping would make `_ui_state` ambiguous, and
    a gap would mean an outcome the UI has never been told how to draw.
    """
    assert not (_HARD_DENIAL & _NOT_DETERMINABLE)
    assert set(ReasonCode) == _HARD_DENIAL | _NOT_DETERMINABLE | _WELCOME
    # Every "welcome" code really is one — the bucket is a complement, so pin it.
    refusals = ("_excluded", "_too_young", "_confirm", "_needs_gender", "_needs_age")
    for code in _WELCOME:
        assert not code.endswith(refusals), code


def test_the_committed_contract_matches_the_domain() -> None:
    """The fixture the browser replays is still what `eligibility()` decides."""
    cases = _matrix()
    if _REGENERATE:
        _FIXTURE.write_text(
            json.dumps(
                {
                    "_note": (
                        "GENERATED from swimzh.domain.access.eligibility by "
                        "apps/web/tests/test_eligibility_ui_contract.py — do NOT hand-edit. "
                        "Replayed against apps/web/static/js/eligibility.js by "
                        "apps/web/static/js/eligibility.test.js AND against SwimZHKit by "
                        "apps/ios/Tests/SwimZHKitTests/EligibilityContractTests.swift, so the "
                        "browser badge, the iOS badge and the server verdict cannot drift. "
                        "Each case carries the access arm's OWN fields (`access_params`), so a "
                        "client must read the published bound rather than hardcode a default. "
                        "Regenerate with SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT=1."
                    ),
                    "cases": cases,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    committed = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert committed["cases"] == cases, (
        "the generated eligibility contract is stale; regenerate with "
        "SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT=1 uv run pytest "
        "apps/web/tests/test_eligibility_ui_contract.py"
    )


def test_the_contract_covers_every_access_type() -> None:
    committed = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    covered = {c["access"] for c in committed["cases"]}
    assert covered == {type(a).__name__ for a in REPRESENTATIVE_ACCESS}
    # The three kinds this plan added, named so a silent drop is loud.
    assert {"GirlsOnly", "GenderDiverse", "AccompaniedChildren"} <= covered


def test_the_contract_pins_the_parameterised_arms_off_their_defaults() -> None:
    """The three arms whose bound is a FIELD appear at bounds that are not the default.

    Without this, a client can hardcode 60/18/16 — as `eligibility.js` documented itself
    doing — and replay all 440 old cells green while contradicting the server on the first
    page that publishes a different number. The assertion is on the committed file, not on
    `_matrix()`, so a regenerated fixture that lost `access_params` fails here.
    """
    committed = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    bounds: dict[str, set[int]] = {}
    for case in committed["cases"]:
        assert "access_params" in case, case
        min_age = case["access_params"].get("min_age")
        if min_age is not None:
            bounds.setdefault(case["access"], set()).add(min_age)
    assert bounds == {
        "SeniorsOnly": {59, 60, 61},
        "AdultsOnly": {17, 18, 19},
        "GenderDiverse": {15, 16, 17},
    }

    # And the bound is what actually decides: the same person is welcome at one and refused
    # at the next, which is the behaviour a constant cannot reproduce.
    def mark(access: str, min_age: int, age: int) -> str:
        found = [
            c
            for c in committed["cases"]
            if c["access"] == access
            and c["access_params"].get("min_age") == min_age
            and c["age"] == age
            and c["gender"] == ""
        ]
        assert len(found) == 1, (access, min_age, age)
        return str(found[0]["ui"])

    assert mark("AdultsOnly", 17, 17) == "in"
    assert mark("AdultsOnly", 19, 18) == "no"
    assert mark("SeniorsOnly", 59, 59) == "in"
    assert mark("SeniorsOnly", 61, 60) == "no"
    assert mark("GenderDiverse", 15, 15) == "chk"
    assert mark("GenderDiverse", 17, 16) == "no"


def test_the_new_kinds_never_read_as_welcome() -> None:
    """None of the three ever yields ✓ — that is the harm the plan exists to fix."""
    for case in _matrix():
        if case["access"] in {"GirlsOnly", "GenderDiverse", "AccompaniedChildren"}:
            assert case["ui"] != "in", case


# --------------------------------------------------------------------------------------
# The named harm, end to end: aemtler's Thursday girls-only session.
# --------------------------------------------------------------------------------------

# Thursday 2026-09-17 18:00 — inside the 17:15–19:00 session published "für Mädchen".
_AEMTLER_THURSDAY = "2026-09-17T18:00"
_AEMTLER_SESSION = Path(__file__).resolve().parent / "fixtures" / "aemtler_girls_only.json"


def _girls_only_option(params: dict[str, str | int]) -> dict[str, Any] | None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": _AEMTLER_THURSDAY, **params})
    assert response.status_code == 200, response.text
    options: list[dict[str, Any]] = response.json()["options"]
    for option in options:
        if option["facility_id"] == "schulschwimmanlage-aemtler" and option["start"] == "17:15":
            return option
    return None


def test_aemtler_thursday_is_a_girls_only_session_the_server_refuses_a_man() -> None:
    # `eligible_only=false` is what the UI always sends (api.ts) — on the API DEFAULT the
    # session vanishes instead of rendering as "check with the pool" (a recorded tension).
    full = _girls_only_option({"gender": "male", "age": 40, "eligible_only": "false"})
    assert full is not None, "aemtler's Thursday 17:15 session is missing from /swim"
    # `valid_as_of` is the BUILD date, so it moves every day — asserted for shape, then
    # dropped from the committed capture rather than making the fixture expire overnight.
    assert isinstance(full["valid_as_of"], str) and full["valid_as_of"]
    option = {k: v for k, v in full.items() if k != "valid_as_of"}
    assert option["access"] == "GirlsOnly"
    assert option["end"] == "19:00"
    assert option["eligible"] is False
    assert option["reason_code"] == str(ReasonCode.GIRLS_ONLY_EXCLUDED)

    if _REGENERATE:
        _AEMTLER_SESSION.write_text(
            json.dumps(
                {
                    "_note": (
                        "GENERATED by apps/web/tests/test_eligibility_ui_contract.py from a real "
                        "offline `swimzh build` + /swim round-trip — do NOT hand-edit. It is the "
                        "one session named in the plan's Context: aemtler, Thursday 17:15-19:00, "
                        "published 'für Mädchen'. blocks/board.test.ts replays it through the "
                        "board's row badge so the UI is proven, not just the API."
                    ),
                    "viewer": {"gender": "male", "age": 40},
                    "option": option,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    committed = json.loads(_AEMTLER_SESSION.read_text(encoding="utf-8"))
    assert committed["option"] == option, (
        "the committed aemtler session fixture is stale; regenerate with "
        "SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT=1"
    )


@pytest.mark.parametrize("gender", ["male", "diverse"])
def test_the_api_default_hides_the_girls_only_session_rather_than_offering_it(gender: str) -> None:
    """`eligible_only` defaults to true, so the excluded viewer never sees it at all — the
    one thing that must never happen is seeing it presented as attendable."""
    assert _girls_only_option({"gender": gender, "age": 40}) is None
