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
from swimzh.domain.access import (
    AccompaniedChildren,
    AdultsOnly,
    GenderDiverse,
    GirlsOnly,
    PublicSwim,
    WomenOnly,
)
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.resolver import resolve_basin
from swimzh.domain.schedule import (
    AnnualWindow,
    DatePrecision,
    HolidayPolicy,
    MonthDay,
    OpenDay,
    ScheduleRule,
    TimeRange,
    Weekday,
)
from swimzh.providers.schedule_scraper import (
    _split_season,
    parse_notices,
    parse_schedule,
    scrape_schedule,
)

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


# --- the school-pool vocabulary -------------------------------------------------------
#
# Five Schulschwimmanlagen publish public swimming, in a richer `Angebot` vocabulary than the
# Hallenbäder: seven distinct strings, three of which the domain could not express at all.
# Two silent losses lived here — a continuation row (weekday cell = a bare NBSP) was dropped
# whole, and `"für\xa0Erwachsene"` never matched `"für Erwachsene"`.


def _rules_of(fixture: str) -> tuple[ScheduleRule, ...]:
    result = parse_schedule((FIXTURES / fixture).read_text(encoding="utf-8"))
    assert isinstance(result, Ok), result
    return result.value.rules


def _at(rules: tuple[ScheduleRule, ...], day: Weekday, start: time) -> ScheduleRule:
    return next(r for r in rules if day in r.weekdays and r.time.start == start)


def test_aemtler_keeps_every_published_session() -> None:
    # 7 source rows -> 7 rules. Before the continuation-row fix, the 4 rows whose weekday cell
    # is a bare NBSP were dropped and the page yielded 3.
    rules = _rules_of("schulschwimmanlage_aemtler.html")
    assert len(rules) == 7
    assert [sorted(d.name for d in r.weekdays) for r in rules] == [
        ["MONDAY"],
        ["MONDAY"],
        ["MONDAY"],
        ["THURSDAY"],
        ["THURSDAY"],
        ["FRIDAY"],
        ["FRIDAY"],
    ]


def test_the_girls_session_is_not_advertised_as_public() -> None:
    # THE harm this vocabulary exists to fix: "für Mädchen" matched neither "frau" nor
    # anything else, so an adult man was told he may attend a girls-only session.
    thursday = _at(_rules_of("schulschwimmanlage_aemtler.html"), Weekday.THURSDAY, time(17, 15))
    assert thursday.time == TimeRange(time(17, 15), time(19, 0))
    assert thursday.access == GirlsOnly()


def test_frauen_und_maedchen_is_women_only_not_girls_only() -> None:
    # The load-bearing ordering constraint: "Frauen" is tested BEFORE "Mädchen", else the
    # whole-cell meaning of "für Frauen und Mädchen" is lost.
    rules = _rules_of("schulschwimmanlage_aemtler.html")
    assert _at(rules, Weekday.MONDAY, time(18, 45)).access == WomenOnly()
    assert _at(rules, Weekday.FRIDAY, time(16, 0)).access == WomenOnly()


def test_the_nbsp_casualty_adults_only_is_recovered() -> None:
    # `"für\xa0Erwachsene"` — a non-breaking space. Without normalising it the cell fell
    # through to PublicSwim, silently telling a child an adults-only window was open.
    assert _at(_rules_of("schulschwimmanlage_aemtler.html"), Weekday.MONDAY, time(20, 15)) == (
        ScheduleRule(
            weekdays=frozenset({Weekday.MONDAY}),
            time=TimeRange(time(20, 15), time(21, 0)),
            access=AdultsOnly(),
            source_text="Öffentliches Schwimmen (für\xa0Erwachsene, Tiefe 135\xa0cm)",
        )
    )


def test_erwachsene_und_kinder_is_public_not_adults_only() -> None:
    # "Erwachsene und Kinder" means everyone; it CONTAINS "Erwachsene" and must be read first.
    monday = _at(_rules_of("schulschwimmanlage_aemtler.html"), Weekday.MONDAY, time(19, 30))
    assert monday.access == PublicSwim()


def test_altweg_publishes_a_trans_and_non_binary_session_with_its_age_bound() -> None:
    rules = _rules_of("schulschwimmanlage_altweg.html")
    assert len(rules) == 2
    late = _at(rules, Weekday.TUESDAY, time(20, 0))
    assert late.time == TimeRange(time(20, 0), time(21, 0))
    # "offen für" is the same grammar as "für" — a RESERVED session, not "also welcome".
    assert late.access == GenderDiverse(min_age=16)
    assert _at(rules, Weekday.TUESDAY, time(18, 15)).access == AdultsOnly()


def test_riedtli_publishes_an_accompanied_children_session() -> None:
    rules = _rules_of("schulschwimmanlage_riedtli.html")
    assert len(rules) == 3
    # "für Kinder nur mit Erwachsenen" contains "Erwachsene" and must be read before it.
    assert _at(rules, Weekday.MONDAY, time(16, 30)).access == AccompaniedChildren()
    assert _at(rules, Weekday.MONDAY, time(18, 0)).access == AdultsOnly()
    assert _at(rules, Weekday.THURSDAY, time(18, 0)).access == WomenOnly()


