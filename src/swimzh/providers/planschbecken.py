"""Parser for the shared Planschbecken overview page — one page states three facts
about thirteen pools.

The 13 Planschbecken share one URL (`…/sommerbaeder/planschbecken.html`), so no per-pool
scraper ever sees them. The page itself states real facts **once, for all thirteen**, in its
lead paragraph: *"Diese sind je nach Wetter von Mai bis September in Betrieb. Die Nutzung
der Planschbecken ist kostenlos."* — a season, a weather condition, and free admission.

**Page-level prose only, structurally.** The per-pool accordion is stripped before any
sentence is read, so a blurb inside an `<stzh-accordion-item>` can never supply (or spoil)
a fact — no per-pool join, no name matching, per the fan-out invariant. The lead sentence
sits outside the accordion (verified against the committed fixture).

**Stated, never assumed.** The season sentence is load-bearing: a page without it is
`Err(ParseError)` and aborts the build (fail-fast, like every declared page). The two
qualifiers are read off the page or defaulted to the honest unknown: *"je nach Wetter"*
inside the season sentence → `Weather.FAIR_ONLY`, absent → `Weather.ANY`; the tight
*"Nutzung … kostenlos"* sentence → `Free()`, absent → `Unknown()` — free-ness is a fact
the page states, never an inference from a missing tariff.

This module is a **pure parser** — no I/O. `etl.scrape`'s shared-source phase fetches the
page once and hands the body here; the resulting `SharedFacts` fan out to every member.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from swimzh.core import Err, Ok, ParseError, ProviderError, Result
from swimzh.domain.admission import Admission, Free, Unknown
from swimzh.domain.models import OperatingSeason
from swimzh.domain.schedule import AnnualWindow, Weather

_SOURCE = "planschbecken"


@dataclass(frozen=True, slots=True)
class SharedFacts:
    """The page-level facts one shared page states about every member pool.

    `operating_season` is optional in the TYPE (a future shared page may state admission
    only); the Planschbecken parser itself never returns `None` — its season sentence is
    required or the parse fails.
    """

    operating_season: OperatingSeason | None
    admission: Admission


#: German month names as the city writes them. Fixed vocabulary, so a misspelling is a
#: parse failure (fail-fast) rather than a silently wrong season.
_MONTHS: dict[str, int] = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
#: Longest-first so "juli" can never be shadowed by a shorter prefix alternative.
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

#: The season SENTENCE: "… von Mai bis September in Betrieb." Anchored on month names AND
#: "in Betrieb" so an unrelated date range elsewhere on the page can never be read as the
#: season. Captured up to the sentence boundary so the weather qualifier is scoped to THIS
#: sentence, not the whole page.
_SEASON_SENTENCE_RE = re.compile(
    r"([^.]*?\bvon\s+(" + _MONTH_ALT + r")\s+bis\s+(" + _MONTH_ALT + r")\s+in\s+Betrieb[^.]*)",
    re.IGNORECASE,
)

#: The weather qualifier, looked up inside the season sentence only.
_WEATHER_PHRASE = "je nach wetter"

#: The admission SENTENCE: "Die Nutzung der Planschbecken ist kostenlos." Tight — a bare
#: `kostenlos` in unrelated prose (locker rows, Ausstattung) must not assert free admission.
_FREE_SENTENCE_RE = re.compile(r"\bNutzung\b[^.]*\bkostenlos\b", re.IGNORECASE)

#: One per-pool accordion entry. Stripped whole before parsing: fan-out facts are
#: page-level only, so nothing inside an accordion may be read.
_ACCORDION_ITEM_RE = re.compile(r"<stzh-accordion-item\b.*?</stzh-accordion-item>", re.S | re.I)

_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _page_level_text(page_html: str) -> str:
    """The page's prose with every accordion entry removed and markup stripped.

    Tags are stripped BEFORE entities are unescaped: unescaping first would mint real
    markup out of escaped text in prose (`&lt;b&gt;`), which the tag pass would then
    delete — silently dropping prose from the very sentences this parser reads.
    """
    without_accordions = _ACCORDION_ITEM_RE.sub(" ", page_html)
    without_scripts = _SCRIPT_RE.sub(" ", without_accordions)
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", without_scripts))).strip()


def parse_planschbecken(page_html: str) -> Result[SharedFacts, ProviderError]:
    """Read the three page-stated facts, or fail the parse if the season sentence is gone.

    The month range rides `AnnualWindow.whole_months` — `MONTH` precision, whole months
    inclusive — because the page names months and no days.
    """
    text = _page_level_text(page_html)
    season = _SEASON_SENTENCE_RE.search(text)
    if season is None:
        return Err(
            ParseError(
                source=_SOURCE,
                detail="season sentence ('von <Monat> bis <Monat> in Betrieb') not found",
                raw_snippet=text[:200],
            )
        )
    sentence, start_month, end_month = season.group(1), season.group(2), season.group(3)
    window = AnnualWindow.whole_months(
        _MONTHS[start_month.casefold()], _MONTHS[end_month.casefold()]
    )
    weather = Weather.FAIR_ONLY if _WEATHER_PHRASE in sentence.casefold() else Weather.ANY
    admission: Admission = Free() if _FREE_SENTENCE_RE.search(text) else Unknown()
    return Ok(
        SharedFacts(
            operating_season=OperatingSeason(window=window, weather=weather),
            admission=admission,
        )
    )
