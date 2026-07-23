"""Design-system layer gates (plan Risk #1: no-build modularity drift).

The layering tokens → components → blocks → shell is enforced mechanically here:
  * components import nothing from the blocks layer;
  * all colour lives in tokens.css — no raw hex/rgba leaks into components.css /
    blocks.css or the component JS;
  * the /static mount serves the design-system assets;
  * the `/` page is the SMALL unified shell that LINKS the token layer (the legacy
    embedded string and its `/* __TOKENS__ */` inlining machinery were deleted at S5).
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


def test_filter_toolbar_phone_breakpoints_stack_and_stretch() -> None:
    """S5 responsive contract for the FilterToolbar. There is no layout engine in the
    gate, so — mirroring the S2 board-overflow and S3 sheet contracts — assert the CSS
    PROPERTIES that make the toolbar reflow on a phone are declared:

      * a `@media (max-width: 720px)` block stacks each field full-width
        (`.toolbar__field { flex: 1 1 100% }`);
      * inside it the segmented controls stretch (`.ui-seg` full-width, options
        `flex: 1 1 0`), the DateStepper spans full-width, and the place + pool
        comboboxes fill the row (their intrinsic min-width released to 0);
      * a deeper `@media (max-width: 560px)` block tightens the strip and lets the age
        chips share the row.

    The true visual check is the human review at the S5 pause; this is the mechanical
    proxy that the phone reflow has not regressed in CSS.
    """
    blocks = (_STATIC / "blocks.css").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", blocks)
    assert "@media (max-width: 720px)" in normalized, "the toolbar needs a <=720px breakpoint"
    assert "@media (max-width: 560px)" in normalized, (
        "the toolbar needs a deeper <=560px breakpoint"
    )
    # The stack: each field spans the full row.
    assert ".toolbar__field { flex: 1 1 100%; }" in normalized, "fields must stack full-width"
    # Segmented controls stretch and their options share the row.
    assert ".toolbar__field .ui-seg { display: flex; width: 100%; }" in normalized
    assert ".toolbar__field .ui-seg__opt { flex: 1 1 0; text-align: center; }" in normalized
    # The DateStepper spans full-width.
    assert ".toolbar__field .ui-datestepper { display: flex; width: 100%; }" in normalized
    # Place + pool comboboxes fill the row (their 12rem min-width released to 0).
    assert (
        ".toolbar__field .ui-combo input, .toolbar__field .ui-place input "
        "{ flex: 1 1 auto; width: 100%; min-width: 0; }"
    ) in normalized, "the place/pool inputs must fill the row (min-width released)"


def test_every_interactive_control_has_a_focus_visible_ring() -> None:
    """A11y: every interactive control shows a visible focus ring via the shared
    `--focus-ring` token on :focus-visible (keyboard focus, never mouse). The primitive
    controls carry it in components.css; the block-level theme toggle carries it in
    blocks.css. All use `box-shadow: var(--focus-ring)` (the token is a box-shadow
    value — never mis-applied as an `outline` colour)."""
    components = (_STATIC / "components.css").read_text(encoding="utf-8")
    blocks = (_STATIC / "blocks.css").read_text(encoding="utf-8")
    norm_c = re.sub(r"\s+", " ", components)
    norm_b = re.sub(r"\s+", " ", blocks)
    # Every documented interactive primitive is in the shared focus-ring selector list.
    for selector in (
        ".ui-seg__opt:focus-visible",
        ".ui-chip:focus-visible",
        ".ui-combo input:focus-visible",
        ".ui-place input:focus-visible",
        ".ui-place__geo:focus-visible",
        ".ui-datestepper__nav:focus-visible",
        ".ui-toggle input:focus-visible",
    ):
        assert selector in norm_c, f"missing focus-visible ring for {selector}"
    assert "box-shadow: var(--focus-ring);" in norm_c, "primitives ring via box-shadow"
    # The block-level theme toggle also rings on focus-visible.
    assert ".apphdr__theme:focus-visible" in norm_b, "the theme toggle needs a focus-visible ring"
    assert "box-shadow: var(--focus-ring);" in norm_b, "the theme toggle rings via box-shadow"
    # The token is a box-shadow value, so it must NEVER be mis-applied as an outline colour.
    assert "outline: 2px solid var(--focus-ring)" not in norm_b, (
        "--focus-ring is a box-shadow value, not an outline colour"
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


def _gallery_inline_style() -> str:
    """The gallery router's inline `<style>` block (the ONE server-rendered stylesheet
    outside the static .css files). It must obey the same no-hex rule — colour via
    var(--…) only — so it is scanned alongside the static CSS/JS (S5 F nit)."""
    from apps.web.api.gallery.router import _GALLERY_PAGE

    m = re.search(r"<style>(.*?)</style>", _GALLERY_PAGE, re.DOTALL)
    assert m, "gallery page must carry an inline <style> block to scan"
    return m.group(1)


def test_no_raw_hex_or_rgba_outside_tokens_css() -> None:
    """All colour literals live in tokens.css. Component CSS, component JS, AND the
    gallery router's inline <style> use var(--…) / color-mix() / currentColor only —
    never a raw hex or rgba()."""
    offenders = []
    css_files = [p for p in _STATIC.glob("*.css") if p.name != "tokens.css"]
    for path in [*css_files, *_js_sources()]:
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if _HEX.search(line) or _RGBA.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    # The gallery router's inline <style> is server-rendered, not a static file — scan it too.
    for n, line in enumerate(_gallery_inline_style().splitlines(), 1):
        if _HEX.search(line) or _RGBA.search(line):
            offenders.append(f"gallery/router.py<style>:{n}: {line.strip()}")
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


def test_index_shell_links_the_token_layer_and_hydrator() -> None:
    """S5 retired the legacy embedded `_PAGE`/`_RENDERED_PAGE` string (which inlined
    tokens via the `/* __TOKENS__ */` marker). `/` now serves the SMALL unified shell
    that LINKS the three design-system stylesheets (tokens first) from /static and the
    app.js ES-module hydrator — the tokens still reach the page, now by <link>. This
    replaces the old injected-definition belt-and-braces check."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert '<link rel="stylesheet" href="/static/tokens.css">' in page
    assert '<link rel="stylesheet" href="/static/components.css">' in page
    assert '<link rel="stylesheet" href="/static/blocks.css">' in page
    assert '<script type="module" src="/static/js/app.js"></script>' in page
    # The legacy symbols are gone — the router no longer carries them.
    import apps.web.api.ui.router as ui_router

    assert not hasattr(ui_router, "_PAGE")
    assert not hasattr(ui_router, "_RENDERED_PAGE")
    assert not hasattr(ui_router, "_TOKENS_CSS")
