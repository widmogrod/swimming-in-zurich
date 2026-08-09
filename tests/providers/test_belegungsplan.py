"""Belegungsplan (lane-reservation) PDF parser, pinned by the committed real City fixture
plus unit coverage of the header/grid/invariant seams and the typed error mapping."""

from __future__ import annotations

import hashlib
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
    _grid_band,
    _Header,
    _parse_header,
    _parse_sectioned_basin,
    _parse_valid_from,
    _resolve,
    _segment_grid,
    _weekday_row,
    _Word,
    parse_belegungsplan,
    parse_belegungsplan_sheet,
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


def _reservation_digest(reservations: tuple[LaneReservation, ...]) -> str:
    """Order-independent SHA-256 of the full reservation set — the golden anchor guarding
    that E1's page-relative geometry produced *byte-identical* City output to the A4 parser."""

    def key(r: LaneReservation) -> tuple[object, ...]:
        return (
            tuple(sorted(w.value for w in r.weekdays)),
            r.time.start.isoformat(),
            r.time.end.isoformat(),
            tuple(sorted(r.lanes)),
            repr(r.access),
        )

    lines = [
        f"{sorted(w.value for w in r.weekdays)}|{r.time.start}-{r.time.end}|"
        f"{sorted(r.lanes)}|{r.access!r}"
        for r in sorted(reservations, key=key)
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# Captured from the pre-refactor (absolute-A4-pixel) parser. E1 must not move a single byte.
_CITY_GOLDEN_DIGEST = "ce91c0fa5394b33d90ba24af8f47f1736c35c95c259c59419c60d6c311aec1b6"


def test_city_reservations_are_byte_identical_golden(city_bytes: bytes) -> None:
    plan = parse_belegungsplan(city_bytes).unwrap_or_raise().plan
    assert len(plan.reservations) == 43
    assert _reservation_digest(plan.reservations) == _CITY_GOLDEN_DIGEST


# --- newly-listed basins pinned by committed real fixtures (Slice A / E1) -------------
#
# Reality pinned against the live PDFs. Leimbach parses as a real PARTIAL LanePlan (byte-for-
# byte unchanged by E1's page-relative geometry — see the golden guard below). Bläsi is a
# genuinely ragged movable-floor grid (34 ≠ 7×5 columns) → still a typed `SchemaMismatch`
# skip until Slice E2. Käferberg, however, is a *clean* 4×7 grid printed on an A3 sheet: the
# old parser rejected it only because its absolute 645px A4 legend clip chopped the wider
# page. E1's page-relative band (derived from the weekday anchors, not A4 pixels) is a
# superset — it now parses Käferberg as PARTIAL. City + Leimbach remain byte-identical. A
# failed parse is still downgraded by scrape_lane_plans to a reported skip, never fatal.


# Leimbach parses UNIFORM-5. Its 5th Sunday lane (x≈648) sits just right of City's old A4
# legend clamp, so the pre-E2 parser silently dropped it AND a stray Wednesday cell had
# mis-shaped the grid; the E2 anchor-derived band restores the lane and the fragment-merge
# absorbs the stray, so this golden differs from the (buggy) E1 digest. See the header note.
# Re-pinned for the grid-bottom boundary (claim-audit S1): the footer sentence's standalone
# '2' (y=542.4, 2.11×pitch below the last time label) had minted a phantom 33rd slot row —
# a "Wednesday 22:00–22:30 lane 4 SchoolReserved" session the PDF never published. The diff
# from the previous digest is EXACTLY that one deleted reservation; nothing was added.
_LEIMBACH_GOLDEN_DIGEST = "bb9a8201db8b3d391d739f429a27a5622738f7068f082273c85bd0852e1089bd"


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


def test_leimbach_reservations_are_uniform_five_golden() -> None:
    # Leimbach is uniform 5 lanes every day (its Sunday 5th lane restored by the anchor band).
    # Pin the exact reservation set + `lanes_by_weekday=None` so the shape can't silently drift.
    plan = parse_belegungsplan((FIXTURES / "leimbach.pdf").read_bytes()).unwrap_or_raise().plan
    assert plan.lanes_by_weekday is None
    assert _reservation_digest(plan.reservations) == _LEIMBACH_GOLDEN_DIGEST


def test_leimbach_footer_digit_is_not_a_session() -> None:
    # The footer sentence "Den Badegästen stehen … mindestens 2 Bahnen zur Verfügung." ends in
    # a standalone digit 2.11×pitch below the last time label. It is page prose — a promise
    # that lanes stay PUBLIC — not a grid cell, and must never mint a phantom slot row.
    plan = parse_belegungsplan((FIXTURES / "leimbach.pdf").read_bytes()).unwrap_or_raise().plan
    # 32 slot rows (06:00–22:00), not the phantom 33: the coverage denominator is the true grid.
    assert plan.coverage.cells_total == 32 * 7 * 5 == 1120
    # The phantom "Wednesday 22:00–22:30 lane 4 SchoolReserved" session is gone.
    assert _reservations_at(plan.reservations, Weekday.WEDNESDAY, time(22, 0)) == []
    # No reservation's TimeRange lies beyond the last cell-backed label (21:30–22:00).
    assert all(r.time.end <= time(22, 0) for r in plan.reservations)


def test_blaesi_real_fixture_parses_uniform_five_lanes() -> None:
    # E2 net-new parse. Bläsi's real Sunday 5th lane (x≈657) sits just right of the old City-A4
    # legend clamp, which had dropped it and made the sheet look 34-column ragged. With the
    # anchor-derived band the sheet is UNIFORM 5 lanes every day — `lanes_by_weekday` stays
    # None (the earlier {Sun:4} shape was a clip artifact, not a movable floor). PARTIAL: some
    # cells carry owners the legend doesn't resolve.
    result = parse_belegungsplan((FIXTURES / "blaesi.pdf").read_bytes())
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "Bläsi" in parsed.basin_hint
    assert parsed.plan.lane_count == 5
    assert parsed.plan.lanes_by_weekday is None
    assert parsed.plan.coverage.cells_total == 32 * 7 * 5  # a full uniform-5 grid, Sunday incl.
    assert parsed.plan.coverage.confidence is PlanConfidence.PARTIAL
    assert _check_invariants(parsed.plan.reservations, parsed.plan.lane_count) is None


def test_variobecken_real_fixture_parses_uniform_four_lanes() -> None:
    # E2 net-new parse. The City Variobecken's real Sunday 4th lane (x≈661, 32/32 public cells)
    # sits just right of the old A4 legend clamp, which dropped it and falsely reported a 4/3
    # movable floor. With the anchor-derived band the sheet is UNIFORM 4 lanes every day —
    # `lanes_by_weekday` stays None — and every cell resolves, so it is genuinely COMPLETE
    # (a true COMPLETE now, not a COMPLETE hiding a silently-clipped public lane).
    result = parse_belegungsplan((FIXTURES / "city-variobecken.pdf").read_bytes())
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "Vario" in parsed.basin_hint
    assert parsed.plan.lane_count == 4
    assert parsed.plan.lanes_by_weekday is None
    assert parsed.plan.coverage.cells_total == 32 * 7 * 4  # full uniform-4 grid, Sunday incl.
    assert parsed.plan.coverage.cells_resolved == parsed.plan.coverage.cells_total
    assert parsed.plan.coverage.confidence is PlanConfidence.COMPLETE
    assert _check_invariants(parsed.plan.reservations, parsed.plan.lane_count) is None


def test_kaeferberg_real_fixture_parses_uniform_four_lanes() -> None:
    # E1 made Käferberg parse (clean 4×7 A3 grid the old A4-pixel clip had hidden). E2 pins its
    # now-parsing shape: it takes the uniform fast path (28 = 7×4 columns), so despite being an
    # A3 sheet it is uniform — `lanes_by_weekday` stays None — not ragged this term.
    result = parse_belegungsplan((FIXTURES / "kaeferberg.pdf").read_bytes())
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "Käferberg" in parsed.basin_hint
    assert parsed.plan.lane_count == 4
    assert parsed.plan.lanes_by_weekday is None
    assert parsed.plan.coverage.confidence is PlanConfidence.PARTIAL
    assert _check_invariants(parsed.plan.reservations, parsed.plan.lane_count) is None


# --- Oerlikon sheets: single 8-lane grid + stacked Teil-sectioned basins (E3) --------
#
# Verified from the committed A2 PDFs (pdfplumber word extraction), NOT calibrated to whatever
# the parser first emitted:
#   * oerlikon-schwimmerbecken.pdf   — ONE basin, a clean uniform 8-lane × 7-day grid
#     ("8 Bahnen" over every weekday, 56 = 7×8 data columns). NOT sectioned; `section` stays
#     None. The old parser rejected it only because its title sits a line higher on the taller
#     A2 sheet than the fixed A4 title window allowed.
#   * oerlikon-nichtschwimmer-sprungbecken.pdf — TWO basins stacked side by side
#     ("Nichtschwimmer" + "Sprungbecken", 14 = 2×7 weekday anchors). Each weekday column is
#     genuinely split into "Teil 1 / Teil 2" — so each basin is a uniform 7×2 grid whose two
#     lanes carry D's `section` labels. This is the only committed sheet that names sections.


def _section_reservation_digest(reservations: tuple[LaneReservation, ...]) -> str:
    """Like `_reservation_digest` but folds in `section` — the E3 golden anchor for the
    Teil-sectioned Oerlikon basins."""

    def key(r: LaneReservation) -> tuple[object, ...]:
        return (
            tuple(sorted(w.value for w in r.weekdays)),
            r.time.start.isoformat(),
            r.time.end.isoformat(),
            tuple(sorted(r.lanes)),
            repr(r.access),
            r.section or "",
        )

    lines = [
        f"{sorted(w.value for w in r.weekdays)}|{r.time.start}-{r.time.end}|"
        f"{sorted(r.lanes)}|{r.access!r}|{r.section}"
        for r in sorted(reservations, key=key)
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# Re-pinned for the grid-bottom boundary (claim-audit S1): the footer sentence's standalone
# '4' (y=780.3, 2.65×pitch below the last time label) had minted a phantom 35th slot row —
# a "Thursday 23:00–23:30 lane 8 SchoolReserved" session the PDF never published. The diff
# from the previous digest is EXACTLY that one deleted reservation; nothing was added.
_OERLIKON_SCHWIMMER_DIGEST = "2813ca96b6d8dc072ae6fcb13692f11d060c482fb308ab4d27dfb7331f1b8d29"
_NICHTSCHWIMMER_DIGEST = "86edde12fcfc4452502fc3cf55f6ee2549cd557e4958f38d574ebba2d6b8c628"
_SPRUNGBECKEN_DIGEST = "b9a762994cbbc00235e7f6403482ca6aeb96eb33db9c117293b60e1b7004bf0f"


def test_oerlikon_schwimmerbecken_parses_uniform_eight_lanes() -> None:
    # A2 sheet, single basin, clean uniform 8-lane × 7-day grid — no named sections.
    result = parse_belegungsplan((FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes())
    assert isinstance(result, Ok), result
    parsed = result.value
    assert "Oerlikon" in parsed.basin_hint and "Schwimmer" in parsed.basin_hint
    plan = parsed.plan
    assert plan.lane_count == 8
    assert plan.valid_from == date(2026, 1, 1)
    assert plan.lanes_by_weekday is None  # uniform 7×8 fast path, not ragged/clipped
    # No "Teil" sections on this sheet — every reservation stays section-free.
    assert all(r.section is None for r in plan.reservations)
    # Honest PARTIAL: some slots are blank (pool closed) — but no lane carries an unknown owner,
    # so this is never a false COMPLETE hiding a dropped column.
    assert plan.coverage.confidence is PlanConfidence.PARTIAL
    assert plan.coverage.unresolved_lanes == frozenset()
    assert _check_invariants(plan.reservations, plan.lane_count) is None
    assert _reservation_digest(plan.reservations) == _OERLIKON_SCHWIMMER_DIGEST


def test_oerlikon_schwimmerbecken_footer_digit_is_not_a_session() -> None:
    # Same footer-prose trap as Leimbach: the standalone '4' of "… mindestens 4 Bahnen zur
    # Verfügung." sits 2.65×pitch below the last time label and had minted a phantom 35th row.
    plan = (
        parse_belegungsplan((FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes())
        .unwrap_or_raise()
        .plan
    )
    # 34 slot rows, not the phantom 35: the coverage denominator is the true grid.
    assert plan.coverage.cells_total == 34 * 7 * 8
    # The phantom "Thursday 23:00–23:30 lane 8 SchoolReserved" session is gone; the real late
    # sessions (e.g. Tuesday Kanupolo until 23:00) survive.
    assert _reservations_at(plan.reservations, Weekday.THURSDAY, time(23, 0)) == []
    assert all(r.time.end <= time(23, 0) for r in plan.reservations)


def test_oerlikon_schwimmerbecken_via_sheet_is_single_basin() -> None:
    result = parse_belegungsplan_sheet((FIXTURES / "oerlikon-schwimmerbecken.pdf").read_bytes())
    assert isinstance(result, Ok), result
    assert len(result.value) == 1  # single-basin sheet -> 1-tuple
    assert result.value[0].plan.lane_count == 8


def test_oerlikon_sprungbecken_sheet_splits_into_two_sectioned_basins() -> None:
    # The stacked sheet yields ONE ParsedPlan per basin, each a 2-lane grid whose lanes are the
    # genuinely-named "Teil 1 / Teil 2" sections (this is where D's `section` earns its keep).
    result = parse_belegungsplan_sheet(
        (FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf").read_bytes()
    )
    assert isinstance(result, Ok), result
    plans = result.value
    assert len(plans) == 2
    by_hint = {p.basin_hint: p.plan for p in plans}
    assert any("Nichtschwimmer" in h for h in by_hint)
    assert any("Sprungbecken" in h for h in by_hint)

    for hint, plan in by_hint.items():
        assert plan.lane_count == 2, hint
        assert plan.valid_from == date(2025, 11, 26), hint
        assert plan.lanes_by_weekday is None, hint
        # Exactly the two named sections, each pinned to its own lane (Teil 1 -> lane 1,
        # Teil 2 -> lane 2): sections never merge and no lane escapes 1..2.
        assert {r.section for r in plan.reservations} == {"Teil 1", "Teil 2"}, hint
        for r in plan.reservations:
            expected_lane = 1 if r.section == "Teil 1" else 2
            assert r.lanes == frozenset({expected_lane}), (hint, r.section, r.lanes)
        assert plan.coverage.confidence is PlanConfidence.PARTIAL, hint
        assert _check_invariants(plan.reservations, plan.lane_count) is None, hint


def test_parse_belegungsplan_sheet_single_basin_matches_single_parser() -> None:
    # A single-basin sheet (City) returns a 1-tuple byte-identical to `parse_belegungsplan`.
    city = FIXTURE.read_bytes()
    sheet = parse_belegungsplan_sheet(city)
    assert isinstance(sheet, Ok)
    assert len(sheet.value) == 1
    assert _reservation_digest(sheet.value[0].plan.reservations) == _CITY_GOLDEN_DIGEST


def test_parse_belegungsplan_sheet_unreadable_bytes_is_typed_error() -> None:
    # A sheet-level parse still funnels every failure through a typed `Result` (no exceptions).
    result = parse_belegungsplan_sheet(b"this is not a pdf")
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_parse_sectioned_basin_without_cells_is_schema_mismatch() -> None:
    # A stacked-basin sub-grid with no data cells fails as a typed SchemaMismatch, never raising.
    group = [_word(name, 100.0 + 50 * i, 40.0) for i, name in enumerate(["Mo", "Di", "Mi"])]
    result = _parse_sectioned_basin(
        words=group,  # only the weekday anchors, no digit cells below
        group=group,
        legend={1: "Öffentlichkeit"},
        valid_from=None,
        slots=[TimeRange(time(6, 0), time(6, 30))],
        data_top=100.0,
        spec=GridSpec(),
        page_width=1190.0,
    )
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "no grid cells" in result.error.detail


def test_oerlikon_sprungbecken_basins_are_golden() -> None:
    result = parse_belegungsplan_sheet(
        (FIXTURES / "oerlikon-nichtschwimmer-sprungbecken.pdf").read_bytes()
    )
    by_hint = {p.basin_hint: p.plan for p in result.unwrap_or_raise()}
    nichtschwimmer = next(p for h, p in by_hint.items() if "Nichtschwimmer" in h)
    sprungbecken = next(p for h, p in by_hint.items() if "Sprungbecken" in h)
    assert _section_reservation_digest(nichtschwimmer.reservations) == _NICHTSCHWIMMER_DIGEST
    assert _section_reservation_digest(sprungbecken.reservations) == _SPRUNGBECKEN_DIGEST


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


# --- page-relative geometry (E1) ----------------------------------------------------


def test_gridspec_has_no_absolute_a4_pixel_bands() -> None:
    # The A4 pixel constants (central_x / legend_x_min absolute values) are gone; the band
    # is derived page-relative, so only ratios/tolerances survive on GridSpec. There is no
    # right-hand legend page-fraction (it clipped wider sheets) — only the left gutter.
    spec = GridSpec()
    assert not hasattr(spec, "central_x")
    assert not hasattr(spec, "legend_x_min")
    assert not hasattr(spec, "legend_margin_ratio")
    assert 0.0 < spec.grid_margin_ratio < 1.0


def test_grid_band_is_derived_from_weekday_anchors() -> None:
    # Seven anchors spaced 50 apart (centres 200..500) sit clear of the left margin, so the
    # band is the pure anchor derivation: [c0 - half_day, c6 + half_day], half_day = span/12.
    anchors = [_word("x", 200.0 + 50 * i, 60.0, width=0.0) for i in range(7)]
    lo, hi = _grid_band(anchors, GridSpec(), page_width=841.92)
    assert lo == pytest.approx(175.0)  # 200 - 300/12
    assert hi == pytest.approx(525.0)  # 500 + 300/12


def test_grid_band_right_edge_follows_anchors_not_a_page_fraction() -> None:
    # The right edge is purely anchor-derived (c6 + half_day) — never clamped to a City-A4
    # legend fraction, which would cut INSIDE a wider sheet's band and drop its Sunday lane.
    anchors = [_word("x", 120.0 + 90 * i, 60.0, width=0.0) for i in range(7)]  # centres 120..660
    _lo, hi = _grid_band(anchors, GridSpec(), page_width=841.92)
    assert hi == pytest.approx(660.0 + 540.0 / 12)  # c6 + half_day = 705, NOT the old 645 clamp


def test_weekday_row_recognizes_abbreviated_names() -> None:
    # A header spelled "Mo Di Mi Do Fr Sa So" is recognised as the weekday anchor row.
    abbr = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    words = [_word(name, 100.0 + 80 * i, 60.0) for i, name in enumerate(abbr)]
    row = _weekday_row(words)
    assert row is not None
    assert len(row) == 7


def test_weekday_row_picks_densest_row_over_stray_weekday_words() -> None:
    # A stray "So" higher up (e.g. prose) must not be mistaken for the header row.
    words = [_word("So", 300.0, 20.0)]  # stray, topmost but alone
    words += [_word(name.capitalize(), 90.0 + 80 * i, 60.0) for i, name in enumerate(_DAYS)]
    row = _weekday_row(words)
    assert row is not None
    assert len(row) == 7  # the full 7-cell row, not the lone stray
    assert min(w.top for w in row) == 60.0


def test_parse_header_reads_abbreviated_weekday_header() -> None:
    abbr = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    words = [_word(name, 90.0 + 80 * i, 60.0) for i, name in enumerate(abbr)]
    words += [_word("6", 88.0, 74.0), _word("Bahnen", 97.0, 74.0)]
    words += [_word("Hallenbad", 200.0, 40.0), _word("Oerlikon", 250.0, 40.0)]
    header = _parse_header(words, GridSpec()).unwrap_or_raise()
    assert header.lane_count == 6
    assert header.basin_hint == "Hallenbad Oerlikon"


# --- grid segmentation seams --------------------------------------------------------


def _header(lane_count: int = 6) -> _Header:
    return _Header(
        basin_hint="X",
        lane_count=lane_count,
        valid_from=None,
        weekday_top=60.0,
        bahnen_top=74.0,
        grid_x_min=70.0,
        grid_x_max=645.0,
        weekday_centres=tuple(110.0 + 80.0 * i for i in range(7)),  # 7 evenly-spaced anchors
    )


def test_segment_grid_no_cells_is_schema_mismatch() -> None:
    result = _segment_grid(_header_words(), GridSpec(), _header())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "no grid cells" in result.error.detail


def _ragged_grid_words(sunday_lanes: int = 1) -> list[_Word]:
    """A 2-lane-nominal grid across 2 slots where Sunday carries `sunday_lanes` lanes — a
    deliberately ragged/truncated day grid (E2). Two left-gutter time-label rows name the
    slots; every cell is code 1 (public)."""
    words: list[_Word] = []
    for row, top in enumerate((100.0, 120.0)):
        for weekday, centre in enumerate(110.0 + 80.0 * i for i in range(7)):
            lanes = sunday_lanes if weekday == 6 else 2
            offsets = [0.0] if lanes == 1 else [-8.0, 8.0]
            for off in offsets:
                words.append(_word("1", centre + off, top, width=1.0))
        label = "06.00" if row == 0 else "06.30"
        second = "06.30" if row == 0 else "07.00"
        words += [_word(label, 20.0, top), _word("-", 45.0, top), _word(second, 52.0, top)]
    return words


def test_segment_grid_ragged_columns_resolve_per_weekday_not_schema_mismatch() -> None:
    # A grid whose day columns don't form a clean 7×lane_count rectangle (Sunday truncated to
    # one lane) no longer aborts as a SchemaMismatch — it segments per weekday and records the
    # ragged shape. This is exactly the movable-floor case E2 unlocks.
    result = _segment_grid(_ragged_grid_words(sunday_lanes=1), GridSpec(), _header(lane_count=2))
    assert isinstance(result, Ok), result
    grid = result.value
    assert grid.lanes_by_weekday is not None
    assert grid.lanes_by_weekday[Weekday.SUNDAY] == 1
    assert grid.lanes_by_weekday[Weekday.MONDAY] == 2


def test_ragged_grid_counts_cells_honestly_and_is_partial() -> None:
    # The truncated Sunday lane contributes fewer cells to the denominator (never fabricated),
    # so coverage stays honest: 2 slots × (6 days × 2 + 1 Sunday lane) = 26 cells, all public.
    grid = _segment_grid(_ragged_grid_words(sunday_lanes=1), GridSpec(), _header(lane_count=2))
    resolved = _resolve(grid.unwrap_or_raise(), {1: "Öffentlichkeit"})
    assert resolved.cells_total == 2 * (6 * 2 + 1)
    assert resolved.cells_resolved == resolved.cells_total


def test_segment_grid_excludes_digit_below_label_span() -> None:
    # A standalone digit well below the last time label (the footer sentence's lane-count
    # promise) is page prose, not a grid cell. Labels sit at tops 100/120 (pitch 20), so the
    # boundary is 120 + 1.0×20 = 140; a digit at 160 (2×pitch below the last label) must be
    # excluded. Without the bottom boundary it minted a third slot row — and here would abort
    # the whole sheet as "3 slot rows but only 2 time labels".
    words = _ragged_grid_words(sunday_lanes=2)
    words.append(_word("2", 110.0, 160.0, width=1.0))  # footer digit inside the x-band
    result = _segment_grid(words, GridSpec(), _header(lane_count=2))
    assert isinstance(result, Ok), result
    grid = result.value
    assert len(grid.slots) == 2  # the two labelled rows only — no phantom third row
    assert all(row in (0, 1) for (_wd, _lane, row) in grid.codes)


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
    def __init__(self, words: list[dict[str, object]], width: float = 841.92) -> None:
        self._words = words
        self.width = width

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
