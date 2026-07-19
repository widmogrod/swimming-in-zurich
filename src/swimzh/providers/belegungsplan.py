"""Parse a per-basin "Belegungsplan" (lane-reservation) PDF into a `LanePlan`.

The PDF is a weekly grid — *7 weekdays × N lanes × 30-min slots* — each cell a legend
code (1 = Öffentlichkeit/public, 2 = Schulen, 3..N = named clubs), with a header carrying
the basin name, the lane count ("6 Bahnen"), and a valid-from date ("ab 01. Januar 2026"),
and a right-hand legend mapping codes to owner names.

`pdfplumber` reconstructs per-word bounding boxes; this module clusters the digit
x-coordinates into 7×N lane columns and their y-coordinates into slot rows, maps each cell
to an owner via the legend, RLE-compresses contiguous same-owner regions into
`LaneReservation`s, then runs two invariants (per-slot lane disjointness, lanes ⊆ {1..N})
before returning. Every failure is a typed `ProviderError` (no new variants):

  * missing `pdfplumber`                         -> `ProviderSpecific`
  * undecodable / no-text PDF                     -> `ParseError` ("unreadable PDF")
  * header/legend/grid missing or layout changed  -> `SchemaMismatch`
  * disjointness / ⊆ violation                    -> `ParseError`
  * low-but-nonzero coverage                       -> `Ok` + `PlanCoverage.PARTIAL`

An unrecognised owner label is **never** treated as public: that lane at that slot is left
unresolved (counted in `PlanCoverage`), preserving the three-way distinction between public
(explicit), unknown (coverage), and absent (not represented).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time

from swimzh.core.errors import ParseError, ProviderError, ProviderSpecific, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved, SessionAccess
from swimzh.domain.lane_plan import LanePlan, LaneReservation, PlanConfidence, PlanCoverage
from swimzh.domain.schedule import TimeRange, Weekday

_SOURCE = "belegungsplan"

_WEEKDAY_NAMES: dict[str, Weekday] = {
    "montag": Weekday.MONDAY,
    "dienstag": Weekday.TUESDAY,
    "mittwoch": Weekday.WEDNESDAY,
    "donnerstag": Weekday.THURSDAY,
    "freitag": Weekday.FRIDAY,
    "samstag": Weekday.SATURDAY,
    "sonntag": Weekday.SUNDAY,
}
_MONTHS: dict[str, int] = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
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
_VALID_FROM_RE = re.compile(r"ab\s+(\d{1,2})\.\s*([A-Za-zäöü]+)\s+(\d{4})", re.IGNORECASE)
_TIME_LABEL_RE = re.compile(r"(\d{1,2})\.(\d{2}).*?(\d{1,2})\.(\d{2})")


@dataclass(frozen=True, slots=True)
class GridSpec:
    """Provider-local layout tolerances (pixels, pdfplumber top-left origin)."""

    x_tol: float = 5.0  # cluster digit x-centres into lane columns
    y_tol: float = 6.0  # cluster digit tops into slot rows
    legend_x_min: float = 645.0  # right-hand legend / valid-from live beyond this x
    central_x: tuple[float, float] = (70.0, 645.0)  # the day-grid x band
    title_gap: float = 8.0  # basin title sits at least this far above the weekday row
    bahnen_gap: float = 5.0  # data cells sit at least this far below the "Bahnen" row


_DEFAULT_GRID_SPEC = GridSpec()  # City layout tolerances; a module singleton for defaults


@dataclass(frozen=True, slots=True)
class _Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True, slots=True)
class _Header:
    basin_hint: str
    lane_count: int
    valid_from: date | None
    weekday_top: float
    bahnen_top: float


@dataclass(frozen=True, slots=True)
class ParsedPlan:
    """A parsed plan plus the PDF-header basin name, reconciled to a `Basin` in silver."""

    basin_hint: str
    plan: LanePlan


# --- generic 1-D clustering ---------------------------------------------------------


def _cluster(values: list[float], tol: float) -> list[float]:
    """Cluster sorted 1-D values; return each cluster's mean centre, ascending."""
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _nearest(value: float, centres: list[float]) -> int:
    return min(range(len(centres)), key=lambda i: abs(centres[i] - value))


# --- header -------------------------------------------------------------------------


