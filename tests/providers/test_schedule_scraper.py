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
from swimzh.domain.schedule import HolidayPolicy, TimeRange, Weekday
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


# --- day-cell normalisation ---------------------------------------------------------
#
# The city writes markup INTO the weekday cell. Every form below made `_parse_days` return
# an empty set, and `_rules_from_rows` silently drops a row whose days do not resolve — so
# four pools lost their Sunday sessions and Bungertwies lost Monday and Wednesday too.


def _row_page(day_cell: str, hours_cell: str = "9–16 Uhr") -> str:
    """A minimal stadt-zuerich page carrying one timetable row."""
    return f'<div>[{{"value":"{day_cell}"}},{{"value":"{hours_cell}"}}]</div>'


def _days_of(day_cell: str) -> set[str]:
    result = parse_schedule(_row_page(day_cell))
    if not isinstance(result, Ok):
        return set()
    return {d.name for rule in result.value.rules for d in rule.weekdays}


def test_holiday_qualifier_after_a_br_does_not_swallow_the_day() -> None:
    # kaeferberg, leimbach (with a NBSP instead of the <br>), bungertwies (+ a footnote).
    assert _days_of("Sonntag<br>(und Feiertage)") == {"SUNDAY"}
    assert _days_of("Sonntag (und Feiertage)") == {"SUNDAY"}
    assert _days_of("Sonntag<br>(und Feiertage<sup>3</sup>)") == {"SUNDAY"}


def test_br_separates_days_so_a_paired_row_keeps_both() -> None:
    # blaesi: `<br>` is a SEPARATOR here, not noise — dropping it silently lost the Sunday
    # half of a Saturday+Sunday row while the Saturday half survived.
    assert _days_of("Samstag, Sonntag<br>(und Feiertage)") == {"SATURDAY", "SUNDAY"}


def test_footnote_marker_on_the_weekday_itself_is_ignored() -> None:
    # bungertwies: `Montag<sup>1</sup>` / `Mittwoch<sup>2</sup>` dropped both rows entirely.
    assert _days_of("Montag<sup>1</sup>") == {"MONDAY"}
    assert _days_of("Mittwoch<sup>2</sup>") == {"WEDNESDAY"}


def test_plain_and_span_day_cells_are_unchanged() -> None:
    assert _days_of("Montag") == {"MONDAY"}
    assert _days_of("Freitag–Sonntag") == {"FRIDAY", "SATURDAY", "SUNDAY"}
    assert _days_of("Montag–Sonntag") == {
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    }


def test_a_cell_with_no_weekday_still_resolves_to_nothing() -> None:
    assert _days_of("(und Feiertage)") == set()
    assert _days_of("Gilberte") == set()


def test_bungertwies_and_leimbach_recover_their_lost_sessions() -> None:
    # The regression, end to end on the real saved pages.
    bungertwies = parse_schedule(
        (FIXTURES / "hallenbad_bungertwies.html").read_text(encoding="utf-8")
    )
    assert isinstance(bungertwies, Ok)
    days = {d.name for r in bungertwies.value.rules for d in r.weekdays}
    assert {"MONDAY", "WEDNESDAY", "SUNDAY"} <= days

    leimbach = parse_schedule((FIXTURES / "hallenbad_leimbach.html").read_text(encoding="utf-8"))
    assert isinstance(leimbach, Ok)
    assert "SUNDAY" in {d.name for r in leimbach.value.rules for d in r.weekdays}


# --- public-holiday policy, sourced from the timetable --------------------------------


def _policy_of(fixture: str) -> object:
    result = parse_schedule((FIXTURES / fixture).read_text(encoding="utf-8"))
    assert isinstance(result, Ok), result
    return result.value.holiday_policy


def test_und_feiertage_on_a_sunday_row_sources_a_sunday_schedule() -> None:
    for fixture in (
        "hallenbad_blaesi.html",
        "hallenbad_bungertwies.html",
        "hallenbad_leimbach.html",
        "waermebad_kaeferberg.html",
    ):
        assert _policy_of(fixture) is HolidayPolicy.SUNDAY_SCHEDULE, fixture


def test_a_page_that_says_nothing_about_holidays_yields_unknown_not_normal() -> None:
    # The whole point: silence is `None`, never an assumed NORMAL. City and Oerlikon carry no
    # holiday token at all.
    assert _policy_of("hallenbad_city.html") is None
    assert _policy_of("hallenbad_oerlikon.html") is None
    assert _policy_of("hallenbad_altstetten.html") is None


def test_the_qualifier_is_only_honoured_on_a_row_that_resolves_to_sunday() -> None:
    # "(und Feiertage)" on some other weekday means something we have not seen; guessing
    # SUNDAY_SCHEDULE from it would invent a fact.
    result = parse_schedule(_row_page("Mittwoch (und Feiertage)"))
    assert isinstance(result, Ok)
    assert result.value.holiday_policy is None


# --- table selection: by heading, not by position -------------------------------------
#
# bad-altstetten.ch ships two structurally identical footer tables, "Öffnungszeiten
# Hallenbad" and "Öffnungszeiten Sauna". Taking the first that parsed made the right answer
# depend on DOM order in a widget nobody promised us -- a reorder would have served sauna
# hours as pool hours with no ParseError to notice.

_SAUNA_TABLE = (
    "<h2>Öffnungszeiten Sauna</h2><table><tr><td>Mo</td><td>09:00 – 22:00</td></tr></table>"
)
_POOL_TABLE = (
    "<h2>Öffnungszeiten Hallenbad</h2><table><tr><td>Mo</td><td>06:00 – 21:00</td></tr></table>"
)
_UNLABELLED_TABLE = "<table><tr><td>Mo</td><td>07:00 – 19:00</td></tr></table>"


def _only_range(page: str) -> tuple[time, time] | None:
    result = parse_schedule(page)
    if not isinstance(result, Ok):
        return None
    (rule,) = result.value.rules
    return rule.time.start, rule.time.end


def test_the_pool_table_wins_whatever_the_document_order() -> None:
    assert _only_range(_SAUNA_TABLE + _POOL_TABLE) == (time(6, 0), time(21, 0))
    assert _only_range(_POOL_TABLE + _SAUNA_TABLE) == (time(6, 0), time(21, 0))


def test_an_unlabelled_table_is_still_used() -> None:
    # The overwhelmingly common case: one table, no heading worth reading. Unchanged.
    assert _only_range(_UNLABELLED_TABLE) == (time(7, 0), time(19, 0))
    assert _only_range(_UNLABELLED_TABLE + _SAUNA_TABLE) == (time(7, 0), time(19, 0))


def test_a_sauna_only_page_refuses_rather_than_serving_sauna_hours() -> None:
    # Under the fail-fast contract a ParseError is a loud build abort; serving 09:00-22:00 as
    # the pool's hours would be a plausible wrong number nobody would ever notice.
    assert isinstance(parse_schedule(_SAUNA_TABLE), Err)


def test_a_combined_heading_still_counts_as_the_pool() -> None:
    combined = (
        "<h2>Öffnungszeiten Hallenbad und Sauna</h2>"
        "<table><tr><td>Mo</td><td>05:00 – 20:00</td></tr></table>"
    )
    assert _only_range(combined) == (time(5, 0), time(20, 0))
