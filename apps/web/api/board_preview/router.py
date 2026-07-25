"""The dev-only RibbonBoard preview (`/ui/board`).

S2's observable surface: it mounts the RibbonBoard block in BOTH modes (Day · all
pools, Pool · the week) from saved `/swim` fixtures, so the canvas board can be seen
in a browser and reviewed at the S3 pause. Like `/ui/gallery`, it is registered only
when `SWIMZH_DEV_UI` is set (read in `config.py`), so it is absent in production.

The page is a thin server shell: it `<link>`s the token + component + block
stylesheets, inlines the two fixtures as <script type="application/json"> blocks,
renders the two mount points + a small gender/age control, and loads the
`board_preview` ES module which reads the fixtures and hydrates the boards
client-side. The fixtures are the SAME files the JS unit tests assert against
(apps/web/tests/fixtures) — one source of truth for the S2 states.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _read_fixture(name: str) -> str:
    """Read a saved `/swim` fixture verbatim for inlining. `</` is escaped so the JSON
    cannot prematurely close the surrounding <script> element."""
    text = (_FIXTURES / name).read_text(encoding="utf-8")
    return text.replace("</", "<\\/")


def _render_page() -> str:
    day = _read_fixture("swim_day.json")
    week = _read_fixture("swim_week_oerlikon.json")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RibbonBoard preview · Swimming in Zürich</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/components.css">
<link rel="stylesheet" href="/static/blocks.css">
<style>
  body {{ font-family: var(--f); background: var(--bg); color: var(--ink);
    margin: 0; padding: var(--s5); }}
  h1 {{ font-size: var(--fs-title); font-weight: var(--fw-title); margin: 0 0 var(--s2); }}
  h2 {{ font-size: var(--fs-head); font-weight: var(--fw-head); margin: var(--s5) 0 var(--s3); }}
  .board-lead {{ color: var(--muted); font-size: var(--fs-body); margin: 0 0 var(--s4); }}
  .board-controls {{ display: flex; gap: var(--s3); align-items: center;
    margin: 0 0 var(--s4); font-size: var(--fs-body); }}
  .board-controls label {{ display: flex; gap: var(--s1); align-items: center; }}
  .board-controls select, .board-controls input {{ height: var(--ctl-h);
    border: 1px solid var(--hair); border-radius: var(--r-sm); background: var(--surface);
    color: var(--ink); padding: 0 var(--s2); font: inherit; }}
</style>
</head>
<body>
<h1>RibbonBoard preview</h1>
<p class="board-lead">The S2 hero block, rendered from saved <code>/swim</code> fixtures
in both modes. Dev-only surface (SWIMZH_DEV_UI) — absent in production. The wide canvas
scrolls INSIDE each row's card; the page never scrolls sideways.</p>

<div class="board-controls">
  <label>Gender
    <select id="board-gender">
      <option value="">unset</option>
      <option value="female">female</option>
      <option value="male">male</option>
      <option value="diverse">diverse</option>
    </select>
  </label>
  <label>Age <input id="board-age" type="number" min="0" max="120" placeholder="—"></label>
</div>

<h2>Day · all pools</h2>
<div id="board-day"></div>

<h2>Pool · the week (Hallenbad Oerlikon)</h2>
<div id="board-pool"></div>

<script id="board-day-data" type="application/json">{day}</script>
<script id="board-week-data" type="application/json">{week}</script>
<script type="module" src="/static/dist/blocks/board_preview.js"></script>
</body>
</html>
"""


_BOARD_PAGE = _render_page()


@router.get("/ui/board", response_class=HTMLResponse)
def board_preview() -> HTMLResponse:
    return HTMLResponse(content=_BOARD_PAGE)
