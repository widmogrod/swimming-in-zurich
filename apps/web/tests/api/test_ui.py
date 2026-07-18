from __future__ import annotations

from fastapi.testclient import TestClient

from apps.web.main import app


def test_index_serves_html_page() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Where can I swim" in response.text
