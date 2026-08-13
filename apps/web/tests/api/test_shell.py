"""S4: `/` now serves the unified two-mode app SHELL (not the four-tab page).

The shell is a small skeleton — charset + the three design-system stylesheets from the
/static mount + the block mount points + the app.js ES module. The four-tab markup
(`data-tab="find"` …) is gone from the live `/` response. The route is NOT dev-gated: it
works whether or not `SWIMZH_DEV_UI` is set, while the dev preview routes stay 404 when the
flag is off (their own tests cover the positive case).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app, create_app

_BLOCK_MOUNTS = (
    'id="app-header"',
    'id="app-toolbar"',
    'id="app-insight"',
    'id="app-board"',
    'id="app-panel"',
    'id="app-legend"',
)


def test_index_serves_the_new_unified_shell() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    page = response.text
    # A real, charset-declaring HTML document.
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert "Swimming in Zürich" in page
    # The app.js ES module is wired, and the design-system stylesheets are LINKED
    # (not inlined) from the /static mount.
    assert '<script type="module" src="/static/dist/app.js">' in page
    assert '<link rel="stylesheet" href="/static/tokens.css">' in page
    assert '<link rel="stylesheet" href="/static/components.css">' in page
    assert '<link rel="stylesheet" href="/static/blocks.css">' in page
    # Every block has its mount point.
    for mount in _BLOCK_MOUNTS:
        assert mount in page, f"missing block mount {mount}"
    # The standalone below-board StateBlocks section is GONE — closed/uncurated pools
    # now read ON the board rows, and the no-pools empty state renders inside the board
    # host (never a duplicate section beneath it).
    assert 'id="app-states"' not in page


def test_index_no_longer_serves_the_four_tab_markup() -> None:
    with TestClient(app) as client:
        page = client.get("/").text
    # The retired four-tab spine is absent from the LIVE response.
    assert "data-tab=" not in page
    assert 'data-tab="find"' not in page
    assert "Plan my week" not in page
    assert "First time here?" not in page
    # The board/legend live in the client now, not an inlined <style>/<script> wall.
    assert "<style>" not in page
    assert "weekgrid" not in page


def test_index_works_regardless_of_dev_ui_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/` is not dev-gated — it serves in production. With the dev flag OFF the preview
    routes 404, but `/` still returns the shell."""
    monkeypatch.setenv("SWIMZH_DEV_UI", "0")
    off = create_app()
    with TestClient(off) as client:
        assert client.get("/").status_code == 200
        assert client.get("/ui/gallery").status_code == 404
        assert client.get("/ui/board").status_code == 404
    monkeypatch.setenv("SWIMZH_DEV_UI", "1")
    on = create_app()
    with TestClient(on) as client:
        assert client.get("/").status_code == 200


def test_shell_language_follows_the_locale_cookie() -> None:
    """`<html lang>` is not cosmetic: screen readers take their pronunciation from it, and
    CSS `:lang()`/hyphenation key off it. Serving `lang="en"` to a Polish reader is a real
    accessibility defect — and it is why the locale lives in a cookie, which the SERVER can
    read, rather than localStorage, which it cannot."""
    with TestClient(app) as client:
        page = client.get("/", cookies={"swimzh_locale": "pl"}).text
    assert '<html lang="pl">' in page
    assert "<title>Pływanie w Zurychu</title>" in page


def test_shell_falls_back_to_accept_language_then_english() -> None:
    """A first visit has no cookie. `Accept-Language` is a HINT, so it selects the shell
    text but never redirects — a language guess must not change a shared URL."""
    with TestClient(app) as client:
        german = client.get("/", headers={"Accept-Language": "de-CH,de;q=0.9"}).text
        unknown = client.get("/", headers={"Accept-Language": "ja,ko;q=0.9"}).text
    assert '<html lang="de-CH">' in german
    assert "Schwimmen in Zürich" in german
    assert '<html lang="en">' in unknown  # unsupported → English, not a guess


def test_the_cookie_beats_accept_language() -> None:
    """An explicit choice outranks a browser hint — the same precedence the client uses."""
    with TestClient(app) as client:
        page = client.get(
            "/", cookies={"swimzh_locale": "it"}, headers={"Accept-Language": "de"}
        ).text
    assert '<html lang="it-CH">' in page
