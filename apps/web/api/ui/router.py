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

from typing import Annotated

from fastapi import APIRouter, Cookie, Header
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
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
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
<script type="module" src="/static/dist/app.js"></script>
</body>
</html>
"""


#: The handful of strings that CANNOT come from the client catalogue, because the browser
#: needs them before any JavaScript runs: the document language and the tab title. A plain
#: dict is proportionate for two strings per locale — gettext would be overkill.
#:
#: `<html lang>` is not cosmetic: screen readers pick their pronunciation from it, and CSS
#: `:lang()` and hyphenation key off it. Serving `lang="en"` to a Polish reader is a real
#: accessibility defect, which is exactly why the locale lives in a COOKIE — localStorage
#: would be invisible here.
_SHELL_TEXT: dict[str, dict[str, str]] = {
    "en": {"lang": "en", "title": "Swimming in Zürich"},
    "de": {"lang": "de-CH", "title": "Schwimmen in Zürich"},
    "fr": {"lang": "fr-CH", "title": "Nager à Zurich"},
    "it": {"lang": "it-CH", "title": "Nuotare a Zurigo"},
    "pl": {"lang": "pl", "title": "Pływanie w Zurychu"},
}

#: Kept in step with the client's LOCALE_COOKIE.
LOCALE_COOKIE = "swimzh_locale"


def _negotiate(cookie: str | None, accept_language: str | None) -> str:
    """The locale for this request: the cookie first, then `Accept-Language`, then `en`.

    The SAME order the client's `resolveLocale` uses — the cookie wins because it is an
    explicit choice, `Accept-Language` is only a hint. Deliberately NOT a redirect: a
    language guess should never change the URL a user shared.
    """
    if cookie in _SHELL_TEXT:
        return cookie or "en"
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        base = tag.split("-")[0]
        if base in _SHELL_TEXT:
            return base
    return "en"


@router.get("/", response_class=HTMLResponse)
def index(
    swimzh_locale: Annotated[str | None, Cookie()] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
    text = _SHELL_TEXT[_negotiate(swimzh_locale, accept_language)]
    return HTMLResponse(content=_SHELL.format(**text))
