"""Extractors for the **private-operator** pool pages (bad-altstetten.ch, doldereisundbad.ch,
seebadenge.ch) — sites the city links to but does not publish.

These pages are hand-authored WordPress, so they carry no `stzh-*` web components: the
stadt-zuerich extractors in `schedule_scraper` (`parse_notices` and friends) find nothing on
them, which is why `hallenbad-altstetten` shipped with `closures: []` while its operator was
announcing an 18-day shutdown.

This module is a **pure parser** — no I/O. It reads bytes `etl.scrape` has already fetched for
the schedule pass, exactly as `parse_notices` does, so it needs no `HttpClient` and no cache
tier of its own.

**Section-anchored, never greedy.** A date range is only read from a window around an explicit
maintenance keyword. These pages are full of unrelated date ranges (events, courses, restaurant
weeks); a page-wide "find a date range" would confidently return the wrong one. Finding nothing
is a normal outcome (most of the year there is no Revision) and yields an empty tuple, not an
error — but note the honest limit of that choice: a *broken* parser is indistinguishable from
*no closure announced*, so this module must stay pinned to a saved-page fixture.
"""

from __future__ import annotations

import html
import re
from datetime import date

from swimzh.domain.schedule import ClosureRange

# German month names as the operators write them. Fixed vocabulary, so a misspelling is a miss
# (→ no closure) rather than a silently wrong date.
_MONTHS: dict[str, int] = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
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

_MONTH_ALT = "|".join(_MONTHS)

#: The keywords that make a date range a *closure*. Matched case-insensitively; the window
#: around a hit is the only text the date regex is ever shown.
_MAINTENANCE_WORDS = ("revision", "betriebsferien")

#: How far either side of a keyword hit to look for the range. The altstetten prose puts the
#: dates ~40 chars after the word in one form and ~15 chars *before* it in the other.
_WINDOW = 320

#: `30. Juli – Sonntag, 16. August 2026` and `28. Juli 2025 bis Sonntag,17. August 2025`.
#: The first year is optional: when the operator states it once, at the end, it governs both
#: endpoints. A weekday before the second day ("Sonntag,") is noise and is skipped.
_RANGE_RE = re.compile(
    r"(\d{1,2})\.\s*(" + _MONTH_ALT + r")\.?"
    r"(?:\s+(\d{4}))?"
    r"\s*(?:–|—|-|bis(?:\s+und\s+mit)?)\s*"
    r"(?:[A-Za-zÄÖÜäöü]+\s*,\s*)?"
    r"(\d{1,2})\.\s*(" + _MONTH_ALT + r")\.?"
    r"\s+(\d{4})",
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain_text(page_html: str) -> str:
    """Strip markup to a single whitespace-normalised line.

    The operators wrap dates in `<strong>`/`<br>` mid-phrase, so matching against raw HTML
    would miss ranges that are perfectly legible to a reader.
    """
    without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", page_html, flags=re.S | re.I)
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(without_scripts))).strip()


def _to_date(day: str, month: str, year: str) -> date | None:
    """Build a date, or `None` if the operator wrote something impossible (31 February)."""
    month_num = _MONTHS.get(month.casefold())
    if month_num is None:
        return None
    try:
        return date(int(year), month_num, int(day))
    except ValueError:
        return None


def _windows(text: str) -> list[str]:
    """The slices of `text` around every maintenance keyword, in order of appearance."""
    lowered = text.casefold()
    spans: list[str] = []
    for word in _MAINTENANCE_WORDS:
        start = lowered.find(word)
        while start != -1:
            spans.append(text[max(0, start - _WINDOW) : start + _WINDOW])
            start = lowered.find(word, start + 1)
    return spans


def parse_maintenance_closures(page_html: str) -> tuple[ClosureRange, ...]:
    """Extract announced maintenance shutdowns ("Revision", "Betriebsferien") as closures.

    Returns every distinct range found, oldest first — including ranges already in the past.
    A stale announcement left on the page is harmless (the resolver only consults a closure
    whose `contains(d)` holds) and dropping it would mean deciding today's date matters to a
    *parser*, which it must not.

    `reason` is the German keyword, so `classify_closure` maps it to `ClosureCode.MAINTENANCE`
    (or `OPERATIONAL_BREAK`) through the existing table rather than a second vocabulary here.
    """
    text = _plain_text(page_html)
    seen: set[tuple[date, date]] = set()
    closures: list[ClosureRange] = []

    for window in _windows(text):
        reason = "Betriebsferien" if "betriebsferien" in window.casefold() else "Revision"
        for day1, month1, year1, day2, month2, year2 in _RANGE_RE.findall(window):
            start = _to_date(day1, month1, year1 or year2)
            end = _to_date(day2, month2, year2)
            if start is None or end is None or end < start:
                continue
            if (start, end) in seen:
                continue
            seen.add((start, end))
            closures.append(ClosureRange(start=start, end=end, reason=reason))

    closures.sort(key=lambda c: (c.start, c.end))
    return tuple(closures)