def _parse_valid_from(text: str) -> date | None:
    match = _VALID_FROM_RE.search(text)
    if match is None:
        return None
    day, month_name, year = match.group(1), match.group(2).lower(), match.group(3)
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _lane_count(words: list[_Word], bahnen_top: float) -> int | None:
    """The digit immediately left of each "Bahnen" header; require all columns to agree."""
    counts: set[int] = set()
    bahnen = [w for w in words if abs(w.top - bahnen_top) <= 2 and w.text.lower() == "bahnen"]
    digits = [w for w in words if abs(w.top - bahnen_top) <= 2 and w.text.isdigit()]
    for label in bahnen:
        left = [d for d in digits if d.x1 <= label.x0 and label.x0 - d.x1 < 6]
        if left:
            counts.add(int(left[-1].text))
    if len(counts) != 1:
        return None
    return counts.pop()


def _row_text(words: list[_Word]) -> str:
    return " ".join(w.text for w in sorted(words, key=lambda w: w.x0)).strip()


def _basin_title(words: list[_Word], spec: GridSpec, weekday_top: float) -> str:
    """The title line ("Hallenbad City Schwimmerbecken"), a central band above the weekdays."""
    lo, hi = spec.central_x
    band_top, band_bottom = weekday_top - 30, weekday_top - spec.title_gap
    title_words = [w for w in words if band_top < w.top < band_bottom and lo <= w.xc <= hi]
    return _row_text(title_words)


def _header_valid_from(words: list[_Word], spec: GridSpec, weekday_top: float) -> date | None:
    """The "ab 01. Januar 2026" line — right of the grid, above the weekday row (clear of
    the legend, which begins lower down)."""
    right = [w for w in words if w.xc > spec.legend_x_min and w.top < weekday_top]
    return _parse_valid_from(_row_text(right))


def _parse_header(words: list[_Word], spec: GridSpec) -> Result[_Header, ProviderError]:
    weekday_tops = [w.top for w in words if w.text.strip().lower() in _WEEKDAY_NAMES]
    if not weekday_tops:
        return Err(SchemaMismatch(source=_SOURCE, detail="no weekday header row"))
    weekday_top = min(weekday_tops)

    bahnen_tops = [w.top for w in words if w.text.lower() == "bahnen" and w.top > weekday_top]
    if not bahnen_tops:
        return Err(SchemaMismatch(source=_SOURCE, detail="no 'Bahnen' lane-count row"))
    bahnen_top = min(bahnen_tops)

    lane_count = _lane_count(words, bahnen_top)
    if lane_count is None or lane_count < 1:
        return Err(SchemaMismatch(source=_SOURCE, detail="lane count not determinable"))

    basin_hint = _basin_title(words, spec, weekday_top)
    if not basin_hint:
        return Err(SchemaMismatch(source=_SOURCE, detail="no basin title"))

    return Ok(
        _Header(
            basin_hint=basin_hint,
            lane_count=lane_count,
            valid_from=_header_valid_from(words, spec, weekday_top),
            weekday_top=weekday_top,
            bahnen_top=bahnen_top,
        )
    )


# --- legend -------------------------------------------------------------------------


def _parse_legend(words: list[_Word], spec: GridSpec, weekday_top: float) -> dict[int, str]:
    """code -> owner name, from the right-hand legend rows (blank names omitted)."""
    legend_words = [w for w in words if w.xc > spec.legend_x_min and w.top > weekday_top]
    rows: dict[int, list[_Word]] = defaultdict(list)
    for w in legend_words:
        rows[round(w.top)].append(w)
    legend: dict[int, str] = {}
    for row in rows.values():
        ordered = sorted(row, key=lambda w: w.x0)
        head = ordered[0].text.strip()
        if not head.isdigit():
            continue
        name = " ".join(w.text for w in ordered[1:]).strip()
        if name:
            legend[int(head)] = name
    return legend


def _code_to_access(name: str) -> SessionAccess:
    lowered = name.lower()
    if "öffentlich" in lowered:
        return PublicSwim()
    if "schul" in lowered:
        return SchoolReserved()
    return ClubReserved(club=name)


# --- grid segmentation --------------------------------------------------------------


def _time_labels(words: list[_Word], spec: GridSpec) -> list[TimeRange]:
    # A label ("06.00 - 06.30") is split across several words on one row; group by row first,
    # then match the joined text — no single word carries the whole range.
    label_words = [w for w in words if w.xc < spec.central_x[0]]
    rows: dict[int, list[_Word]] = defaultdict(list)
    for w in label_words:
        rows[round(w.top)].append(w)
    labels: list[TimeRange] = []
    for top in sorted(rows):
        text = " ".join(w.text for w in sorted(rows[top], key=lambda w: w.x0))
        match = _TIME_LABEL_RE.search(text)
        if match is None:
            continue
        # Late rows read "23.30 - 24.00"; 24:00 is not a valid `time`. Those slots are past
        # the swim grid (which ends at 22:00), so an unconstructable label is simply skipped.
        try:
            start = time(int(match.group(1)), int(match.group(2)))
            end = time(int(match.group(3)), int(match.group(4)))
        except ValueError:
            continue
        if start < end:
            labels.append(TimeRange(start=start, end=end))
    return labels