def test_tannenrauch_parses_completely() -> None:
    rules = _rules_of("schulschwimmanlage_tannenrauch.html")
    assert len(rules) == 6
    # Wednesday and Friday each publish two sessions; the second row of each inherits its day.
    assert {r.time.start for r in rules if Weekday.WEDNESDAY in r.weekdays} == {
        time(12, 30),
        time(14, 0),
    }
    assert {r.time.start for r in rules if Weekday.FRIDAY in r.weekdays} == {
        time(16, 0),
        time(17, 30),
    }


def test_borrweg_parses_completely() -> None:
    # Borrweg's roster entry carries the generic overview URL, so the build cannot reach this
    # page (S2) — but its timetable is part of the vocabulary and parses like the rest.
    rules = _rules_of("schulschwimmanlage_borrweg.html")
    assert len(rules) == 2
    assert _at(rules, Weekday.TUESDAY, time(16, 30)).access == PublicSwim()
    assert _at(rules, Weekday.TUESDAY, time(18, 30)).access == AdultsOnly()


def test_every_school_rule_keeps_the_verbatim_angebot_cell() -> None:
    # "We shouldn't compress information": classifying must not destroy what the page said.
    # The cell carries a per-session depth the basin model cannot express, so the rule keeps it.
    for fixture in (
        "schulschwimmanlage_aemtler.html",
        "schulschwimmanlage_altweg.html",
        "schulschwimmanlage_borrweg.html",
        "schulschwimmanlage_riedtli.html",
        "schulschwimmanlage_tannenrauch.html",
    ):
        for rule in _rules_of(fixture):
            assert rule.source_text.startswith("Öffentliches Schwimmen ("), fixture
            assert "Tiefe" in rule.source_text, fixture


def test_the_generic_table_format_is_unchanged_by_the_continuation_rule() -> None:
    """The continuation-row inheritance lands in `_rules_from_rows`, which serves BOTH formats.

    It is inert for format 2 only because `_parse_html_table` pre-filters rows on
    `_parse_days(r[0])` being truthy — nothing there can reach the carried set. altstetten has
    no golden-file coverage, so its exact rule set is pinned here instead.
    """
    rules = _rules_of("hallenbad_altstetten.html")
    assert {
        (frozenset(d.name for d in r.weekdays), str(r.time.start), str(r.time.end), r.access)
        for r in rules
    } == {
        (frozenset({"MONDAY", "WEDNESDAY", "FRIDAY"}), "06:00:00", "21:00:00", PublicSwim()),
        (frozenset({"TUESDAY", "THURSDAY"}), "08:00:00", "21:00:00", PublicSwim()),
        (frozenset({"SATURDAY", "SUNDAY"}), "08:00:00", "18:00:00", PublicSwim()),
    }


def test_a_source_without_a_category_column_carries_no_source_text() -> None:
    # bad-altstetten's generic table has no Angebot cell; inventing one would be a lie.
    assert all(r.source_text == "" for r in _rules_of("hallenbad_altstetten.html"))


def test_a_continuation_row_before_any_weekday_is_still_dropped() -> None:
    # Inheriting means inheriting a RESOLVED day — there is nothing to carry into the first row.
    result = parse_schedule(_row_page("\xa0", "9–16 Uhr"))
    assert isinstance(result, Err)


# --- seasonal hours (Bläsi + Käferberg regain their weekends) --------------------------


def test_blaesi_recovers_its_weekend_from_the_BARE_season_grammar() -> None:
    # The cell is `9–16 Uhr Mai–September<br>9–18 Uhr Oktober–April` — NO parentheses. Both
    # halves used to fail `_parse_time_range` outright, so Bläsi resolved Mon–Fri only.
    rules = _rules_of("hallenbad_blaesi.html")
    assert {d.name for r in rules for d in r.weekdays} == {
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    }

    weekend = sorted((r for r in rules if Weekday.SATURDAY in r.weekdays), key=lambda r: r.time.end)
    assert [(r.time, r.season) for r in weekend] == [
        (TimeRange(time(9), time(16)), AnnualWindow.whole_months(5, 9)),
        (TimeRange(time(9), time(18)), AnnualWindow.whole_months(10, 4)),
    ]
    # The Saturday row names both days, so Sunday carries the identical seasons.
    assert all(Weekday.SUNDAY in r.weekdays for r in weekend)


def test_kaeferberg_recovers_its_weekend_from_the_PARENTHESISED_season_grammar() -> None:
    # `9–16 Uhr (Mai–September)` — the same fact, different punctuation, on a page in the same
    # family. A rule anchored on the parentheses would fix this page and miss Bläsi.
    rules = _rules_of("waermebad_kaeferberg.html")
    saturday = sorted(
        (r for r in rules if r.weekdays == frozenset({Weekday.SATURDAY})), key=lambda r: r.time.end
    )
    assert [(r.time, r.season) for r in saturday] == [
        (TimeRange(time(9), time(16)), AnnualWindow.whole_months(5, 9)),
        (TimeRange(time(9), time(18)), AnnualWindow.whole_months(10, 4)),
    ]
    assert len([r for r in rules if r.weekdays == frozenset({Weekday.SUNDAY})]) == 2


