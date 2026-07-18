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
from swimzh.domain.access import PublicSwim, SchoolReserved, SeniorsOnly, SessionAccess, WomenOnly
from swimzh.domain.models import Notice
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday

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


# --- shared cell parsers -----------------------------------------------------------


def _lookup_day(token: str) -> Weekday | None:
    key = token.strip().lower()
    if key in _DAYS_FULL:
        return _DAYS_FULL[key]
    return _DAYS_ABBR.get(key)


def _parse_days(cell: str) -> frozenset[Weekday]:
    text = cell.strip().lower()
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


def _parse_category(cell: str) -> SessionAccess:
    lowered = cell.strip().lower()
    if "frau" in lowered:
        return WomenOnly()
    if "senior" in lowered:
        return SeniorsOnly()
    if "schul" in lowered:
        return SchoolReserved()
    return PublicSwim()  # "gemischt" / unmarked → public


def _slots(hours_cell: str, category_cell: str | None) -> list[tuple[TimeRange, SessionAccess]]:
    hours = [h for h in hours_cell.split("<br>") if h.strip()]
    categories = (category_cell or "").split("<br>")
    out: list[tuple[TimeRange, SessionAccess]] = []
    for i, hour in enumerate(hours):
        time_range = _parse_time_range(hour)
        if time_range is None:
            continue
        category = categories[i] if i < len(categories) else (categories[-1] if categories else "")
        out.append((time_range, _parse_category(category)))
    return out


def _rules_from_rows(rows: list[list[str]]) -> list[ScheduleRule]:
    rules: list[ScheduleRule] = []
    for row in rows:
        days = _parse_days(row[0])
        if not days:
            continue
        category_cell = row[2] if len(row) >= 3 else None
        for time_range, access in _slots(row[1], category_cell):
            rules.append(ScheduleRule(weekdays=days, time=time_range, access=access))
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
    return Ok(ScrapedSchedule(rules=tuple(rules)))


# --- format 2: generic HTML <table> ------------------------------------------------


def _text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell_html)).strip()


def _parse_html_table(decoded_html: str) -> Result[ScrapedSchedule, ProviderError]:
    for table in _TABLE_RE.findall(decoded_html):
        rows = [[_text(td) for td in _TD_RE.findall(tr)] for tr in _TR_RE.findall(table)]
        # A schedule table: the day cell resolves AND a later cell holds a time range.
        hours_rows = [
            r for r in rows if len(r) >= 2 and _parse_days(r[0]) and _TIME_RE.search(r[1])
        ]
        rules = _rules_from_rows(hours_rows)
        if rules:  # first schedule-like table wins
            return Ok(ScrapedSchedule(rules=tuple(rules)))
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
