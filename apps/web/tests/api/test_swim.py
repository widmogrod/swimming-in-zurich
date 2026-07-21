"""The swim endpoint over the real curated data — the eligibility differentiator must
survive the whole HTTP round-trip."""

from __future__ import annotations

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


def test_options_carry_price_and_provenance() -> None:
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
