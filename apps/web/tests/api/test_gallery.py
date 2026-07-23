"""The dev-only component gallery (`/ui/gallery`).

Two gates: it is ABSENT in production (SWIMZH_DEV_UI off → 404) and, when the dev
flag is on, it renders every Part-2 primitive in each documented state in BOTH
themes. Because a FastAPI route is mounted for the process once registered, the
route must be gated at registration time — so each test builds a fresh app via the
`create_app` factory after setting the flag, rather than reusing the module app.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.api.gallery.router import _COMPONENTS, _THEMES
from apps.web.main import create_app

_REGISTRY_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "components" / "registry.js"
# Top-level REGISTRY keys look like `  'name': {` or `  combobox: {` (2-space indent,
# value opens a brace) — the inner `create:`/`interactive:`/`props:` keys are deeper.
_REGISTRY_KEY = re.compile(r"^ {2}(?:'([a-z-]+)'|([a-z-]+)):\s*\{\s*$", re.MULTILINE)


def _registry_names() -> set[str]:
    text = _REGISTRY_JS.read_text(encoding="utf-8")
    body = text.split("export const REGISTRY = {", 1)[1]
    return {a or b for a, b in _REGISTRY_KEY.findall(body)}


def test_gallery_components_cross_check_the_js_registry() -> None:
    """S5 F nit: the Python gallery route (`_COMPONENTS`) and the JS `REGISTRY` must
    name the SAME primitives, so a Python-only edit can't add a mount the JS cannot
    hydrate (an unhydratable dead cell), nor drop one the JS still expects. Cross-check
    the two directly — the JS-side `registry.test.js` guards the states per component;
    this guards the name SET across the language boundary."""
    python_names = {name for name, _title, _states in _COMPONENTS}
    js_names = _registry_names()
    assert js_names, "failed to parse any REGISTRY keys from registry.js"
    assert python_names == js_names, (
        f"gallery _COMPONENTS vs JS REGISTRY drift — "
        f"python-only: {python_names - js_names}; js-only: {js_names - python_names}"
    )


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
