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


def _js_sources() -> list[Path]:
    """Every design-system JS module — top-level (timescale/filterstate/eligibility),
    the primitives under components/, and the blocks under blocks/. Excludes *.test.js
    (test assertions may legitimately mention a hex regex) and the fake-DOM helper. All
    colour must resolve through tokens.css (var()/currentColor), never a raw hex/rgba."""
    js_dir = _STATIC / "js"
    sources: list[Path] = []
    for pattern in ("*.js", "components/*.js", "blocks/*.js"):
        sources.extend(
            p
            for p in js_dir.glob(pattern)
            if not p.name.endswith(".test.js") and p.name != "_fakedom.js"
        )
    return sources


def test_board_grid_guarantees_overflow_containment() -> None:
    """The RibbonBoard's wide canvas MUST scroll inside its card, never push the page
    sideways (the exact bug that bit the prototype). There is no layout engine in the
    test env, so `scrollWidth`/`clientWidth` are meaningless here; instead we assert the
    CSS PROPERTIES that GUARANTEE containment are declared on the board:

      * the canvas grid column is `minmax(0, 1fr)` (min=0 lets it shrink below content)
        — NOT `1fr` (min=auto=max-content would blow the column out to the page);
      * the scroll cell is `overflow-x: auto`;
      * the canvas track inside it is `width: max-content`.

    The true visual/browser check is deferred to the human review at the S3 pause; this
    is the mechanical proxy that the containment contract has not regressed in CSS.
    """
    blocks = (_STATIC / "blocks.css").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", blocks)
    assert "minmax(0, 1fr)" in normalized, "board canvas column must be minmax(0,1fr)"
    assert "grid-template-columns: [label] var(--board-label-w) [canvas] minmax(0, 1fr)" in (
        normalized
    ), "the board row grid must place the canvas in a minmax(0,1fr) column"
    assert "overflow-x: auto" in normalized, "the scroll cell must be overflow-x:auto"
    assert "width: max-content" in normalized, "the canvas track must be width:max-content"
    # And the failure mode is absent: the canvas column is never a bare `1fr`.
    assert "[canvas] 1fr" not in normalized, "a bare 1fr canvas column would overflow the page"


def test_detail_panel_bottom_sheet_responsive_contract() -> None:
    """The DetailPanel is a sticky side panel ≥1060px and a slide-up bottom SHEET
    below it (transform + a dimming backdrop), with both motions frozen under
    prefers-reduced-motion. There is no layout engine in the gate, so — mirroring the
    S2 board overflow-contract — assert the CSS PROPERTIES that guarantee the sheet
    behaviour are declared:

      * a `@media (max-width: 1060px)` block exists;
      * inside it the sheet slides via `transform: translateY(100%)` (closed) and the
        `.is-open` state resets it to `translateY(0)`;
      * a `.detail__backdrop` dims the page (`position: fixed`);
      * a `@media (prefers-reduced-motion: reduce)` block freezes the transition.

    The true visual/browser check is the human review at the S3 pause; this is the
    mechanical proxy that the sheet contract has not regressed in CSS.
    """
    blocks = (_STATIC / "blocks.css").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", blocks)
    assert "@media (max-width: 1060px)" in normalized, "the sheet needs a <1060px breakpoint"
    assert "@media (min-width: 1060px)" in normalized, "the side panel needs a >=1060px branch"
    assert "transform: translateY(100%)" in normalized, "the closed sheet must be off-screen"
    assert "transform: translateY(0)" in normalized, "the open sheet must slide into view"
    assert ".detail__backdrop" in normalized, "the sheet needs a dimming backdrop"
    assert "position: fixed" in normalized, "the sheet + backdrop must be fixed-positioned"
    assert "@media (prefers-reduced-motion: reduce)" in normalized, (
        "the slide + backdrop fade must be frozen under reduced motion"
    )


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
    for path in [*css_files, *_js_sources()]:
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
