"""Pins the shared Planschbecken parser against the committed page snapshot.

Fixture provenance: `fixtures/planschbecken.html` is byte-identical to the response body of
`https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/sommerbaeder/planschbecken.html`
as held by the provider HTTP disk cache (entry `107cac543a59f52e`, `static` tier, fetched
2026-08-08T12:55:51+02:00) — materialized once from the cache, not re-fetched.

Two families of pins:

* **The three facts** the page states once for all thirteen pools — season (MONTH
  precision), weather, free admission — plus their honest degradations when a stated
  qualifier is absent (stated weather only, never assumed; free-ness stated, never
  inferred) and the fail-fast on a missing season sentence.
* **The page measurements** the fan-out design was decided on, converted from a
  gitignored-cache inspection into committed facts: the accordion names *Josefwiese*
  (roster: *Josefswiese*) and omits *Föhrenwald* entirely — the measured 2-of-13 name
  mismatch that killed the per-pool join — so the page carries exactly 12
  `<stzh-accordion-item>` elements for 13 pools.
"""

from __future__ import annotations

import re
from pathlib import Path

from swimzh.core import Err, Ok, ParseError
from swimzh.domain.admission import Free, Unknown
from swimzh.domain.schedule import DatePrecision, Weather
from swimzh.providers.planschbecken import SharedFacts, parse_planschbecken

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "planschbecken.html"

#: The page's own lead sentences, verbatim — each removal test asserts its target text is
#: really in the fixture first, so a page refresh that rewords the prose fails loudly here
#: rather than silently testing nothing.
SEASON_SENTENCE = "Diese sind je nach Wetter von Mai bis September in Betrieb."
WEATHER_PHRASE = "je nach Wetter "
FREE_WORD = "kostenlos"

ACCORDION_ITEM_RE = re.compile(r"<stzh-accordion-item\b.*?</stzh-accordion-item>", re.S)


def _page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _facts(page_html: str) -> SharedFacts:
    result = parse_planschbecken(page_html)
    assert isinstance(result, Ok), result
    return result.value


def _removed(page: str, target: str) -> str:
    assert target in page, f"fixture no longer carries {target!r} — re-pin before testing"
    return page.replace(target, "")


def test_the_committed_page_states_all_three_facts() -> None:
    """Season Mai–September at MONTH precision, fair-weather only, admission free."""
    facts = _facts(_page())

    season = facts.operating_season
    assert season is not None
    assert season.window.precision is DatePrecision.MONTH
    assert (season.window.start.month, season.window.end.month) == (5, 9)
    assert season.weather is Weather.FAIR_ONLY
    assert facts.admission == Free()


def test_a_page_without_the_season_sentence_is_a_parse_error() -> None:
    """The season sentence is load-bearing: without it the parse fails fast and aborts the
    build — it never degrades to a season-less Ok."""
    result = parse_planschbecken(_removed(_page(), SEASON_SENTENCE))

    assert isinstance(result, Err), result
    assert isinstance(result.error, ParseError)


def test_weather_is_stated_never_assumed() -> None:
    """Without "je nach Wetter" the season still parses, at `Weather.ANY` — the qualifier
    is read off the page, not presumed for every outdoor basin."""
    facts = _facts(_removed(_page(), WEATHER_PHRASE))

    season = facts.operating_season
    assert season is not None
    assert season.weather is Weather.ANY
    assert (season.window.start.month, season.window.end.month) == (5, 9)


def test_free_admission_is_stated_never_inferred() -> None:
    """Without "kostenlos" the admission is `Unknown()` — never `Free()` inferred from a
    missing tariff link, and never an error: the season sentence alone still parses."""
    facts = _facts(_removed(_page(), FREE_WORD))

    assert facts.admission == Unknown()
    assert facts.operating_season is not None


def test_no_accordion_content_is_read() -> None:
    """A copy with every `<stzh-accordion-item>` stripped parses to the identical
    `SharedFacts` — the fan-out facts are page-level prose, never a per-pool blurb."""
    page = _page()
    stripped = ACCORDION_ITEM_RE.sub("", page)
    assert "<stzh-accordion-item" not in stripped

    assert _facts(stripped) == _facts(page)


# --- The measured page shape the fan-out design rests on, pinned as committed facts. ---


def test_the_accordion_misnames_josefwiese_and_omits_foehrenwald() -> None:
    """The measured 2-of-13 mismatch that rejected the per-pool join: the accordion heading
    is *Josefwiese* while the roster says *Josefswiese* (the page's own image alt-text even
    disagrees with its heading), and *Föhrenwald* appears nowhere on the page."""
    page = _page()
    headings = re.findall(r'<stzh-accordion-item\s+heading="([^"]*)"', page)

    assert "Josefwiese" in headings
    assert "Josefswiese" not in headings
    assert "Föhrenwald" not in page


def test_the_page_carries_exactly_twelve_accordion_items() -> None:
    """12 accordions for 13 pools — the page cannot be a per-pool source."""
    assert len(ACCORDION_ITEM_RE.findall(_page())) == 12
