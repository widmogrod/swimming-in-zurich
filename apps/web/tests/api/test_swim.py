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


def test_invalid_gender_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "other"})
    assert response.status_code == 400


def test_missing_at_is_422() -> None:
    with TestClient(app) as client:
        response = client.get("/swim")
    assert response.status_code == 422


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
