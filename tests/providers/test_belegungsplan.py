"""Belegungsplan (lane-reservation) PDF parser, pinned by the committed real City fixture
plus unit coverage of the header/grid/invariant seams and the typed error mapping."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from datetime import date, time
from pathlib import Path

import httpx
import pytest

from swimzh.core.errors import HttpStatus, ParseError, ProviderSpecific, SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved
from swimzh.domain.lane_plan import LaneReservation, PlanConfidence
from swimzh.domain.schedule import TimeRange, Weekday
from swimzh.providers import belegungsplan
from swimzh.providers.belegungsplan import (
    GridSpec,
    _check_invariants,
    _code_to_access,
    _Grid,
    _Header,
    _parse_header,
    _parse_valid_from,
    _resolve,
    _segment_grid,
    _Word,
    parse_belegungsplan,
    scrape_belegungsplan,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "city-schwimmerbecken.pdf"


@pytest.fixture(scope="module")
def city_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _reservations_at(
    reservations: tuple[LaneReservation, ...], weekday: Weekday, t: time
) -> list[LaneReservation]:
    return [r for r in reservations if weekday in r.weekdays and r.time.contains(t)]


# --- the committed real fixture -----------------------------------------------------


def test_parses_real_city_fixture_header(city_bytes: bytes) -> None:
    result = parse_belegungsplan(city_bytes)
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "City" in parsed.basin_hint
    assert parsed.plan.lane_count == 6
    assert parsed.plan.valid_from == date(2026, 1, 1)


def test_real_fixture_is_fully_resolved(city_bytes: bytes) -> None:
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    # 32 slots (06:00–22:00) × 7 days × 6 lanes, every cell a known owner.
    assert plan.coverage.cells_total == 32 * 7 * 6
    assert plan.coverage.cells_resolved == plan.coverage.cells_total
    assert plan.coverage.confidence is PlanConfidence.COMPLETE
    assert plan.coverage.unresolved_lanes == frozenset()


def test_real_fixture_tuesday_early_lanes(city_bytes: bytes) -> None:
    # Feasibility anchor: Tue 06:00 = 4/6 lanes public, lanes 1–2 held by ASVZ + Swimatic.
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    active = _reservations_at(plan.reservations, Weekday.TUESDAY, time(6, 0))
    owners = {}
    for reservation in active:
        for lane in reservation.lanes:
            owners[lane] = reservation.access
    assert owners[1] == ClubReserved(club="ASVZ")
    assert owners[2] == ClubReserved(club="Swimatic")
    public_lanes = sum(len(r.lanes) for r in active if isinstance(r.access, PublicSwim))
    assert public_lanes == 4


def test_real_fixture_stores_public_and_school_explicitly(city_bytes: bytes) -> None:
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    assert any(isinstance(r.access, PublicSwim) for r in plan.reservations)
    assert any(isinstance(r.access, SchoolReserved) for r in plan.reservations)
    # Only the three sanctioned owner arms are ever emitted (decision #1 invariant).
    assert all(
        isinstance(r.access, PublicSwim | SchoolReserved | ClubReserved) for r in plan.reservations
    )


def test_real_fixture_passes_disjointness(city_bytes: bytes) -> None:
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    assert _check_invariants(plan.reservations, plan.lane_count) is None


# --- newly-listed basins pinned by committed real fixtures (Slice A) -----------------
#
# Reality pinned against the live PDFs (verified 2026-07-21): only Leimbach parses under the
# current City-A4 geometry — as a real, PARTIAL LanePlan. Bläsi/Käferberg are movable-floor
# basins whose per-weekday lane counts make the grid ragged (fewer than 7×lane_count columns),
# so they are typed `SchemaMismatch` skips until the anchor-derived parser (Slice E2). Either
# way scrape_lane_plans downgrades a failed parse to a reported skip, never fatal.


def test_leimbach_real_fixture_parses_to_partial_plan() -> None:
    result = parse_belegungsplan((FIXTURES / "leimbach.pdf").read_bytes())
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "Leimbach" in parsed.basin_hint
    assert parsed.plan.lane_count == 5
    assert parsed.plan.valid_from == date(2026, 3, 3)
    # Some cells carry owners the legend doesn't resolve -> a real but PARTIAL plan.
    assert parsed.plan.coverage.confidence is PlanConfidence.PARTIAL
    assert parsed.plan.reservations  # non-empty
    assert _check_invariants(parsed.plan.reservations, parsed.plan.lane_count) is None


def test_blaesi_real_fixture_is_schema_mismatch_until_slice_e() -> None:
    result = parse_belegungsplan((FIXTURES / "blaesi.pdf").read_bytes())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "columns" in result.error.detail  # ragged movable-floor grid


def test_kaeferberg_real_fixture_is_schema_mismatch_until_slice_e() -> None:
    result = parse_belegungsplan((FIXTURES / "kaeferberg.pdf").read_bytes())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "columns" in result.error.detail  # ragged movable-floor grid


# --- owner-relabel trap: an unknown code is never public ----------------------------


def test_unknown_owner_label_degrades_to_partial_never_public(
    city_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Drop every club/school code from the legend: those cells must become *unresolved*
    # (counted in coverage), never silently counted as public.
    monkeypatch.setattr(
        belegungsplan,
        "_parse_legend",
        lambda *_a, **_k: {1: "Öffentlichkeit"},
    )
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    assert plan.coverage.confidence is PlanConfidence.PARTIAL
    assert plan.coverage.unresolved_lanes  # non-empty
    assert plan.coverage.cells_resolved < plan.coverage.cells_total
    # Tue 06:00 lane 1 was ASVZ (now unknown) — it must NOT have become public.
    active = _reservations_at(plan.reservations, Weekday.TUESDAY, time(6, 0))
    for reservation in active:
        if isinstance(reservation.access, PublicSwim):
            assert 1 not in reservation.lanes


# --- code -> access mapping ---------------------------------------------------------


def test_code_to_access_maps_public_school_and_clubs() -> None:
    assert _code_to_access("Öffentlichkeit") == PublicSwim()
    assert _code_to_access("Schulen") == SchoolReserved()
    assert _code_to_access("ASVZ") == ClubReserved(club="ASVZ")


# --- valid-from date parsing --------------------------------------------------------


def test_parse_valid_from_reads_german_date() -> None:
    assert _parse_valid_from("ab 01. Januar 2026") == date(2026, 1, 1)
    assert _parse_valid_from("ab 1. September 2025") == date(2025, 9, 1)


def test_parse_valid_from_rejects_unknown_month_and_bad_day() -> None:
    assert _parse_valid_from("ab 01. Foobar 2026") is None
    assert _parse_valid_from("ab 31. Februar 2026") is None  # not a real date
    assert _parse_valid_from("no date here") is None


# --- header seams -------------------------------------------------------------------


def _word(text: str, x0: float, top: float, width: float = 8.0) -> _Word:
    return _Word(text=text, x0=x0, x1=x0 + width, top=top)


def _header_words() -> list[_Word]:
    """A minimal well-formed header: weekday row, a 'Bahnen' row with a lane digit, title."""
    words = [_word(name.capitalize(), 90.0 + 80 * i, 60.0) for i, name in enumerate(_DAYS)]
    words += [_word("6", 88.0, 74.0), _word("Bahnen", 97.0, 74.0)]
    words += [_word("Hallenbad", 200.0, 40.0), _word("City", 250.0, 40.0)]
    words += [_word("ab", 665.0, 43.0), _word("01.", 679.0, 43.0)]
    words += [_word("Januar", 695.0, 43.0), _word("2026", 729.0, 43.0)]
    return words


_DAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]


def test_parse_header_reads_title_lane_count_and_valid_from() -> None:
    header = _parse_header(_header_words(), GridSpec()).unwrap_or_raise()
    assert header.lane_count == 6
    assert header.basin_hint == "Hallenbad City"
    assert header.valid_from == date(2026, 1, 1)


def test_parse_header_missing_weekday_row_is_schema_mismatch() -> None:
    result = _parse_header([_word("Bahnen", 97.0, 74.0)], GridSpec())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_parse_header_missing_bahnen_row_is_schema_mismatch() -> None:
    words = [_word(name.capitalize(), 90.0 + 80 * i, 60.0) for i, name in enumerate(_DAYS)]
    result = _parse_header(words, GridSpec())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_parse_header_ambiguous_lane_count_is_schema_mismatch() -> None:
    words = [_word(name.capitalize(), 90.0 + 80 * i, 60.0) for i, name in enumerate(_DAYS)]
    # Two 'Bahnen' columns disagree on the lane digit -> not determinable.
    words += [_word("6", 88.0, 74.0), _word("Bahnen", 97.0, 74.0)]
    words += [_word("4", 168.0, 74.0), _word("Bahnen", 177.0, 74.0)]
    result = _parse_header(words, GridSpec())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_parse_header_missing_title_is_schema_mismatch() -> None:
    words = [_word(name.capitalize(), 90.0 + 80 * i, 60.0) for i, name in enumerate(_DAYS)]
    words += [_word("6", 88.0, 74.0), _word("Bahnen", 97.0, 74.0)]  # no title band words
    result = _parse_header(words, GridSpec())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


# --- grid segmentation seams --------------------------------------------------------


def _header(lane_count: int = 6) -> _Header:
    return _Header(
        basin_hint="X", lane_count=lane_count, valid_from=None, weekday_top=60.0, bahnen_top=74.0
    )


def test_segment_grid_no_cells_is_schema_mismatch() -> None:
    result = _segment_grid(_header_words(), GridSpec(), _header())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "no grid cells" in result.error.detail


def test_segment_grid_wrong_column_count_is_schema_mismatch() -> None:
    # Three digit columns where 7×6 = 42 are required.
    cells = [_word("1", 100.0 + 20 * c, 100.0, width=1.0) for c in range(3)]
    result = _segment_grid(cells, GridSpec(), _header())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "columns" in result.error.detail


def test_segment_grid_missing_time_labels_is_schema_mismatch() -> None:
    # A full 42-column × 2-row grid but no left-hand time labels to name the slots.
    cells: list[_Word] = []
    for col in range(42):
        for row in range(2):
            cells.append(_word("1", 80.0 + 13.0 * col, 100.0 + 12.6 * row, width=1.0))
    result = _segment_grid(cells, GridSpec(), _header())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "time labels" in result.error.detail


# --- resolution / RLE on a synthetic grid -------------------------------------------


def test_resolve_rle_merges_lanes_and_days_and_flags_unknown() -> None:
    slots = [TimeRange(time(6, 0), time(6, 30)), TimeRange(time(6, 30), time(7, 0))]
    legend = {1: "Öffentlichkeit"}  # code 2 is unknown -> unresolved
    codes: dict[tuple[Weekday, int, int], int] = {}
    for weekday in Weekday:
        for lane in (1, 2):
            for row in (0, 1):
                codes[(weekday, lane, row)] = 1 if lane == 1 else 2
    grid = _Grid(codes=codes, slots=slots, lane_count=2)
    resolved = _resolve(grid, legend)

    # Lane 1 public across both slots and all 7 days collapses to a single reservation.
    public = [r for r in resolved.reservations if isinstance(r.access, PublicSwim)]
    assert len(public) == 1
    only = public[0]
    assert only.lanes == frozenset({1})
    assert only.weekdays == frozenset(Weekday)
    assert only.time == TimeRange(time(6, 0), time(7, 0))
    # Lane 2 (code 2, unknown) stays unresolved — never emitted, flagged in coverage.
    assert resolved.unresolved_lanes == frozenset({2})
    assert resolved.cells_resolved == 7 * 2  # lane 1 only, 7 days × 2 slots
    assert resolved.cells_total == 2 * 7 * 2


# --- invariants ---------------------------------------------------------------------


def test_check_invariants_accepts_disjoint_reservations() -> None:
    reservations = (
        LaneReservation(
            frozenset({Weekday.MONDAY}),
            TimeRange(time(6, 0), time(8, 0)),
            frozenset({1, 2}),
            ClubReserved(club="ASVZ"),
        ),
        LaneReservation(
            frozenset({Weekday.MONDAY}),
            TimeRange(time(6, 0), time(8, 0)),
            frozenset({3, 4}),
            PublicSwim(),
        ),
    )
    assert _check_invariants(reservations, 6) is None


def test_check_invariants_rejects_overlapping_shared_lanes() -> None:
    reservations = (
        LaneReservation(
            frozenset({Weekday.MONDAY}),
            TimeRange(time(6, 0), time(8, 0)),
            frozenset({1, 2}),
            ClubReserved(club="ASVZ"),
        ),
        LaneReservation(
            frozenset({Weekday.MONDAY}),
            TimeRange(time(7, 0), time(9, 0)),
            frozenset({2, 3}),
            PublicSwim(),
        ),
    )
    error = _check_invariants(reservations, 6)
    assert isinstance(error, ParseError)
    assert "lanes [2]" in error.detail


def test_check_invariants_rejects_lane_out_of_range() -> None:
    reservations = (
        LaneReservation(
            frozenset({Weekday.MONDAY}),
            TimeRange(time(6, 0), time(8, 0)),
            frozenset({7}),
            PublicSwim(),
        ),
    )
    error = _check_invariants(reservations, 6)
    assert isinstance(error, ParseError)
    assert "outside 1..6" in error.detail


# --- error mapping: bytes / optional dependency -------------------------------------


def test_unreadable_bytes_is_parse_error() -> None:
    result = parse_belegungsplan(b"this is not a pdf")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_missing_pdfplumber_is_provider_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate the optional 'pdf' extra not being installed.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    result = parse_belegungsplan(b"%PDF-1.7 whatever")
    assert isinstance(result, Err)
    assert isinstance(result.error, ProviderSpecific)
    assert "pdfplumber" in str(result.error.detail)


class _FakePage:
    def __init__(self, words: list[dict[str, object]]) -> None:
        self._words = words

    def extract_words(self) -> list[dict[str, object]]:
        return self._words


class _FakePdf:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdf:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _fake_open(pdf: _FakePdf) -> Callable[[io.BytesIO], _FakePdf]:
    def opener(_stream: io.BytesIO) -> _FakePdf:
        return pdf

    return opener


def test_pdf_without_pages_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", _fake_open(_FakePdf(pages=[])))
    result = parse_belegungsplan(b"%PDF-1.7")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)
    assert "empty PDF" in result.error.detail


def test_pdf_with_no_words_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", _fake_open(_FakePdf(pages=[_FakePage([])])))
    result = parse_belegungsplan(b"%PDF-1.7")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)
    assert "no text" in result.error.detail


def test_no_legend_is_schema_mismatch(monkeypatch: pytest.MonkeyPatch, city_bytes: bytes) -> None:
    monkeypatch.setattr(belegungsplan, "_parse_legend", lambda *_a, **_k: {})
    result = parse_belegungsplan(city_bytes)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "no legend" in result.error.detail


# --- fetch + scrape seams -----------------------------------------------------------


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


def test_scrape_fetches_and_parses(city_bytes: bytes) -> None:
    client = _client(lambda _r: httpx.Response(200, content=city_bytes))
    result = scrape_belegungsplan(client, "https://example.test/city.pdf")
    assert isinstance(result, Ok)
    assert result.value.plan.lane_count == 6


def test_scrape_propagates_http_error() -> None:
    client = _client(lambda _r: httpx.Response(503, text="down"))
    result = scrape_belegungsplan(client, "https://example.test/city.pdf")
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