def test_kaeferbergs_monday_row_returns_once_the_richer_cell_shape_is_accepted() -> None:
    # `{"value":"<p>11–15 Uhr</p>","style":{"width":"200"},"valign":"auto"}` — the row was
    # invisible to `_ROW_RE` itself, BEFORE any time parsing, so no season work could restore it.
    rules = _rules_of("waermebad_kaeferberg.html")
    assert {d.name for r in rules for d in r.weekdays} == {
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    }
    monday = [r for r in rules if r.weekdays == frozenset({Weekday.MONDAY})]
    assert [r.time for r in monday] == [TimeRange(time(11), time(15))]


def test_an_unseasoned_row_carries_no_season() -> None:
    assert all(
        r.season is None
        for r in _rules_of("hallenbad_blaesi.html")
        if Weekday.SATURDAY not in r.weekdays
    )


def test_a_weekday_qualifier_in_parentheses_is_never_read_as_a_season() -> None:
    # The same page family writes `(Sonntag–Freitag)` and `(Samstag)` into the HOURS cell as a
    # weekday qualifier. The season rule matches MONTH NAMES, never parentheses, so these are
    # left entirely alone — a `(…)`-anchored rule would have eaten them.
    assert _split_season("11–18.30 Uhr (Sonntag–Freitag)") == (
        "11–18.30 Uhr (Sonntag–Freitag)",
        None,
    )
    assert _split_season("11–18.30 Uhr (Samstag)") == ("11–18.30 Uhr (Samstag)", None)


def test_both_season_grammars_peel_to_the_same_window() -> None:
    bare, parenthesised = (
        _split_season("9–16 Uhr Mai–September"),
        _split_season("9–16 Uhr (Mai–September)"),
    )
    assert bare[1] == parenthesised[1] == AnnualWindow.whole_months(5, 9)
    # …and both leave a cell that `_parse_time_range` can read.
    assert bare[0].strip() == parenthesised[0].strip() == "9–16 Uhr"


def test_a_day_numbered_season_keeps_day_precision() -> None:
    # The outdoor grammar: "30. Mai–16. August" names days, so the window is not whole months.
    assert _split_season("9–20 Uhr (30. Mai–16. August)")[1] == AnnualWindow(
        start=MonthDay(5, 30), end=MonthDay(8, 16), precision=DatePrecision.DAY
    )


def test_a_trailing_non_season_qualifier_still_drops_the_slot() -> None:
    # Bläsi's "14–16.30 Uhr Kinderspielnachmittag" is not a season and must not become one;
    # it stays an unparsed cell (recorded loss), so nothing is invented.
    result = parse_schedule(_row_page("Mittwoch", "9–19 Uhr<br>14–16.30 Uhr Kinderspielnachmittag"))
    assert isinstance(result, Ok)
    assert [r.time for r in result.value.rules] == [TimeRange(time(9), time(19))]


def test_a_sauna_table_on_the_same_page_contributes_no_pool_rule() -> None:
    # Leimbach publishes "Öffnungszeiten Sauna und Dampfbad" as a SECOND embedded table, in the
    # richer cell shape — so widening `_ROW_RE` made it visible to a table-blind parser. Its
    # Wednesday women-only sauna slot must not surface as pool hours.
    rules = _rules_of("hallenbad_leimbach.html")
    assert not [r for r in rules if isinstance(r.access, WomenOnly)]
    wednesday = [r for r in rules if Weekday.WEDNESDAY in r.weekdays]
    assert [r.time for r in wednesday] == [TimeRange(time(6), time(21))]


def test_blaesis_scraped_weekend_resolves_to_the_published_hours() -> None:
    # End to end: page -> rules -> resolver. Both dates are SATURDAYS, one in each window.
    rules = _rules_of("hallenbad_blaesi.html")
    facility = Facility(
        identity=PoolIdentity(PoolId("hallenbad-blaesi"), "Bläsi", PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="schedule_scraper", curated=False),
        basins=(Basin(basin_id=BasinId("b"), name="Hauptbecken", rules=rules),),
    )
    calendar = ZurichCalendar(public_holidays={}, school_holidays=[], known_years=[2026])

    def hours(d: date) -> list[TimeRange]:
        day = resolve_basin(facility, facility.basins[0], d, calendar)
        assert isinstance(day, OpenDay), day
        return [s.time for s in day.sessions]

    assert hours(date(2026, 7, 18)) == [TimeRange(time(9), time(16))]  # Mai–September
    assert hours(date(2026, 1, 17)) == [TimeRange(time(9), time(18))]  # Oktober–April