def _cell_words(words: list[_Word], spec: GridSpec, bahnen_top: float) -> list[_Word]:
    lo, hi = spec.central_x
    return [
        w
        for w in words
        if w.text.isdigit() and lo < w.xc < hi and w.top > bahnen_top + spec.bahnen_gap
    ]


@dataclass(frozen=True, slots=True)
class _Grid:
    codes: dict[tuple[Weekday, int, int], int]  # (weekday, lane, row) -> code
    slots: list[TimeRange]  # per row index
    lane_count: int


def _segment_grid(
    words: list[_Word], spec: GridSpec, header: _Header
) -> Result[_Grid, ProviderError]:
    cells = _cell_words(words, spec, header.bahnen_top)
    if not cells:
        return Err(SchemaMismatch(source=_SOURCE, detail="no grid cells"))

    columns = _cluster([w.xc for w in cells], spec.x_tol)
    expected = 7 * header.lane_count
    if len(columns) != expected:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"grid has {len(columns)} columns, expected 7×{header.lane_count}",
            )
        )
    rows = _cluster([w.top for w in cells], spec.y_tol)
    labels = _time_labels(words, spec)
    if len(labels) < len(rows):
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"{len(rows)} slot rows but only {len(labels)} time labels",
            )
        )
    slots = labels[: len(rows)]

    codes: dict[tuple[Weekday, int, int], int] = {}
    for w in cells:
        col = _nearest(w.xc, columns)
        row = _nearest(w.top, rows)
        weekday = Weekday(col // header.lane_count)
        lane = (col % header.lane_count) + 1
        codes[(weekday, lane, row)] = int(w.text)
    return Ok(_Grid(codes=codes, slots=slots, lane_count=header.lane_count))


# --- RLE + coverage -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Resolved:
    reservations: tuple[LaneReservation, ...]
    cells_total: int
    cells_resolved: int
    unresolved_lanes: frozenset[int]


def _column_runs(
    grid: _Grid, legend: dict[int, str], weekday: Weekday, lane: int
) -> tuple[list[tuple[TimeRange, SessionAccess]], int, bool]:
    """Vertical RLE of one (weekday, lane) column: contiguous same-owner runs, the resolved
    cell count, and whether any cell in the column was unresolved."""
    runs: list[tuple[TimeRange, SessionAccess]] = []
    resolved = 0
    unresolved = False
    start_row: int | None = None
    current: SessionAccess | None = None
    n = len(grid.slots)

    def flush(end_row: int) -> None:
        if start_row is not None and current is not None:
            span = TimeRange(grid.slots[start_row].start, grid.slots[end_row].end)
            runs.append((span, current))

    for row in range(n):
        code = grid.codes.get((weekday, lane, row))
        name = legend.get(code) if code is not None else None
        access = _code_to_access(name) if name else None
        if access is None:
            unresolved = unresolved or code is not None
            flush(row - 1)
            start_row, current = None, None
            continue
        resolved += 1
        if current is not None and access == current:
            continue
        flush(row - 1)
        start_row, current = row, access
    flush(n - 1)
    return runs, resolved, unresolved


def _resolve(grid: _Grid, legend: dict[int, str]) -> _Resolved:
    # (time, access) -> lanes, per weekday; then merge equal (time, lanes, access) across days.
    per_day: dict[Weekday, dict[tuple[TimeRange, SessionAccess], set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    resolved_total = 0
    unresolved_lanes: set[int] = set()
    for weekday in Weekday:
        for lane in range(1, grid.lane_count + 1):
            runs, resolved, unresolved = _column_runs(grid, legend, weekday, lane)
            resolved_total += resolved
            if unresolved:
                unresolved_lanes.add(lane)
            for span, access in runs:
                per_day[weekday][(span, access)].add(lane)

    merged: dict[tuple[TimeRange, frozenset[int], SessionAccess], set[Weekday]] = defaultdict(set)
    for weekday, blocks in per_day.items():
        for (span, access), lanes in blocks.items():
            merged[(span, frozenset(lanes), access)].add(weekday)

    reservations = tuple(
        LaneReservation(weekdays=frozenset(weekdays), time=span, lanes=lanes, access=access)
        for (span, lanes, access), weekdays in merged.items()
    )
    cells_total = len(grid.slots) * 7 * grid.lane_count
    return _Resolved(
        reservations=reservations,
        cells_total=cells_total,
        cells_resolved=resolved_total,
        unresolved_lanes=frozenset(unresolved_lanes),
    )


# --- invariants ---------------------------------------------------------------------


def _overlaps(a: TimeRange, b: TimeRange) -> bool:
    return a.start < b.end and b.start < a.end


def _check_invariants(
    reservations: tuple[LaneReservation, ...], lane_count: int
) -> ProviderError | None:
    valid = set(range(1, lane_count + 1))
    for reservation in reservations:
        if not reservation.lanes <= valid:
            bad = sorted(reservation.lanes - valid)
            return ParseError(
                source=_SOURCE,
                detail=f"lanes {bad} outside 1..{lane_count}",
                raw_snippet="",
            )
    for i, a in enumerate(reservations):
        for b in reservations[i + 1 :]:
            if a.weekdays & b.weekdays and _overlaps(a.time, b.time) and a.lanes & b.lanes:
                clash = sorted(a.lanes & b.lanes)
                return ParseError(
                    source=_SOURCE,
                    detail=f"overlapping reservations share lanes {clash}",
                    raw_snippet="",
                )
    return None


# --- top-level parse ----------------------------------------------------------------


def _extract_words(pdf_bytes: bytes) -> Result[list[_Word], ProviderError]:
    try:
        import pdfplumber
    except ImportError:  # optional extra `swimzh[pdf]` not installed
        return Err(
            ProviderSpecific(
                provider=_SOURCE,
                detail="pdfplumber not installed — install the 'pdf' extra to parse Belegungspläne",
            )
        )
    import io

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return Err(ParseError(source=_SOURCE, detail="empty PDF", raw_snippet=""))
            raw = pdf.pages[0].extract_words()
    except Exception as exc:
        return Err(ParseError(source=_SOURCE, detail=f"unreadable PDF: {exc}", raw_snippet=""))
    words = [
        _Word(text=str(w["text"]), x0=float(w["x0"]), x1=float(w["x1"]), top=float(w["top"]))
        for w in raw
    ]
    if not words:
        return Err(ParseError(source=_SOURCE, detail="unreadable PDF: no text", raw_snippet=""))
    return Ok(words)


def parse_belegungsplan(
    pdf_bytes: bytes, spec: GridSpec = _DEFAULT_GRID_SPEC
) -> Result[ParsedPlan, ProviderError]:
    """Parse a Belegungsplan PDF into a `ParsedPlan` (basin hint + `LanePlan`)."""
    words_result = _extract_words(pdf_bytes)
    if isinstance(words_result, Err):
        return words_result
    words = words_result.value

    header_result = _parse_header(words, spec)
    if isinstance(header_result, Err):
        return header_result
    header = header_result.value

    legend = _parse_legend(words, spec, header.weekday_top)
    if not legend:
        return Err(SchemaMismatch(source=_SOURCE, detail="no legend"))

    grid_result = _segment_grid(words, spec, header)
    if isinstance(grid_result, Err):
        return grid_result
    grid = grid_result.value

    resolved = _resolve(grid, legend)
    invariant_error = _check_invariants(resolved.reservations, header.lane_count)
    if invariant_error is not None:
        return Err(invariant_error)

    complete = resolved.cells_resolved == resolved.cells_total and not resolved.unresolved_lanes
    coverage = PlanCoverage(
        confidence=PlanConfidence.COMPLETE if complete else PlanConfidence.PARTIAL,
        cells_total=resolved.cells_total,
        cells_resolved=resolved.cells_resolved,
        unresolved_lanes=resolved.unresolved_lanes,
    )
    plan = LanePlan(
        lane_count=header.lane_count,
        reservations=resolved.reservations,
        valid_from=header.valid_from,
        coverage=coverage,
        fetched_at=None,
    )
    return Ok(ParsedPlan(basin_hint=header.basin_hint, plan=plan))


# --- fetch + scrape -----------------------------------------------------------------


def fetch_plan(client: HttpClient, url: str) -> Result[bytes, ProviderError]:
    """Fetch a Belegungsplan PDF's bytes (transport/status errors as values)."""
    match client.get(url):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return Ok(resp.content)


def scrape_belegungsplan(client: HttpClient, url: str) -> Result[ParsedPlan, ProviderError]:
    match fetch_plan(client, url):
        case Err(error):
            return Err(error)
        case Ok(raw):
            return parse_belegungsplan(raw)
