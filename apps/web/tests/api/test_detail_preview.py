"""The dev-only DetailPanel + LaneGantt preview (`/ui/detail`).

Two gates: ABSENT in production (SWIMZH_DEV_UI off → 404), and when the dev flag is
on it renders the server scaffolding the client hydrates against — the board + panel
mount points, the two inlined fixtures (a `/swim` day for the board and a
`/pools/{id}` capture WITH owner-named reserved lanes for the panel + Gantt), and the
block stylesheet + ES module. The cursor-sync + render is a browser concern
(exercised by the JS unit tests via the headless fake DOM); here we assert the
server-rendered contract.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.web.main import create_app


def test_detail_preview_absent_when_dev_ui_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "0")
    with TestClient(create_app()) as client:
        assert client.get("/ui/detail").status_code == 404


def test_detail_preview_present_when_dev_ui_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        response = client.get("/ui/detail")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_detail_preview_renders_mounts_and_block_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        page = client.get("/ui/detail").text
    assert 'id="detail-board"' in page  # the board the cursor is driven FROM
    assert 'id="detail-panel"' in page  # the panel + Gantt
    assert '<link rel="stylesheet" href="/static/blocks.css">' in page
    assert '<script type="module" src="/static/js/blocks/detail_preview.js"></script>' in page


def test_detail_preview_inlines_a_pool_fixture_with_owner_named_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The panel + Gantt hydrate from a real `/pools/{id}` capture that carries lane
    panels with owner-named reserved segments (the S3 acceptance data)."""
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    with TestClient(create_app()) as client:
        page = client.get("/ui/detail").text
    assert 'id="detail-pool-data"' in page
    start = page.index('id="detail-pool-data"')
    open_tag_end = page.index(">", start) + 1
    close_tag = page.index("</script>", open_tag_end)
    pool = json.loads(page[open_tag_end:close_tag].replace("<\\/", "</"))
    assert pool["lane_panels"], "the pool fixture must carry lane panels"
    owners = {
        seg["owner"]
        for panel in pool["lane_panels"]
        for strip in panel["panel"]["day_view"]["strips"]
        for seg in strip["segments"]
        if seg["owner"]
    }
    assert owners, "the Gantt needs owner-named reserved lanes"
