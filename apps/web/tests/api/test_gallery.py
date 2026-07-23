"""The dev-only component gallery (`/ui/gallery`).

Two gates: it is ABSENT in production (SWIMZH_DEV_UI off → 404) and, when the dev
flag is on, it renders every Part-2 primitive in each documented state in BOTH
themes. Because a FastAPI route is mounted for the process once registered, the
route must be gated at registration time — so each test builds a fresh app via the
`create_app` factory after setting the flag, rather than reusing the module app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.web.api.gallery.router import _COMPONENTS, _THEMES
from apps.web.main import create_app


def test_gallery_absent_when_dev_ui_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "0")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/ui/gallery").status_code == 404


def test_gallery_present_when_dev_ui_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ui/gallery")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_gallery_renders_every_primitive_in_every_state_in_both_themes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/ui/gallery").text

    # Both theme panels are present (dual light/dark, no JS needed to see both).
    for theme in _THEMES:
        assert f'data-theme="{theme}"' in page
    assert "light" in _THEMES and "dark" in _THEMES  # the documented pair

    # Every primitive appears, and every documented state has a mount in EACH theme.
    for name, _title, states in _COMPONENTS:
        assert f'data-component="{name}"' in page
        for state in states:
            marker = f'data-component="{name}" data-state="{state}"'
            # one mount per theme panel
            assert page.count(marker) == len(_THEMES), f"{name}/{state}"

    # Total mounts == (sum of states) × themes — no state silently dropped.
    total_states = sum(len(states) for _n, _t, states in _COMPONENTS)
    assert page.count('class="gallery-item"') == total_states * len(_THEMES)


def test_gallery_links_static_design_system_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gallery is the first consumer of the /static mount: it <link>s the token
    + component stylesheets and loads the ES-module hydrator from /static."""
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/ui/gallery").text
    assert '<link rel="stylesheet" href="/static/tokens.css">' in page
    assert '<link rel="stylesheet" href="/static/components.css">' in page
    assert '<script type="module" src="/static/js/components/gallery.js"></script>' in page
