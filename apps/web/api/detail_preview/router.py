"""The dev-only DetailPanel + LaneGantt preview (`/ui/detail`).

S3's observable surface (the crown-jewel pause): it mounts the RibbonBoard (Day
mode) alongside the DetailPanel + LaneGantt for one basin, ALL sharing one
timescale, so a click on a board ribbon at time T lands the Gantt cursor on T's
gridline and both the board-side readout and the panel headline show the SAME
`publicAt(basin, T)` number. Like `/ui/board` and `/ui/gallery`, it is registered
only when `SWIMZH_DEV_UI` is set (read in `config.py`) — absent in production.

The page is a thin server shell: it `<link>`s the token + component + block
stylesheets, inlines a saved `/swim` fixture (the board) and a saved `/pools/{id}`
fixture (the panel + Gantt, with owner-named reserved lanes) as
<script type="application/json"> blocks, renders the mount points, and loads the
`detail_preview` ES module which hydrates everything client-side. The fixtures are
the SAME files the JS unit tests assert against (apps/web/tests/fixtures).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _read_fixture(name: str) -> str:
    """Read a saved fixture verbatim for inlining. `</` is escaped so the JSON cannot
    prematurely close the surrounding <script> element."""
    text = (_FIXTURES / name).read_text(encoding="utf-8")
    return text.replace("</", "<\\/")


def _render_page() -> str:
    day = _read_fixture("swim_day.json")
    pool = _read_fixture("pool_oerlikon.json")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DetailPanel + LaneGantt preview · Swimming in Zürich</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/components.css">
<link rel="stylesheet" href="/static/blocks.css">
<style>
  body {{ font-family: var(--f); background: var(--bg); color: var(--ink);
    margin: 0; padding: var(--s5); }}
  h1 {{ font-size: var(--fs-title); font-weight: var(--fw-title); margin: 0 0 var(--s2); }}
  .detail-lead {{ color: var(--muted); font-size: var(--fs-body); margin: 0 0 var(--s4); }}
  .detail-layout {{ display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--s4); }}
  @media (min-width: 1060px) {{
    .detail-layout {{ grid-template-columns: minmax(0, 1fr) 22rem; align-items: start; }}
  }}
  .detail-readout {{ font-size: var(--fs-body); color: var(--ink-2); margin: 0 0 var(--s3);
    font-variant-numeric: tabular-nums; }}
  .detail-hint {{ color: var(--muted); font-size: var(--fs-caption); }}
</style>
</head>
<body>
<h1>DetailPanel + LaneGantt preview</h1>
<p class="detail-lead">The S3 crown jewel, rendered from saved fixtures. Click (or hover)
a board ribbon: ONE cursor time T drives the Gantt cursor onto T's gridline and both the
board-side readout and the panel headline to the SAME <code>publicAt(basin, T)</code> value.
Dev-only surface (SWIMZH_DEV_UI) — absent in production. <span class="detail-hint">Resize
below 1060px to see the panel become a slide-up bottom sheet.</span></p>

<p class="detail-readout" id="detail-readout">Board readout — click a ribbon to set the cursor.</p>

<div class="detail-layout">
  <div id="detail-board"></div>
  <div id="detail-panel"></div>
</div>

<script id="detail-day-data" type="application/json">{day}</script>
<script id="detail-pool-data" type="application/json">{pool}</script>
<script type="module" src="/static/dist/blocks/detail_preview.js"></script>
</body>
</html>
"""


_DETAIL_PAGE = _render_page()


@router.get("/ui/detail", response_class=HTMLResponse)
def detail_preview() -> HTMLResponse:
    return HTMLResponse(content=_DETAIL_PAGE)
