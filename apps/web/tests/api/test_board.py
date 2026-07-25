"""The dev-only RibbonBoard preview (`/ui/board`).

Two gates: ABSENT in production (SWIMZH_DEV_UI off → 404), and when the dev flag is
on it renders the server scaffolding both modes hydrate against — the two mount
points, the two inlined `/swim` fixtures, and the block stylesheet + ES module. The
canvas render itself is a browser concern (exercised by the JS unit tests via the
headless fake DOM); here we assert the server-rendered contract.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.web.main import create_app


def test_board_preview_absent_when_dev_ui_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "0")
    with TestClient(create_app()) as client:
        assert client.get("/ui/board").status_code == 404


def test_board_preview_present_when_dev_ui_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        response = client.get("/ui/board")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_board_preview_renders_both_mode_mounts_and_the_block_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        page = client.get("/ui/board").text
    # Day + Pool mount points the client hydrates.
    assert 'id="board-day"' in page
    assert 'id="board-pool"' in page
    # The block layer's stylesheet + the board ES module are linked from /static.
    assert '<link rel="stylesheet" href="/static/blocks.css">' in page
    assert '<script type="module" src="/static/dist/blocks/board_preview.js"></script>' in page


def test_board_preview_inlines_the_swim_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    """The preview inlines the SAME fixtures the JS unit tests assert against, so the
    two modes render real captured `/swim` shapes."""
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        page = client.get("/ui/board").text
    assert 'id="board-day-data"' in page
    assert 'id="board-week-data"' in page
    # The inlined day fixture parses and carries the states S2 must render.
    start = page.index('id="board-day-data"')
    open_tag_end = page.index(">", start) + 1
    close_tag = page.index("</script>", open_tag_end)
    day = json.loads(page[open_tag_end:close_tag].replace("<\\/", "</"))
    assert any(o["lane_timeline"] for o in day["options"])  # a filled-ribbon option
    assert any(not o["lane_timeline"] for o in day["options"])  # a "not published" option
    assert any(s["status"] == "closed" for s in day["statuses"])  # a closed ribbon
    assert any(s["status"] == "uncurated" for s in day["statuses"])  # a ghost ribbon
