"""The UI endpoint: the unified two-mode "flowing water" app.

`/` serves a SMALL, self-contained HTML skeleton — a `<meta charset>`, the three
design-system stylesheets (`tokens.css` → `components.css` → `blocks.css`) linked
from the `/static` mount, the block mount points, and the `app.js` ES module. The
client (``static/js/app.js``) hydrates every block (IdentityHeader, FilterToolbar,
InsightBar, RibbonBoard, DetailPanel, BoardLegend) from the JSON API
(`/swim`, `/pools`, `/pools/{id}`, `/access-types`). The no-pools empty state is a
board-level state (StateBlocks) rendered inside the board host — not a standalone
below-board section.

There is no server-side templating and nothing is read from `data/` here — the token
layer is LINKED (not inlined), so the no-build layering tokens → components → blocks
is served entirely static. The legacy 1084-line four-tab embedded string that this
replaced was deleted at S5.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


# The unified two-mode app shell. A SMALL skeleton: charset + the three design-system
# stylesheets from the /static mount + the block mount points + the app.js ES module.
# There is no standalone StateBlocks mount — closed/uncurated pools now read ON the
# board rows, and the no-pools empty state renders inside the board host.
# The client (static/js/app.js) hydrates every block from the JSON API. Tokens are
# LINKED here (not inlined): the no-build layering is tokens → components → blocks,
# all served static, so there is nothing to inject at request time.
_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swimming in Zürich</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/components.css">
<link rel="stylesheet" href="/static/blocks.css">
</head>
<body>
<div id="app" class="app">
  <header id="app-header" class="apphdr"></header>
  <div id="app-toolbar" class="toolbar"></div>
  <div id="app-insight" class="insight"></div>
  <main class="app__main">
    <div id="app-board" class="app__board"></div>
    <aside id="app-panel" class="app__panel"></aside>
  </main>
  <section id="app-legend" class="legend"></section>
</div>
<script type="module" src="/static/js/app.js"></script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=_SHELL)
