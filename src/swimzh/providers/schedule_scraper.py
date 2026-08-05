"""Scrape opening-hours schedules from pool web pages into domain `ScheduleRule`s.

Two page formats are supported, tried in order (a parser registry — add a format, no host
branching):

  1. **stadt-zuerich.ch** — the timetable is an HTML-entity-encoded JSON table of rows
     ``[day, hours, category]`` (e.g. ``["Dienstag", "8–14 Uhr<br>14–22 Uhr", "Frauen"]``).
  2. **generic HTML `<table>`** — a plain ``<tr><td>day</td><td>time</td></tr>`` schedule
     (e.g. bad-altstetten.ch: ``<td>Mo/Mi/Fr</td><td>06:00 – 21:00</td>``). No category column,
     so sessions are public.

Both share the German day/time cell parsers below. Scraping is inherently brittle (page
formats are not contracts): parsing is defensive (unparseable cells skipped, no usable rows →
`ParseError`), pinned by saved-page fixtures, and every failure is a typed `ProviderError`.
Scraped rules use `DayScope.ALWAYS`; annual `Revision` closures are out of scope here.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time

from swimzh.core.errors import ParseError, ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import (
    AccompaniedChildren,
    AdultsOnly,
    GenderDiverse,
    GirlsOnly,
    PublicSwim,
    SchoolReserved,
    SeniorsOnly,
    SessionAccess,
    WomenOnly,
)
from swimzh.domain.models import Notice
from swimzh.domain.schedule import HolidayPolicy, ScheduleRule, TimeRange, Weekday

_SOURCE = "schedule_scraper"

_DAYS_FULL: dict[str, Weekday] = {
    "montag": Weekday.MONDAY,
    "dienstag": Weekday.TUESDAY,
    "mittwoch": Weekday.WEDNESDAY,
    "donnerstag": Weekday.THURSDAY,
    "freitag": Weekday.FRIDAY,
    "samstag": Weekday.SATURDAY,
    "sonntag": Weekday.SUNDAY,
}
_DAYS_ABBR: dict[str, Weekday] = {
    "mo": Weekday.MONDAY,
    "di": Weekday.TUESDAY,
    "mi": Weekday.WEDNESDAY,
    "do": Weekday.THURSDAY,
    "fr": Weekday.FRIDAY,
    "sa": Weekday.SATURDAY,
    "so": Weekday.SUNDAY,
}

_ROW_RE = re.compile(r'\[\{"value":"(?:[^"\\]|\\.)*"\}(?:,\{"value":"(?:[^"\\]|\\.)*"\})*\]')
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TIME_RE = re.compile(r"\d{1,2}[.:]\d{2}\s*[–-]\s*\d{1,2}[.:]\d{2}")


@dataclass(frozen=True, slots=True)
class ScrapedSchedule:
    rules: tuple[ScheduleRule, ...]
    #: `SUNDAY_SCHEDULE` when the timetable attaches holidays to a Sunday row
    #: ("Sonntag (und Feiertage)"); `None` when the page says nothing — the honest unknown,
    #: never assumed to be `NORMAL`.
    holiday_policy: HolidayPolicy | None = None


# --- shared cell parsers -----------------------------------------------------------


def _lookup_day(token: str) -> Weekday | None:
    key = token.strip().lower()
    if key in _DAYS_FULL:
        return _DAYS_FULL[key]
    return _DAYS_ABBR.get(key)


#: A parenthetical qualifier in a day cell — "(und Feiertage)", "(und Feiertage<sup>3</sup>)".
#: Stripped before weekday lookup; the holiday signal itself is read by `_holiday_policy`
#: BEFORE this runs, so removing it here loses nothing.
_DAY_QUALIFIER_RE = re.compile(r"\([^)]*\)")


def _clean_day_cell(cell: str) -> str:
    """Reduce a day cell to bare weekday tokens separated by commas.

    The city writes real markup into this cell — a `<br>` before a qualifier
    (`Sonntag<br>(und Feiertage)`), footnote markers on the weekday itself
    (`Montag<sup>1</sup>`), and a non-breaking space instead of a normal one
    (`Sonntag\xa0(und Feiertage)`). Each of those made the whole row fail to resolve, and a
    row whose days do not resolve is silently dropped by `_rules_from_rows` — so four pools
    lost their Sunday sessions and Bungertwies lost most of its week. `<br>` becomes a comma
    because it separates day tokens (`Samstag, Sonntag<br>(...)`), not just noise.
    """
    text = cell.replace("\xa0", " ")
    text = re.sub(r"<br\s*/?>", ",", text, flags=re.IGNORECASE)
    text = _DAY_QUALIFIER_RE.sub(" ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # A footnote marker leaves its number behind once the <sup> tags are gone ("Montag 1").
    # No German weekday token contains a digit, so dropping digits cannot eat a real day.
    text = re.sub(r"\d+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _parse_days(cell: str) -> frozenset[Weekday]:
    text = _clean_day_cell(cell)
    span = re.match(r"([a-zäöü]+)\s*[–-]\s*([a-zäöü]+)$", text)
    if span:
        start, end = _lookup_day(span.group(1)), _lookup_day(span.group(2))
        if start is not None and end is not None and start <= end:
            return frozenset(w for w in Weekday if start <= w <= end)
    days = {d for part in re.split(r"[,/]", text) if (d := _lookup_day(part)) is not None}
    return frozenset(days)


def _parse_clock(token: str) -> time:
    token = token.strip().replace(":", ".").replace("h", ".")
    if "." in token:
        hour, minute = token.split(".", 1)
        return time(int(hour), int(minute or 0))
    return time(int(token), 0)


def _parse_time_range(cell: str) -> TimeRange | None:
    parts = re.split(r"[–-]", cell.replace("Uhr", "").strip())
    if len(parts) != 2:
        return None
    try:
        return TimeRange(start=_parse_clock(parts[0]), end=_parse_clock(parts[1]))
    except (ValueError, IndexError):
        return None


#: The published age bound inside a category cell — "…Personen ab 16 Jahren".
_MIN_AGE_RE = re.compile(r"\bab\s+(\d{1,2})\s*jahr", re.IGNORECASE)


def _parse_category(cell: str) -> SessionAccess:
    """Classify one *Angebot* cell into the access union.

    Ordered LONGEST-FIRST, because the vocabulary nests: *"für Frauen und Mädchen"* must be
    read as `WomenOnly` (the whole cell), not `GirlsOnly`, and *"für Kinder nur mit
    Erwachsenen"* must not be read as `AdultsOnly` — which it literally contains.

    The `\\xa0` normalisation is load-bearing, not cosmetic: the real cells write
    ``"für\\xa0Erwachsene"`` with a non-breaking space, and matching the literal patterns
    without it fails silently — every adults-only school session would fold to `PublicSwim`.
    """
    lowered = cell.replace("\xa0", " ").strip().lower()
    if "frau" in lowered:
        return WomenOnly()
    if "senior" in lowered:
        return SeniorsOnly()
    if "schul" in lowered:
        return SchoolReserved()
    if "kinder nur mit erwachsenen" in lowered:
        return AccompaniedChildren()
    if "erwachsene und kinder" in lowered:
        return PublicSwim()  # everyone, explicitly — NOT an adults-only window
    if "mädchen" in lowered:
        return GirlsOnly()
    # `GenderDiverse.min_age` is required, so the age is part of what identifies this arm: a
    # trans/non-binary cell WITHOUT a published bound (none exists today) would rather fall
    # through than let the parser invent a threshold the city never wrote.
    if "trans" in lowered or "nicht-binär" in lowered:
        age = _MIN_AGE_RE.search(lowered)
        if age is not None:
            return GenderDiverse(min_age=int(age.group(1)))
    if "erwachsene" in lowered:
        return AdultsOnly()
    return PublicSwim()  # "gemischt" / unmarked → public


@dataclass(frozen=True, slots=True)
class _Slot:
    """One time block of a timetable row, with the verbatim cell its access came from."""

    time: TimeRange
    access: SessionAccess
    source_text: str


def _slots(hours_cell: str, category_cell: str | None) -> list[_Slot]:
    hours = [h for h in hours_cell.split("<br>") if h.strip()]
    categories = (category_cell or "").split("<br>")
    out: list[_Slot] = []
    for i, hour in enumerate(hours):
        time_range = _parse_time_range(hour)
        if time_range is None:
            continue
        category = categories[i] if i < len(categories) else (categories[-1] if categories else "")
        out.append(_Slot(time_range, _parse_category(category), category))
    return out


def _holiday_policy(rows: list[list[str]]) -> HolidayPolicy | None:
    """Read the facility's public-holiday behaviour off the timetable's day column.

    Four pools write "(und Feiertage)" into a Sunday row — the city stating that holidays run
    that row's hours, i.e. `SUNDAY_SCHEDULE`. Nothing else in the timetable speaks to holidays,
    so every other pool yields `None` (unknown), never an assumed `NORMAL`.

    The qualifier is only honoured on a row that actually resolves to Sunday: "(und Feiertage)"
    on some other weekday would mean something we have not seen and must not guess at.
    """
    for row in rows:
        if "feiertag" in row[0].casefold() and Weekday.SUNDAY in _parse_days(row[0]):
            return HolidayPolicy.SUNDAY_SCHEDULE
    return None


def _rules_from_rows(rows: list[list[str]]) -> list[ScheduleRule]:
    """Turn timetable rows into rules, carrying the weekday down CONTINUATION rows.

    A multi-session day is published as one row per session, and only the first names the
    weekday — the rest write a bare ``\\xa0`` into the day cell. Dropping those (which is what
    "no weekdays → skip" did) lost 4 of aemtler's 7 sessions. A blank day cell BEFORE any
    weekday has resolved still drops: there is nothing to inherit.

    This serves both page formats, but is inert for format 2, whose `_parse_html_table`
    pre-filters rows on `_parse_days(r[0])` being truthy — a generic-table page with
    continuation rows would not benefit.
    """
    rules: list[ScheduleRule] = []
    carried: frozenset[Weekday] = frozenset()
    for row in rows:
        days = _parse_days(row[0])
        if days:
            carried = days
        else:
            days = carried
        if not days:
            continue
        category_cell = row[2] if len(row) >= 3 else None
        for slot in _slots(row[1], category_cell):
            rules.append(
                ScheduleRule(
                    weekdays=days,
                    time=slot.time,
                    access=slot.access,
                    source_text=slot.source_text,
                )
            )
    return rules


# --- format 1: stadt-zuerich.ch embedded JSON --------------------------------------


def _parse_stadtzurich(decoded_html: str) -> Result[ScrapedSchedule, ProviderError]:
    rows: list[list[str]] = []
    for match in _ROW_RE.findall(decoded_html):
        try:
            rows.append([c["value"] for c in json.loads(match)])
        except json.JSONDecodeError:
            continue
    hours_rows = [r for r in rows if len(r) >= 2 and "Uhr" in r[1]]
    rules = _rules_from_rows(hours_rows)
    if not rules:
        return Err(ParseError(source=_SOURCE, detail="no stadt-zuerich timetable", raw_snippet=""))
    return Ok(ScrapedSchedule(rules=tuple(rules), holiday_policy=_holiday_policy(hours_rows)))


# --- format 2: generic HTML <table> ------------------------------------------------


def _text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell_html)).strip()


#: How much text before a `<table>` to read as its heading. The operators put the heading in
#: the immediately preceding element, so a short window is both sufficient and safer than a
#: long one (which would reach back into the previous section's heading).
_HEADING_WINDOW = 400

#: Headings that name the pool itself. Checked FIRST, so a combined heading ("Hallenbad und
#: Sauna") is still read as the pool's. None of these is a substring of a non-pool word —
#: "dampfbad" contains "bad", which is exactly why bare "bad" is not on this list.
_POOL_HEADINGS = ("hallenbad", "schwimmbad", "freibad", "schwimm", "becken", "badi")
#: Headings that mark a table as some OTHER facility's hours, when no pool word is present.
_NOT_POOL_HEADINGS = ("sauna", "wellness", "dampfbad", "fitness", "solarium", "restaurant")

#: Ranked table classes. `_NOT_POOL` is not merely deprioritised — it is never served: a
#: table headed "Sauna" is not this pool's timetable under any ordering, and under the
#: fail-fast contract a `ParseError` (a loud build abort) beats a plausible wrong number.
_POOL_TABLE, _UNLABELLED_TABLE, _NOT_POOL_TABLE = 0, 1, 2


def _table_priority(preceding_html: str) -> int:
    """Rank a table by what its heading calls it.

    bad-altstetten.ch ships two structurally IDENTICAL footer tables — "Öffnungszeiten
    Hallenbad" then "Öffnungszeiten Sauna". Taking the first one that parsed meant the correct
    answer depended on DOM order in a footer widget nobody promised us; a reordering would have
    served sauna hours as pool hours silently, with no `ParseError` to notice.
    """
    heading = _text(preceding_html[-_HEADING_WINDOW:]).casefold()
    if any(word in heading for word in _POOL_HEADINGS):
        return _POOL_TABLE
    if any(word in heading for word in _NOT_POOL_HEADINGS):
        return _NOT_POOL_TABLE
    return _UNLABELLED_TABLE


def _parse_html_table(decoded_html: str) -> Result[ScrapedSchedule, ProviderError]:
    candidates: list[tuple[int, int, list[list[str]]]] = []
    previous_end = 0
    for order, match in enumerate(_TABLE_RE.finditer(decoded_html)):
        rows = [[_text(td) for td in _TD_RE.findall(tr)] for tr in _TR_RE.findall(match.group(1))]
        # A schedule table: the day cell resolves AND a later cell holds a time range.
        hours_rows = [
            r for r in rows if len(r) >= 2 and _parse_days(r[0]) and _TIME_RE.search(r[1])
        ]
        # A table's heading is the text since the PREVIOUS table ended — never further back.
        # An unbounded window reaches over the previous table into ITS heading, so with the
        # sauna table first both tables scored "sauna" and document order decided again.
        heading_region = decoded_html[previous_end : match.start()]
        previous_end = match.end()
        priority = _table_priority(heading_region)
        if hours_rows and priority != _NOT_POOL_TABLE:
            candidates.append((priority, order, hours_rows))

    # Best-labelled table wins; document order only breaks ties, so a page with one table
    # (or none labelled) behaves exactly as before.
    for _priority, _order, hours_rows in sorted(candidates, key=lambda c: (c[0], c[1])):
        rules = _rules_from_rows(hours_rows)
        if rules:
            return Ok(
                ScrapedSchedule(rules=tuple(rules), holiday_policy=_holiday_policy(hours_rows))
            )
    return Err(ParseError(source=_SOURCE, detail="no HTML schedule table", raw_snippet=""))


_PARSERS: tuple[Callable[[str], Result[ScrapedSchedule, ProviderError]], ...] = (
    _parse_stadtzurich,
    _parse_html_table,
)


def parse_schedule(page_html: str) -> Result[ScrapedSchedule, ProviderError]:
    """Parse a pool page into schedule rules, trying each supported format in order."""
    decoded = html.unescape(page_html)
    last: Result[ScrapedSchedule, ProviderError] = Err(
        ParseError(source=_SOURCE, detail="no parser matched", raw_snippet=decoded[:200])
    )
    for parser in _PARSERS:
        result = parser(decoded)
        if isinstance(result, Ok):
            return result
        last = result
    return last


# --- notices / alerts (stadt-zuerich.ch <stzh-disturber>) ---------------------------

_SHOW_RE = re.compile(r"<stzh-show\b([^>]*)>(.*?)</stzh-show>", re.IGNORECASE | re.DOTALL)
_LABEL_RE = re.compile(
    r'<stzh-clamp[^>]*slot="label"[^>]*>(.*?)</stzh-clamp>', re.IGNORECASE | re.DOTALL
)


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(name + r'="([^"]*)"', attrs)
    return match.group(1) if match else None


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_notices(page_html: str) -> tuple[Notice, ...]:
    """Extract alert/notice banners (text + active period) from the page's disturber slots."""
    decoded = html.unescape(page_html)
    seen: set[tuple[str, date | None, date | None]] = set()
    notices: list[Notice] = []
    for attrs, inner in _SHOW_RE.findall(decoded):
        label = _LABEL_RE.search(inner)
        if label is None:
            continue
        text = _text(label.group(1))
        if not text:
            continue
        notice = Notice(
            text=text,
            active_from=_iso_date(_attr(attrs, "show-from-date")),
            active_to=_iso_date(_attr(attrs, "hide-from-date")),
        )
        key = (notice.text, notice.active_from, notice.active_to)
        if key not in seen:
            seen.add(key)
            notices.append(notice)
    return tuple(notices)


def fetch_page(client: HttpClient, url: str) -> Result[bytes, ProviderError]:
    """Fetch a pool page's HTML bytes (transport/status errors as values)."""
    match client.get(url):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return Ok(resp.content)


def scrape_schedule(client: HttpClient, url: str) -> Result[ScrapedSchedule, ProviderError]:
    match fetch_page(client, url):
        case Err(error):
            return Err(error)
        case Ok(raw):
            return parse_schedule(raw.decode("utf-8", "replace"))
