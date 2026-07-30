"""The swim endpoint over the real curated data — the eligibility differentiator must
survive the whole HTTP round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app

# Monday 2026-09-14 20:30: City Lehrschwimmbecken runs a women-only session 20:00–22:00.
MONDAY_EVENING = "2026-09-14T20:30"


def test_woman_sees_women_only_session() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" in accesses


def test_man_excluded_from_women_only_session() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "male", "age": 34})
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" not in accesses


def test_options_carry_price_and_provenance(
    offline_gold_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read against the PRE-SCRAPE store (curated City/Oerlikon options, each with a curated
    # `valid_as_of`). The atomic `build` folds in scraped schedules for the schedule-less curated
    # pools (Bläsi/Leimbach/…), which surface as options that keep their curated source-less
    # provenance — so `all(valid_as_of)` is a property of the curated-only store, pinned here.
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(offline_gold_db))
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    assert any(o["price"] for o in options)
    assert all(o["valid_as_of"] for o in options)


def test_options_expose_length_kind_and_source() -> None:
    """S1: the glance badge needs basin length + facility kind, and the ⓘ stamp needs the
    provenance source/curated flag, surfaced through the swim service into OptionOut."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    for o in options:
        assert set(o) >= {"length_m", "kind", "source", "curated"}
        assert isinstance(o["kind"], str) and o["kind"]
        assert isinstance(o["source"], str) and o["source"]
        assert isinstance(o["curated"], bool)
        assert o["length_m"] is None or isinstance(o["length_m"], (int, float))
    # City's curated basins carry real dimensions (50m / 20m), so at least one badge is real.
    assert any(o["length_m"] for o in options)


def test_options_expose_lane_count_and_degrade_when_unknown() -> None:
    """S2: the badge's "N lane" sub-line needs a per-basin lane count on OptionOut. City's
    50m basin carries a real lane count (6 Bahnen); the teaching pool has none, so lanes
    must degrade to None rather than being invented."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    for o in options:
        assert "lanes" in o
        assert o["lanes"] is None or isinstance(o["lanes"], int)
    # Basin *names* collide across facilities (City and Oerlikon both have a "50m-Becken",
    # only City's stating 6 Bahnen), so assert over sets rather than a name-keyed dict that
    # would collapse them order-dependently.
    city_50m = {o["lanes"] for o in options if o["basin"] == "50m-Becken"}
    assert 6 in city_50m  # City's real lane count surfaces
    lehrbecken = {o["lanes"] for o in options if o["basin"] == "Lehrschwimmbecken"}
    assert lehrbecken == {None}  # unknown degrades to None, never invented


def test_invalid_gender_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "other"})
    assert response.status_code == 400


def test_missing_at_defaults_to_server_time() -> None:
    # `at` is optional: a bare /swim answers using server time (Europe/Zurich) instead of
    # 422-ing. The answer shape is the same as an explicit `at`.
    with TestClient(app) as client:
        response = client.get("/swim")
    assert response.status_code == 200
    body = response.json()
    assert {"options", "statuses", "warnings", "notices"} <= set(body)


def test_lat_without_lon_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "lat": 47.37})
    assert response.status_code == 400


def test_future_year_surfaces_calendar_warning() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": "2030-03-12T18:00", "gender": "male", "age": 40}
        )
    assert response.status_code == 200
    assert any("calendar data not available" in w for w in response.json()["warnings"])


# --- S2: machine-readable codes on the wire (additive; prose stays until S5) --------------


def _women_only_option(client: TestClient, gender: str) -> dict[str, object]:
    """The City women-only session as seen by `gender`, with eligibility annotated."""
    response = client.get(
        "/swim",
        params={"at": MONDAY_EVENING, "gender": gender, "age": 34, "eligible_only": "false"},
    )
    assert response.status_code == 200
    options: list[dict[str, object]] = response.json()["options"]
    women = [o for o in options if o["access"] == "WomenOnly"]
    assert women, f"no WomenOnly option for gender={gender}"
    return women[0]


def test_options_carry_a_reason_code_and_no_prose() -> None:
    """S5: the English `reason` is GONE from the wire.

    The server states WHICH outcome; only the client turns that into words, so one API
    serves every locale and no response is implicitly English.
    """
    with TestClient(app) as client:
        option = _women_only_option(client, "female")
    assert option["reason_code"] == "women_only_welcome"
    assert "reason" not in option


def test_the_reason_code_discriminates_what_rule_could_not() -> None:
    """The whole point of S2: female and male see the SAME access type and the same
    `rule`, but opposite outcomes. A client keying on the access type alone would render
    "you're welcome" to someone who is excluded."""
    with TestClient(app) as client:
        welcome = _women_only_option(client, "female")
        excluded = _women_only_option(client, "male")
    assert welcome["access"] == excluded["access"] == "WomenOnly"
    assert welcome["reason_code"] == "women_only_welcome"
    assert excluded["reason_code"] == "women_only_excluded"
    assert welcome["eligible"] is True
    assert excluded["eligible"] is False


def test_reason_params_carry_interpolation_values_not_baked_prose() -> None:
    """Any code whose sentence mentions a number/name must ship that value separately, or
    a translation cannot place it. Params are always present (possibly empty)."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "eligible_only": "false"})
    for option in response.json()["options"]:
        assert isinstance(option["reason_params"], dict)
        if option["reason_code"].startswith(("seniors_only", "adults_only")):
            assert "min_age" in option["reason_params"]


def test_statuses_carry_codes_and_no_mixed_language_prose() -> None:
    """`detail` used to be English in one branch and curated German in the other — the
    seam the whole plan existed to close. It is gone; the codes replace it."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "eligible_only": "false"})
    statuses = response.json()["statuses"]
    assert statuses, "expected at least one closed / schedule-less facility"
    for status in statuses:
        assert status["detail_code"] in {"closed_reason", "awaiting_scrape", "no_source"}
        assert "detail" not in status, "the mixed-language prose is retired (S5)"
        if status["detail_code"] == "closed_reason":
            # S4: WHICH closure, as a code the client can translate.
            assert status["closure_code"]


def test_access_types_key_is_sufficient_to_render_without_server_prose() -> None:
    """S2 asserts `/access-types` needs no new field: `key` already identifies each type,
    so the client can render label+description from its own catalog. The prose here is
    what S5 removes."""
    with TestClient(app) as client:
        types = client.get("/access-types").json()["types"]
    keys = [t["key"] for t in types]
    assert len(keys) == len(set(keys)), "keys must be unique to be a message id"
    assert set(keys) == {
        "public",
        "lane-swim",
        "family",
        "women-only",
        "seniors-only",
        "school-reserved",
        "club-reserved",
        "adults-only",
    }
