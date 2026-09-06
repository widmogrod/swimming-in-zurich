from __future__ import annotations

from fastapi.testclient import TestClient

from apps.web.main import app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Per-source provenance rides along: the session store is one offline `build`, so every
    # source is fresh from that run. A store built before the lake existed reports `[]` — an
    # honest "unknown", never a fabricated freshness.
    assert {row["source"] for row in body["sources"]} == {
        "roster",
        "prices",
        "schedules",
        "lane_plans",
    }
    assert all(row["status"] == "fresh" for row in body["sources"])
