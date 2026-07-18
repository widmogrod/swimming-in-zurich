"""The /pools and /access-types endpoints over the committed catalog."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.web.main import app


def test_pools_lists_all_categories() -> None:
    with TestClient(app) as client:
        response = client.get("/pools")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 50
    # every listed pool has an official link and a kind
    assert all(p["url"] for p in body["pools"])
    assert {"indoor", "outdoor", "lake"} <= set(body["kinds"])


def test_pools_filter_by_kind() -> None:
    with TestClient(app) as client:
        response = client.get("/pools", params={"kind": "indoor"})
    assert response.status_code == 200
    pools = response.json()["pools"]
    assert pools and all(p["kind"] == "indoor" for p in pools)


def test_pools_invalid_kind_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/pools", params={"kind": "spaceship"})
    assert response.status_code == 400


def test_access_types_explained() -> None:
    with TestClient(app) as client:
        response = client.get("/access-types")
    assert response.status_code == 200
    types = {t["key"]: t for t in response.json()["types"]}
    assert "women-only" in types
    assert types["women-only"]["description"]
    assert "school-reserved" in types
