"""The dev-only component gallery (`/ui/gallery`).

Renders every Part-2 primitive in each documented state, inside a LIGHT panel and
a DARK panel (both themes visible at once), for visual review of the design
system. It is a *dev* surface: `main.create_app` registers this router only when
`SWIMZH_DEV_UI` is set (read in `config.py`), so the route is absent in production.

The page is a thin server shell: it `<link>`s the token + component stylesheets
and `<script type="module">`s the gallery hydrator from the `/static` mount, then
lays out one empty mount per (component × state). The client
(`static/js/components/gallery.js`) walks those mounts and hydrates each via the
component registry. The server owns WHICH primitives/states are rendered
(`_COMPONENTS`); the JS owns how each state is realised.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# (data-component token, human title, documented states). The state tokens are
# consumed by the JS registry's props(state); keep them in sync with
# static/js/components/registry.js (registry.test.js asserts the pairing).
_COMPONENTS: list[tuple[str, str, list[str]]] = [
    ("segmented-control", "SegmentedControl", ["default", "selected", "disabled"]),
    ("chip-group", "ChipGroup", ["default", "selected", "disabled"]),
    ("combobox", "Combobox", ["default", "selected", "empty", "disabled"]),
    ("place-typeahead", "PlaceTypeahead", ["default", "empty", "disabled"]),
    ("toggle", "Toggle", ["default", "selected", "disabled"]),
    ("date-stepper", "DateStepper", ["default", "disabled"]),
    ("state-pill", "StatePill", ["open", "opens-later", "closed", "unknown"]),
    ("eligibility-badge", "EligibilityBadge", ["in", "chk", "no"]),
    ("length-lanes-badge", "LengthLanesBadge", ["default", "empty"]),
    ("provenance-stamp", "ProvenanceStamp", ["curated", "illustrative"]),
    ("icon-set", "IconSet", ["default"]),
]

_THEMES = ("light", "dark")


def _mount(name: str, state: str) -> str:
    return (
        f'<div class="gallery-item" data-component="{name}" data-state="{state}">'
        f'<span class="gallery-item__tag">{state}</span></div>'
    )


def _group(name: str, title: str, states: list[str]) -> str:
    items = "".join(_mount(name, s) for s in states)
    return (
        f'<section class="gallery-group" data-component="{name}">'
        f"<h3>{title}</h3>"
        f'<div class="gallery-items">{items}</div>'
        f"</section>"
    )


def _panel(theme: str) -> str:
    groups = "".join(_group(name, title, states) for name, title, states in _COMPONENTS)
    return (
        f'<section class="gallery-panel" data-theme="{theme}">'
        f"<h2>{theme.title()} theme</h2>{groups}</section>"
    )


def _render_page() -> str:
    panels = "".join(_panel(t) for t in _THEMES)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Component gallery · Swimming in Zürich</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/components.css">
<style>
  body {{ font-family: var(--f); background: var(--bg); color: var(--ink);
    margin: 0; padding: var(--s5); }}
  h1 {{ font-size: var(--fs-title); font-weight: var(--fw-title); margin: 0 0 var(--s2); }}
  .gallery-lead {{ color: var(--muted); font-size: var(--fs-body); margin: 0 0 var(--s5); }}
  .gallery-panels {{ display: grid; gap: var(--s5);
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); }}
  .gallery-panel {{ background: var(--bg); color: var(--ink);
    border: 1px solid var(--hair); border-radius: var(--r-lg); padding: var(--s4); }}
  .gallery-panel h2 {{ font-size: var(--fs-head); margin: 0 0 var(--s3); }}
  .gallery-group {{ padding: var(--s3) 0; border-top: 1px solid var(--hair-2); }}
  .gallery-group h3 {{ font-size: var(--fs-caption); text-transform: uppercase;
    letter-spacing: .06em; color: var(--muted); margin: 0 0 var(--s2); }}
  .gallery-items {{ display: flex; flex-wrap: wrap; gap: var(--s4); align-items: flex-start; }}
  .gallery-item {{ display: flex; flex-direction: column; gap: var(--s1); }}
  .gallery-item__tag {{ font-size: var(--fs-micro); text-transform: uppercase;
    letter-spacing: .06em; color: var(--faint); }}
</style>
</head>
<body>
<h1>Component gallery</h1>
<p class="gallery-lead">Every Part-2 primitive in each documented state, in both
themes. Dev-only surface (SWIMZH_DEV_UI) — absent in production.</p>
<div class="gallery-panels">
{panels}
</div>
<script type="module" src="/static/dist/components/gallery.js"></script>
</body>
</html>
"""


_GALLERY_PAGE = _render_page()


@router.get("/ui/gallery", response_class=HTMLResponse)
def gallery() -> HTMLResponse:
    return HTMLResponse(content=_GALLERY_PAGE)
