"""Scrape opening-hours schedules from stadt-zuerich.ch pool pages.

These pages embed the timetable as an HTML-entity-encoded JSON table — rows of
``[day, hours, category]`` (e.g. ``["Dienstag", "8–14 Uhr<br>14–22 Uhr", "Frauen<br>gemischt"]``).
We decode, extract the hours rows, and parse the German day/time/category cells into domain
`ScheduleRule`s.

This is inherently brittle: the page format is not a contract. So parsing is defensive
(unparseable cells are skipped, a table with no usable rows is a `ParseError`), tests pin it
against a saved real page, and every failure surfaces as a typed `ProviderError` value.
Scraped rules use `DayScope.ALWAYS` — the pages do not encode term/holiday variants; annual
`Revision` closures are handled separately (curated `ClosureRange`s).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import time

from swimzh.core.errors import ParseError, ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import PublicSwim, SchoolReserved, SeniorsOnly, SessionAccess, WomenOnly
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday

_SOURCE = "schedule_scraper"

_DAYS: dict[str, Weekday] = {
    "montag": Weekday.MONDAY,
    "dienstag": Weekday.TUESDAY,
    "mittwoch": Weekday.WEDNESDAY,
    "donnerstag": Weekday.THURSDAY,
    "freitag": Weekday.FRIDAY,
    "samstag": Weekday.SATURDAY,
    "sonntag": Weekday.SUNDAY,
}

_ROW_RE = re.compile(r'\[\{"value":"(?:[^"\\]|\\.)*"\}(?:,\{"value":"(?:[^"\\]|\\.)*"\})*\]')


@dataclass(frozen=True, slots=True)
class ScrapedSchedule:
    rules: tuple[ScheduleRule, ...]


def _parse_days(cell: str) -> frozenset[Weekday]:
    text = cell.strip().lower()
    span = re.match(r"([a-zäöü]+)\s*[–-]\s*([a-zäöü]+)$", text)
    if span and span.group(1) in _DAYS and span.group(2) in _DAYS:
        start, end = _DAYS[span.group(1)], _DAYS[span.group(2)]
        if start <= end:
            return frozenset(w for w in Weekday if start <= w <= end)
    parts = re.split(r"[,/]", text)
    return frozenset(_DAYS[p.strip()] for p in parts if p.strip() in _DAYS)


def _parse_clock(token: str) -> time:
    token = token.strip().replace(":", ".").replace("h", ".")
    if "." in token:
        hour, minute = token.split(".", 1)
        return time(int(hour), int(minute or 0))
    return time(int(token), 0)


def _parse_time_range(cell: str) -> TimeRange | None:
    cleaned = cell.replace("Uhr", "").strip()
    parts = re.split(r"[–-]", cleaned)
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


def _extract_rows(decoded_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for match in _ROW_RE.findall(decoded_html):
        try:
            cells = json.loads(match)
        except json.JSONDecodeError:
            continue
        rows.append([c["value"] for c in cells])
    return rows


def parse_schedule(page_html: str) -> Result[ScrapedSchedule, ProviderError]:
    """Parse a pool page's HTML into schedule rules (public/women/seniors/school sessions)."""
    decoded = html.unescape(page_html)
    hours_rows = [r for r in _extract_rows(decoded) if len(r) >= 2 and "Uhr" in r[1]]
    if not hours_rows:
        return Err(
            ParseError(
                source=_SOURCE, detail="no opening-hours table found", raw_snippet=decoded[:200]
            )
        )

    rules: list[ScheduleRule] = []
    for row in hours_rows:
        days = _parse_days(row[0])
        if not days:
            continue
        category_cell = row[2] if len(row) >= 3 else None
        for time_range, access in _slots(row[1], category_cell):
            rules.append(ScheduleRule(weekdays=days, time=time_range, access=access))

    if not rules:
        return Err(
            ParseError(
                source=_SOURCE,
                detail="hours table had no parseable rows",
                raw_snippet=decoded[:200],
            )
        )
    return Ok(ScrapedSchedule(rules=tuple(rules)))


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
