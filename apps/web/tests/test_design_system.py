"""Design-system layer gates (plan Risk #1: no-build modularity drift).

The layering tokens → components → blocks → shell is enforced mechanically here:
  * components import nothing from the blocks layer;
  * all colour lives in tokens.css — no raw hex/rgba leaks into components.css /
    blocks.css or the component JS;
  * the /static mount serves the design-system assets;
  * the `/` page still carries an injected token DEFINITION (S0 critic-nit: a lost
    `/* __TOKENS__ */` marker must not silently break every var(--…)).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from apps.web.main import app

_STATIC = Path(__file__).resolve().parents[1] / "static"
_COMPONENTS_JS = _STATIC / "js" / "components"
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGBA = re.compile(r"\brgba?\(")


def _component_js_sources() -> list[Path]:
    """The component modules themselves — excludes *.test.js (test assertions may
    legitimately mention a hex regex) and the fake-DOM test helper."""
    return [
        p
        for p in _COMPONENTS_JS.glob("*.js")
        if not p.name.endswith(".test.js") and p.name != "_fakedom.js"
    ]


def test_components_do_not_import_the_blocks_layer() -> None:
    """Layer rule: a primitive may not reach up into the blocks layer."""
    offenders = []
    for path in _COMPONENTS_JS.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith(("import ", "export ")) and "blocks" in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, f"components import the blocks layer: {offenders}"


def test_no_raw_hex_or_rgba_outside_tokens_css() -> None:
    """All colour literals live in tokens.css. Component CSS and component JS use
    var(--…) / color-mix() / currentColor only — never a raw hex or rgba()."""
    offenders = []
    css_files = [p for p in _STATIC.glob("*.css") if p.name != "tokens.css"]
    for path in [*css_files, *_component_js_sources()]:
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if _HEX.search(line) or _RGBA.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, f"raw colour literals outside tokens.css: {offenders}"


def test_tokens_css_is_where_colour_actually_lives() -> None:
    """Guard against a vacuous grep: tokens.css really does carry the raw palette
    (so the 'outside tokens.css' assertion above is meaningful)."""
    tokens = (_STATIC / "tokens.css").read_text(encoding="utf-8")
    assert _HEX.search(tokens)
    # The S1 real eligibility tokens carry the MUTED Part-1 values, not alarm red.
    assert "--badge-in: #1a9d54" in tokens
    assert "--badge-chk: #b7791f" in tokens
    assert "--badge-no: #8a909c" in tokens


def test_static_mount_serves_the_design_system_assets() -> None:
    with TestClient(app) as client:
        css = client.get("/static/tokens.css")
        js = client.get("/static/js/components/segmentedcontrol.js")
    assert css.status_code == 200
    assert "--ctl-h: 36px" in css.text
    assert js.status_code == 200
    assert "createSegmentedControl" in js.text


def test_index_page_carries_an_injected_token_definition() -> None:
    """S0 critic-nit: the `/` page inlines tokens.css via the `/* __TOKENS__ */`
    marker; a lost marker would silently break every var(--…). Assert a known token
    DEFINITION is present in the rendered page (the router also raises if the marker
    is missing, so this is belt-and-braces)."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert "--ctl-h: 36px" in page
    assert "--accent: #0e8ea0" in page
