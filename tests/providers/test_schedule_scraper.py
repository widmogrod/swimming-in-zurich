"""Scraper parser tested against a saved real stadt-zuerich.ch page (Hallenbad City), plus
the fetch seam via MockTransport."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time
from pathlib import Path

import httpx

from swimzh.core.errors import HttpStatus, ParseError
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.access import PublicSwim, WomenOnly
from swimzh.domain.schedule import TimeRange, Weekday
from swimzh.providers.schedule_scraper import parse_notices, parse_schedule, scrape_schedule

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "hallenbad_city.html"
FIXTURE_ALTSTETTEN = FIXTURES / "hallenbad_altstetten.html"


def test_parses_real_city_page() -> None:
    result = parse_schedule(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(result, Ok), result
    rules = result.value.rules
    assert rules

    # The women-only Variobecken slots the city actually publishes:
    women = {(r.time, min(r.weekdays)) for r in rules if isinstance(r.access, WomenOnly)}
    assert (TimeRange(time(8, 0), time(14, 0)), Weekday.TUESDAY) in women
    assert (TimeRange(time(18, 0), time(22, 0)), Weekday.THURSDAY) in women

    # A day-range row (Freitag–Sonntag) expands to all three days, public.
    fri_sun = next(
        r
        for r in rules
        if isinstance(r.access, PublicSwim)
        and r.weekdays == frozenset({Weekday.FRIDAY, Weekday.SATURDAY, Weekday.SUNDAY})
    )
    assert fri_sun.time == TimeRange(time(8, 0), time(22, 0))


def test_parses_altstetten_html_table() -> None:
    # A different site (bad-altstetten.ch, WordPress) with a plain <table> schedule and no
    # category column — handled by the generic HTML-table parser, not the stadt-zuerich one.
    result = parse_schedule(FIXTURE_ALTSTETTEN.read_text(encoding="utf-8"))
    assert isinstance(result, Ok), result
    rules = result.value.rules

    mon_wed_fri = next(
        r
        for r in rules
        if r.weekdays == frozenset({Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY})
    )
    assert mon_wed_fri.time == TimeRange(time(6, 0), time(21, 0))
    assert isinstance(mon_wed_fri.access, PublicSwim)

    assert any(
        r.weekdays == frozenset({Weekday.SATURDAY, Weekday.SUNDAY})
        and r.time == TimeRange(time(8, 0), time(18, 0))
        for r in rules
    )
    # This site publishes no women-only sessions.
    assert all(not isinstance(r.access, WomenOnly) for r in rules)


def test_parse_notices_extracts_closure_with_dates() -> None:
    notices = parse_notices(FIXTURE.read_text(encoding="utf-8"))
    assert notices
    closure = notices[0]
    assert "Revision" in closure.text
    assert closure.active_from == date(2026, 7, 4)
    assert closure.active_to == date(2026, 8, 7)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="schedule_scraper", retry=RetryPolicy(max_attempts=1))


def test_scrape_schedule_fetches_and_parses() -> None:
    body = FIXTURE.read_bytes()
    client = _client(lambda _r: httpx.Response(200, content=body))
    result = scrape_schedule(client, "https://example.test/city.html")
    assert isinstance(result, Ok)
    assert result.value.rules


def test_page_without_table_is_parse_error() -> None:
    result = parse_schedule("<html><body>no timetable here</body></html>")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_http_error_propagates() -> None:
    client = _client(lambda _r: httpx.Response(503, text="down"))
    result = scrape_schedule(client, "https://example.test/city.html")
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
