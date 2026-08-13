"""Parse a per-basin "Belegungsplan" (lane-reservation) PDF into a `LanePlan`.

The PDF is a weekly grid — *7 weekdays × N lanes × 30-min slots* — each cell a legend
code (1 = Öffentlichkeit/public, 2 = Schulen, 3..N = named clubs), with a header carrying
the basin name, the lane count ("6 Bahnen"), and a valid-from date ("ab 01. Januar 2026"),
and a right-hand legend mapping codes to owner names.

`pdfplumber` reconstructs per-word bounding boxes; this module clusters the digit
x-coordinates into lane columns and their y-coordinates into slot rows, pairs each slot row
to its time label by y-geometry (a gutter label the source left cell-free is a blank
half-hour, never a rank shift — see `_pair_rows_to_labels`), maps each cell to an
owner via the legend, RLE-compresses contiguous same-owner regions into `LaneReservation`s,
then runs two invariants (per-slot lane disjointness, lanes ⊆ {1..N}) before returning. A
clean 7×N rectangle takes a uniform fast path; a movable-floor / truncated sheet whose day
columns are ragged is segmented **per weekday** under the detected anchors, so the lane count
may differ by day (`LanePlan.lanes_by_weekday`) — unresolved columns are counted honestly in
coverage (`PlanCoverage.PARTIAL`), never fabricated. Every failure is a typed `ProviderError`
(no new variants):

  * missing `pdfplumber`                         -> `ProviderSpecific`
  * undecodable / no-text PDF                     -> `ParseError` ("unreadable PDF")
  * header/legend missing, no cells, no slot rows -> `SchemaMismatch`
  * disjointness / ⊆ violation                    -> `ParseError`
  * ragged floors / low-but-nonzero coverage      -> `Ok` + `PlanCoverage.PARTIAL`

An unrecognised owner label is **never** treated as public: that lane at that slot is left
unresolved (counted in `PlanCoverage`), preserving the three-way distinction between public
(explicit), unknown (coverage), and absent (not represented).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time

from swimzh.core.errors import ParseError, ProviderError, ProviderSpecific, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import ClubReserved, PublicSwim, SchoolReserved, SessionAccess
from swimzh.domain.lane_plan import LanePlan, LaneReservation, PlanConfidence, PlanCoverage
from swimzh.domain.schedule import TimeRange, Weekday

_SOURCE = "belegungsplan"

# A weekday-anchor gap wider than this multiple of the regular day pitch starts a new stacked
# basin (Oerlikon's Nichtschwimmer-/Sprungbecken sit 1.35× apart vs. the 1.0× intra-grid pitch).
_GROUP_GAP_RATIO = 1.3

_WEEKDAY_NAMES: dict[str, Weekday] = {
    "montag": Weekday.MONDAY,
    "dienstag": Weekday.TUESDAY,
    "mittwoch": Weekday.WEDNESDAY,
    "donnerstag": Weekday.THURSDAY,
    "freitag": Weekday.FRIDAY,
    "samstag": Weekday.SATURDAY,
    "sonntag": Weekday.SUNDAY,
}
_WEEKDAY_ABBR: dict[str, Weekday] = {
    "mo": Weekday.MONDAY,
    "di": Weekday.TUESDAY,
    "mi": Weekday.WEDNESDAY,
    "do": Weekday.THURSDAY,
    "fr": Weekday.FRIDAY,
    "sa": Weekday.SATURDAY,
    "so": Weekday.SUNDAY,
}
# Header rows use either the full ("Montag") or abbreviated ("Mo") weekday spelling; both
# anchor the day-grid columns.
_WEEKDAY_TOKENS: frozenset[str] = frozenset(_WEEKDAY_NAMES) | frozenset(_WEEKDAY_ABBR)

# Fallback page width (A4 landscape, pdfplumber points) for direct/test callers that don't
# supply one; the real parse path always passes the actual `page.width`. This is a page
# dimension, not a grid band — the absolute A4 grid pixels are gone from `GridSpec`.
_DEFAULT_PAGE_WIDTH = 841.92
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
    """Provider-local layout tolerances — page-relative, not absolute A4 pixels.

    The day-grid x band is derived per-PDF from the detected weekday-row anchors (see
    `_grid_band`): the right edge follows the anchors (half a day-column past the last
    weekday), which lands between the final lane and the right-hand legend on every observed
    sheet. Only the left `grid_margin_ratio` fences off the time-label gutter as a page-width
    fraction, so a wider (A3) or differently margined sheet scales instead of relying on
    hard-coded City A4 pixels. There is deliberately no *right* page-fraction clamp: a fixed
    fraction calibrated to City's A4 legend (645px) cut INSIDE the day band of any wider
    A4-landscape sheet, silently dropping its rightmost (Sunday) lane column.
    """

    x_tol: float = 5.0  # cluster digit x-centres into lane columns
    y_tol: float = 6.0  # cluster digit tops into slot rows
    grid_margin_ratio: float = 70.0 / _DEFAULT_PAGE_WIDTH  # left time-label gutter fraction
    lane_merge_ratio: float = 0.5  # merge a sub-pitch column fragment (< this × lane pitch)
    title_gap: float = 8.0  # basin title sits at least this far above the weekday row
    bahnen_gap: float = 5.0  # data cells sit at least this far below the "Bahnen" row
    # Bottom boundary: a cell may sit at most this × label pitch below the LAST left-gutter
    # time label; anything lower is page prose, not a grid cell. Measured on the committed
    # corpus: real cell rows sit at most 0.434×pitch below their own label, while the footer
    # sentence's standalone digit ("… mindestens N Bahnen zur Verfügung.") sits 2.11×pitch
    # (Leimbach) / 2.65×pitch (Oerlikon) below the last label ROW — including the
    # "23.30 - 24.00" row that never becomes a `TimeRange`; measured to the last
    # *constructable* `TimeRange` instead, the same Oerlikon gap is 3.65×pitch — and 1.0
    # separates prose from cells cleanly in either frame.
    label_overhang_ratio: float = 1.0
    # Row→label pairing tolerance: a cell-row cluster claims the time label whose top is
    # nearest, but only within this × label pitch (see `_pair_rows_to_labels`). Corpus-
    # measured: real cell rows sit 0.411–0.434×pitch below their own label, while the next
    # label is ≥0.514×pitch away — the binding case is the two sectioned Oerlikon basins
    # (0.434×pitch offset, next label at 0.514×; the single-basin sheets all sit ≥0.576×).
    # 0.5 admits every real row and keeps the nearest label unambiguous, but with only
    # 0.014×pitch of headroom: do NOT widen this past 0.514. A label no row claims is a
    # blank half-hour (legal); an in-grid row no label admits is garble (`SchemaMismatch`).
    row_label_tol_ratio: float = 0.5


_DEFAULT_GRID_SPEC = GridSpec()  # default layout tolerances; a module singleton for defaults


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
    grid_x_min: float  # left edge of the day-grid band (page-relative, anchor-derived)
    grid_x_max: float  # right edge / start of the legend gutter
    weekday_centres: tuple[float, ...] = ()  # detected weekday-anchor x-centres, ascending


@dataclass(frozen=True, slots=True)
class ParsedPlan:
    """A parsed plan plus the PDF-header basin name and the URL it was fetched from.

    `source_url` is the deterministic reconciliation key (silver joins on it); the parser stays
    URL-agnostic — it emits the default `""` and the fetch loop stamps the real URL. `basin_hint`
    (the PDF header title) is demoted to a stacked-sheet discriminator + audit string, never an
    identity key."""

    basin_hint: str
    plan: LanePlan
    source_url: str = ""


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


def _cluster_counts(values: list[float], tol: float) -> list[tuple[float, int]]:
    """Like `_cluster`, but also carry each cluster's support (member count)."""
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(sum(g) / len(g), len(g)) for g in groups]


def _lane_columns(values: list[float], spec: GridSpec) -> list[float]:
    """Per-weekday lane column centres, robust to a lone sub-pitch fragment. Cluster the cell
    x-centres, then fold any fragment sitting much closer than the lane pitch to its neighbour
    (a stray digit, e.g. Leimbach's single misplaced cell) into that neighbour, weighted by
    support — so a real 5-lane day is not mis-read as 6."""
    columns = _cluster_counts(values, spec.x_tol)
    if len(columns) < 3:
        return [c for c, _ in columns]
    gaps = sorted(columns[i + 1][0] - columns[i][0] for i in range(len(columns) - 1))
    pitch = gaps[len(gaps) // 2]  # median gap ≈ the regular lane pitch
    merged: list[tuple[float, int]] = [columns[0]]
    for centre, n in columns[1:]:
        prev_centre, prev_n = merged[-1]
        if centre - prev_centre < spec.lane_merge_ratio * pitch:
            total = prev_n + n
            merged[-1] = ((prev_centre * prev_n + centre * n) / total, total)
        else:
            merged.append((centre, n))
    return [c for c, _ in merged]


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


def _basin_title(
    words: list[_Word], grid_x_min: float, grid_x_max: float, spec: GridSpec, weekday_top: float
) -> str:
    """The title line ("Hallenbad City Schwimmerbecken"), the text row immediately above the
    weekday row within the day-grid x-span. Picking the row *closest above* — rather than a
    fixed pixel window — is page-relative: it adapts to A4-vs-A2 line spacing (City's title
    sits 22 px above the weekday row, Oerlikon's taller A2 sheet 31 px) while still skipping
    the higher "Übersicht Dauerbelegungen" strap-line, so City-family basin hints stay
    byte-identical and the wider Oerlikon sheet's title is read."""
    above = [
        w
        for w in words
        if w.top < weekday_top - spec.title_gap and grid_x_min <= w.xc <= grid_x_max
    ]
    if not above:
        return ""
    target = max(_cluster([w.top for w in above], spec.y_tol))  # the row closest to the weekdays
    row = [w for w in above if abs(w.top - target) <= spec.y_tol]
    return _row_text(row)


def _header_valid_from(words: list[_Word], grid_x_max: float, weekday_top: float) -> date | None:
    """The "ab 01. Januar 2026" line — right of the grid, above the weekday row (clear of
    the legend, which begins lower down)."""
    right = [w for w in words if w.xc > grid_x_max and w.top < weekday_top]
    return _parse_valid_from(_row_text(right))


def _weekday_row(words: list[_Word]) -> list[_Word] | None:
    """The header's weekday cells (full or abbreviated names). Robust to stray weekday-like
    words elsewhere: pick the densest same-top row, tie-broken by the topmost."""
    rows: dict[int, list[_Word]] = defaultdict(list)
    for w in words:
        if w.text.strip().lower() in _WEEKDAY_TOKENS:
            rows[round(w.top)].append(w)
    if not rows:
        return None
    return max(rows.values(), key=lambda r: (len(r), -min(w.top for w in r)))


def _grid_band(anchors: list[_Word], spec: GridSpec, page_width: float) -> tuple[float, float]:
    """Derive the day-grid x band from the weekday anchors + page width. The band spans the
    weekday-row centres extended by half a day-column each side. The left edge is additionally
    clamped to the page's time-label gutter; the right edge is left purely anchor-derived —
    half a day past the last weekday centre lands between the final lane and the legend on
    every observed sheet, whereas a fixed page-fraction clamp (calibrated to City's A4 legend)
    would cut inside a wider sheet's band and drop its rightmost lane."""
    centres = sorted(w.xc for w in anchors)
    span = centres[-1] - centres[0]
    half_day = span / (2 * (len(centres) - 1)) if len(centres) > 1 else 0.0
    lo = max(centres[0] - half_day, page_width * spec.grid_margin_ratio)
    hi = centres[-1] + half_day
    return lo, hi


def _parse_header(
    words: list[_Word], spec: GridSpec, page_width: float = _DEFAULT_PAGE_WIDTH
) -> Result[_Header, ProviderError]:
    anchors = _weekday_row(words)
    if not anchors:
        return Err(SchemaMismatch(source=_SOURCE, detail="no weekday header row"))
    weekday_top = min(w.top for w in anchors)
    weekday_centres = tuple(sorted(w.xc for w in anchors))
    grid_x_min, grid_x_max = _grid_band(anchors, spec, page_width)

    bahnen_tops = [w.top for w in words if w.text.lower() == "bahnen" and w.top > weekday_top]
    if not bahnen_tops:
        return Err(SchemaMismatch(source=_SOURCE, detail="no 'Bahnen' lane-count row"))
    bahnen_top = min(bahnen_tops)

    lane_count = _lane_count(words, bahnen_top)
    if lane_count is None or lane_count < 1:
        return Err(SchemaMismatch(source=_SOURCE, detail="lane count not determinable"))

    basin_hint = _basin_title(words, grid_x_min, grid_x_max, spec, weekday_top)
    if not basin_hint:
        return Err(SchemaMismatch(source=_SOURCE, detail="no basin title"))

    return Ok(
        _Header(
            basin_hint=basin_hint,
            lane_count=lane_count,
            valid_from=_header_valid_from(words, grid_x_max, weekday_top),
            weekday_top=weekday_top,
            bahnen_top=bahnen_top,
            grid_x_min=grid_x_min,
            grid_x_max=grid_x_max,
            weekday_centres=weekday_centres,
        )
    )


# --- legend -------------------------------------------------------------------------


def _parse_legend(words: list[_Word], grid_x_max: float, weekday_top: float) -> dict[int, str]:
    """code -> owner name, from the right-hand legend rows (blank names omitted)."""
    legend_words = [w for w in words if w.xc > grid_x_max and w.top > weekday_top]
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
    # "schul" routes to SchoolReserved — the committed legends are full of genuine
    # compound-named schools (Kantonsschule, Tagesschule, Rafaelschule, Privatschule,
    # Gesamtschule, Schulsportkurs). The ONE exception is targeted, not word-boundary:
    # a name whose "schul" hit comes only from the word "Schwimmschule" is a swim CLUB
    # (Oerlikon's "Schwimmschule Limmatsharks") and keeps its full name — the same
    # posture as the "bare 'bad' is not a pool keyword" negative.
    if "schul" in lowered.replace("schwimmschule", ""):
        return SchoolReserved()
    return ClubReserved(club=name)


# --- grid segmentation --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _TimeLabel:
    """A left-gutter time label with its page y-top — the geometry rows pair against."""

    top: float
    time: TimeRange


def _time_labels(words: list[_Word], grid_x_min: float) -> list[_TimeLabel]:
    # A label ("06.00 - 06.30") is split across several words on one row; group by row first,
    # then match the joined text — no single word carries the whole range.
    label_words = [w for w in words if w.xc < grid_x_min]
    rows: dict[int, list[_Word]] = defaultdict(list)
    for w in label_words:
        rows[round(w.top)].append(w)
    labels: list[_TimeLabel] = []
    for top in sorted(rows):
        group = sorted(rows[top], key=lambda w: w.x0)
        text = " ".join(w.text for w in group)
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
            labels.append(_TimeLabel(top=min(w.top for w in group), time=TimeRange(start, end)))
    return labels


def _pair_rows_to_labels(
    rows: Sequence[float], labels: Sequence[_TimeLabel], spec: GridSpec
) -> Result[tuple[TimeRange, ...], ProviderError]:
    """Pair each cell-row cluster to the time label it geometrically sits under.

    Rank pairing (`labels[: len(rows)]`) silently shifts every row after a *blank* gutter
    slot — a label the source printed but left cell-free (Bläsi's 07:30–08:00, Käferberg's
    06:00–06:30) — serving whole sheets 30 minutes early. Geometry pairing instead lets each
    row claim its NEAREST label within `row_label_tol_ratio` × pitch: a label no row claims
    is a legal blank half-hour, while an in-grid row no label admits (or two rows claiming
    the same label) is garble → `SchemaMismatch`. Correct sheets, where every row's nearest
    label is the rank-assigned one anyway, pair byte-identically."""
    if not labels:
        return Err(SchemaMismatch(source=_SOURCE, detail="no time labels"))
    if len(labels) < 2:
        # A single label yields no pitch to derive the tolerance from; only rank can pair.
        if len(rows) > len(labels):
            return Err(
                SchemaMismatch(
                    source=_SOURCE,
                    detail=f"{len(rows)} slot rows but only {len(labels)} time labels",
                )
            )
        return Ok(tuple(label.time for label in labels[: len(rows)]))
    tops = [label.top for label in labels]
    pitch = (tops[-1] - tops[0]) / (len(tops) - 1)
    tolerance = pitch * spec.row_label_tol_ratio
    paired: list[TimeRange] = []
    claimed: set[int] = set()
    for row in rows:
        index = _nearest(row, tops)
        label = labels[index]
        if abs(tops[index] - row) > tolerance:
            return Err(
                SchemaMismatch(
                    source=_SOURCE,
                    detail=(
                        f"cell row at y={row:.1f} matches no time label within "
                        f"{spec.row_label_tol_ratio}×pitch (nearest is "
                        f"{abs(tops[index] - row) / pitch:.2f}×pitch away)"
                    ),
                )
            )
        if index in claimed:
            return Err(
                SchemaMismatch(
                    source=_SOURCE,
                    detail=(
                        f"two cell rows claim the {label.time.start}-{label.time.end} "
                        f"time label (second at y={row:.1f})"
                    ),
                )
            )
        claimed.add(index)
        paired.append(label.time)
    return Ok(tuple(paired))


def _label_row_tops(words: list[_Word], grid_x_min: float) -> list[float]:
    """The y-tops of the left-gutter time-label rows, ascending. Matched by the time-range
    regex alone: a "23.30 - 24.00" row that never becomes a `TimeRange` still counts here,
    because these tops bound the data grid geometrically."""
    rows: dict[int, list[_Word]] = defaultdict(list)
    for w in words:
        if w.xc < grid_x_min:
            rows[round(w.top)].append(w)
    tops = [
        min(g.top for g in group)
        for group in rows.values()
        if _TIME_LABEL_RE.search(" ".join(g.text for g in sorted(group, key=lambda g: g.x0)))
    ]
    return sorted(tops)


def _grid_bottom(words: list[_Word], grid_x_min: float, spec: GridSpec) -> float:
    """The y below which a digit is page prose, not a grid cell: last time-label top plus
    `label_overhang_ratio` × the label pitch. The footer sentence's standalone digit ("Den
    Badegästen stehen … mindestens N Bahnen zur Verfügung.") sits well below the label span
    and must never mint a phantom slot row. With fewer than two label rows there is no pitch
    to derive — the boundary stays open (`inf`) and the label-count checks catch garble."""
    tops = _label_row_tops(words, grid_x_min)
    if len(tops) < 2:
        return math.inf
    pitch = (tops[-1] - tops[0]) / (len(tops) - 1)
    return tops[-1] + pitch * spec.label_overhang_ratio


def _cell_words(
    words: list[_Word], grid_x_min: float, grid_x_max: float, spec: GridSpec, bahnen_top: float
) -> list[_Word]:
    bottom = _grid_bottom(words, grid_x_min, spec)
    return [
        w
        for w in words
        if w.text.isdigit()
        and grid_x_min < w.xc < grid_x_max
        and bahnen_top + spec.bahnen_gap < w.top < bottom
    ]


@dataclass(frozen=True, slots=True)
class _Grid:
    codes: dict[tuple[Weekday, int, int], int]  # (weekday, lane, row) -> code
    slots: list[TimeRange]  # per row index
    lane_count: int  # uniform / nominal lane count (the RLE + invariant ceiling)
    # Per-weekday lane counts for a ragged (movable-floor) grid; `None` when every weekday
    # shares `lane_count`. A weekday absent from a non-`None` map falls back to `lane_count`.
    lanes_by_weekday: Mapping[Weekday, int] | None = None


def _weekday_bounds(header: _Header) -> list[float]:
    """The per-weekday x cut lines: the grid's left edge, the midpoints between adjacent
    weekday anchors, and the grid's right edge — so each weekday owns exactly the band around
    its own anchor."""
    centres = header.weekday_centres
    mids = [(centres[i] + centres[i + 1]) / 2 for i in range(len(centres) - 1)]
    return [header.grid_x_min, *mids, header.grid_x_max]


def _uniform_grid(
    cells: list[_Word],
    columns: list[float],
    slots: list[TimeRange],
    spec: GridSpec,
    header: _Header,
) -> _Grid:
    """The clean `7×lane_count` rectangle: global column clustering divided evenly across the
    seven days. This is the pre-E2 path, kept byte-for-byte so a basin whose grid is already a
    clean rectangle (City COMPLETE, Käferberg PARTIAL) is unchanged."""
    rows = _cluster([w.top for w in cells], spec.y_tol)[: len(slots)]
    codes: dict[tuple[Weekday, int, int], int] = {}
    for w in cells:
        col = _nearest(w.xc, columns)
        row = _nearest(w.top, rows)
        weekday = Weekday(col // header.lane_count)
        lane = (col % header.lane_count) + 1
        codes[(weekday, lane, row)] = int(w.text)
    return _Grid(codes=codes, slots=slots, lane_count=header.lane_count)


def _ragged_grid(
    cells: list[_Word], slots: list[TimeRange], spec: GridSpec, header: _Header
) -> _Grid:
    """A movable-floor / truncated grid whose day columns don't form a clean `7×lane_count`
    rectangle: segment the cells per weekday under the detected anchors and cluster each day's
    lanes independently, so the lane count may differ by weekday. Unfilled columns simply
    aren't represented (their cells stay unresolved, counted honestly in coverage — never
    fabricated as public). When the counts genuinely differ across days, `lanes_by_weekday`
    records the ragged shape (storing all seven days); when every day agrees it stays `None`
    and the grid is uniform after all."""
    rows = _cluster([w.top for w in cells], spec.y_tol)[: len(slots)]
    bounds = _weekday_bounds(header)
    per_day_cols: dict[Weekday, list[float]] = {}
    for i, weekday in enumerate(Weekday):
        lo, hi = bounds[i], bounds[i + 1]
        day_cells = [w for w in cells if lo <= w.xc < hi]
        per_day_cols[weekday] = _lane_columns([w.xc for w in day_cells], spec) if day_cells else []

    counts = {wd: len(cols) for wd, cols in per_day_cols.items()}
    lane_count = max(header.lane_count, max(counts.values()))
    ragged = len(set(counts.values())) > 1

    codes: dict[tuple[Weekday, int, int], int] = {}
    for i, weekday in enumerate(Weekday):
        cols = per_day_cols[weekday]
        if not cols:
            continue
        lo, hi = bounds[i], bounds[i + 1]
        for w in cells:
            if lo <= w.xc < hi:
                lane = _nearest(w.xc, cols) + 1
                row = _nearest(w.top, rows)
                codes[(weekday, lane, row)] = int(w.text)
    return _Grid(
        codes=codes,
        slots=slots,
        lane_count=lane_count,
        lanes_by_weekday=dict(counts) if ragged else None,
    )


def _segment_grid(
    words: list[_Word], spec: GridSpec, header: _Header
) -> Result[_Grid, ProviderError]:
    cells = _cell_words(words, header.grid_x_min, header.grid_x_max, spec, header.bahnen_top)
    if not cells:
        return Err(SchemaMismatch(source=_SOURCE, detail="no grid cells"))

    rows = _cluster([w.top for w in cells], spec.y_tol)
    labels = _time_labels(words, header.grid_x_min)
    slots_result = _pair_rows_to_labels(rows, labels, spec)
    if isinstance(slots_result, Err):
        return slots_result
    slots = list(slots_result.value)

    columns = _cluster([w.xc for w in cells], spec.x_tol)
    if len(columns) == 7 * header.lane_count:
        return Ok(_uniform_grid(cells, columns, slots, spec, header))
    # A ragged / truncated grid (movable floor, clipped edge column) no longer aborts as a
    # `SchemaMismatch`: segment it per weekday and let unresolved cells surface as PARTIAL.
    return Ok(_ragged_grid(cells, slots, spec, header))


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
        # A run may only extend across CONTIGUOUS slots: geometry pairing leaves a blank
        # gutter label out of `slots`, so adjacent row indices can be half an hour apart —
        # a same-owner block on both sides of the blank must stay two reservations, never
        # a claim over the half-hour the source left empty.
        if (
            current is not None
            and access == current
            and grid.slots[row].start == grid.slots[row - 1].end
        ):
            continue
        flush(row - 1)
        start_row, current = row, access
    flush(n - 1)
    return runs, resolved, unresolved


def _lanes_on(grid: _Grid, weekday: Weekday) -> int:
    """The lane count in force on `weekday`: the per-weekday override for a ragged grid,
    else the uniform `lane_count`."""
    if grid.lanes_by_weekday is None:
        return grid.lane_count
    return grid.lanes_by_weekday.get(weekday, grid.lane_count)


def _resolve(
    grid: _Grid, legend: dict[int, str], lane_sections: Mapping[int, str] | None = None
) -> _Resolved:
    # (time, access, section) -> lanes, per weekday; then merge equal keys across days. When
    # `lane_sections` is None every section is None, so the grouping — and every emitted
    # reservation — is byte-identical to the pre-section path. When a sectioned sheet maps a
    # lane to a "Teil" label, that label enters the key so reservations in different sections
    # never merge and each carries D's `section`.
    def _section_of(lane: int) -> str | None:
        return lane_sections.get(lane) if lane_sections is not None else None

    per_day: dict[Weekday, dict[tuple[TimeRange, SessionAccess, str | None], set[int]]] = (
        defaultdict(lambda: defaultdict(set))
    )
    resolved_total = 0
    unresolved_lanes: set[int] = set()
    for weekday in Weekday:
        for lane in range(1, _lanes_on(grid, weekday) + 1):
            runs, resolved, unresolved = _column_runs(grid, legend, weekday, lane)
            resolved_total += resolved
            if unresolved:
                unresolved_lanes.add(lane)
            for span, access in runs:
                per_day[weekday][(span, access, _section_of(lane))].add(lane)

    merged: dict[tuple[TimeRange, frozenset[int], SessionAccess, str | None], set[Weekday]] = (
        defaultdict(set)
    )
    for weekday, blocks in per_day.items():
        for (span, access, section), lanes in blocks.items():
            merged[(span, frozenset(lanes), access, section)].add(weekday)

    reservations = tuple(
        LaneReservation(
            weekdays=frozenset(weekdays), time=span, lanes=lanes, access=access, section=section
        )
        for (span, lanes, access, section), weekdays in merged.items()
    )
    # Count cells honestly: a ragged grid contributes each weekday's own lane count, so a
    # movable-floor day with fewer lanes never inflates the denominator.
    cells_total = len(grid.slots) * sum(_lanes_on(grid, wd) for wd in Weekday)
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


def _extract_words(pdf_bytes: bytes) -> Result[tuple[list[_Word], float], ProviderError]:
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
            page = pdf.pages[0]
            raw = page.extract_words()
            page_width = float(page.width)
    except Exception as exc:
        return Err(ParseError(source=_SOURCE, detail=f"unreadable PDF: {exc}", raw_snippet=""))
    words = [
        _Word(text=str(w["text"]), x0=float(w["x0"]), x1=float(w["x1"]), top=float(w["top"]))
        for w in raw
    ]
    if not words:
        return Err(ParseError(source=_SOURCE, detail="unreadable PDF: no text", raw_snippet=""))
    return Ok((words, page_width))


def _plan_from_resolved(
    resolved: _Resolved,
    lane_count: int,
    valid_from: date | None,
    lanes_by_weekday: Mapping[Weekday, int] | None,
) -> LanePlan:
    """Assemble a `LanePlan` + its honest coverage from a resolved grid (shared by the single-
    basin and per-section paths)."""
    complete = resolved.cells_resolved == resolved.cells_total and not resolved.unresolved_lanes
    coverage = PlanCoverage(
        confidence=PlanConfidence.COMPLETE if complete else PlanConfidence.PARTIAL,
        cells_total=resolved.cells_total,
        cells_resolved=resolved.cells_resolved,
        unresolved_lanes=resolved.unresolved_lanes,
    )
    return LanePlan(
        lane_count=lane_count,
        reservations=resolved.reservations,
        valid_from=valid_from,
        coverage=coverage,
        fetched_at=None,
        lanes_by_weekday=lanes_by_weekday,
    )


def _parse_single_basin(
    words: list[_Word], spec: GridSpec, page_width: float
) -> Result[ParsedPlan, ProviderError]:
    header_result = _parse_header(words, spec, page_width)
    if isinstance(header_result, Err):
        return header_result
    header = header_result.value

    legend = _parse_legend(words, header.grid_x_max, header.weekday_top)
    if not legend:
        return Err(SchemaMismatch(source=_SOURCE, detail="no legend"))

    grid_result = _segment_grid(words, spec, header)
    if isinstance(grid_result, Err):
        return grid_result
    grid = grid_result.value

    resolved = _resolve(grid, legend)
    invariant_error = _check_invariants(resolved.reservations, grid.lane_count)
    if invariant_error is not None:
        return Err(invariant_error)

    plan = _plan_from_resolved(resolved, grid.lane_count, header.valid_from, grid.lanes_by_weekday)
    return Ok(ParsedPlan(basin_hint=header.basin_hint, plan=plan))


def parse_belegungsplan(
    pdf_bytes: bytes, spec: GridSpec = _DEFAULT_GRID_SPEC
) -> Result[ParsedPlan, ProviderError]:
    """Parse a single-basin Belegungsplan PDF into a `ParsedPlan` (basin hint + `LanePlan`)."""
    words_result = _extract_words(pdf_bytes)
    if isinstance(words_result, Err):
        return words_result
    words, page_width = words_result.value
    return _parse_single_basin(words, spec, page_width)


# --- multi-basin / named-section (Teil) sheets --------------------------------------


def _weekday_groups(anchors: list[_Word]) -> list[list[_Word]]:
    """Split the detected weekday cells into one group per stacked basin. A sheet that lays
    several basins side by side repeats the weekday row (e.g. Oerlikon's Nichtschwimmer- and
    Sprungbecken: 14 anchors = 2×7); the basins are separated by an inter-basin x-gap markedly
    wider than the regular day pitch, so a gap above `_GROUP_GAP_RATIO × median` starts a new
    group. A normal single-basin sheet has one uniform pitch and yields a single group."""
    ordered = sorted(anchors, key=lambda w: w.xc)
    if len(ordered) < 2:
        return [ordered]
    gaps = [ordered[i + 1].xc - ordered[i].xc for i in range(len(ordered) - 1)]
    median = sorted(gaps)[len(gaps) // 2]
    groups: list[list[_Word]] = [[ordered[0]]]
    for i in range(1, len(ordered)):
        if gaps[i - 1] > _GROUP_GAP_RATIO * median:
            groups.append([])
        groups[-1].append(ordered[i])
    return groups


def _first_data_top(words: list[_Word], grid_x_min: float) -> float:
    """The top of the first time-labelled slot row — the vertical start of the data grid. Cells
    align to the left-gutter time labels, so anchoring on the earliest label top excludes the
    section-header rows ("Teil", "1 2") that sit above it."""
    tops = _label_row_tops(words, grid_x_min)
    return tops[0] if tops else 0.0


def _has_section_labels(
    words: list[_Word], grid_x_min: float, grid_x_max: float, weekday_top: float, data_top: float
) -> bool:
    """Whether this basin's columns are named "Teil …" sections (between the weekday row and the
    first data row, within the basin's x-span)."""
    return any(
        w.text.strip().lower() == "teil"
        and grid_x_min <= w.xc <= grid_x_max
        and weekday_top < w.top < data_top
        for w in words
    )


def _parse_sectioned_basin(
    words: list[_Word],
    group: list[_Word],
    legend: dict[int, str],
    valid_from: date | None,
    labels: list[_TimeLabel],
    data_top: float,
    data_bottom: float,
    spec: GridSpec,
    page_width: float,
) -> Result[ParsedPlan, ProviderError]:
    """Parse one stacked basin: a clean `7 × sections` grid under its own weekday anchors. The
    lane count is the number of section columns per weekday (2 for "Teil 1 / Teil 2"), read from
    the geometry — this sheet family carries no "N Bahnen" header. Where the columns are named
    "Teil", each lane maps to that section label (D's `section`); otherwise sections stay `None`
    (stacked basins that simply aren't sub-divided)."""
    grid_x_min, grid_x_max = _grid_band(group, spec, page_width)
    weekday_top = min(w.top for w in group)
    cells = [
        w
        for w in words
        if w.text.isdigit()
        and grid_x_min < w.xc < grid_x_max
        and data_top - spec.y_tol <= w.top < data_bottom
    ]
    if not cells:
        return Err(SchemaMismatch(source=_SOURCE, detail="no grid cells"))
    columns = _cluster([w.xc for w in cells], spec.x_tol)
    weekdays = len(group)
    if weekdays == 0 or len(columns) % weekdays != 0:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"{len(columns)} section columns not a multiple of {weekdays} weekdays",
            )
        )
    sections = len(columns) // weekdays
    if sections < 1:
        return Err(SchemaMismatch(source=_SOURCE, detail="no section columns"))

    rows = _cluster([w.top for w in cells], spec.y_tol)
    slots_result = _pair_rows_to_labels(rows, labels, spec)
    if isinstance(slots_result, Err):
        return slots_result
    used_slots = list(slots_result.value)

    basin_hint = _basin_title(words, grid_x_min, grid_x_max, spec, weekday_top)
    if not basin_hint:
        return Err(SchemaMismatch(source=_SOURCE, detail="no basin title"))

    header = _Header(
        basin_hint=basin_hint,
        lane_count=sections,
        valid_from=valid_from,
        weekday_top=weekday_top,
        bahnen_top=data_top,
        grid_x_min=grid_x_min,
        grid_x_max=grid_x_max,
        weekday_centres=tuple(sorted(w.xc for w in group)),
    )
    grid = _uniform_grid(cells, columns, used_slots, spec, header)
    named = _has_section_labels(words, grid_x_min, grid_x_max, weekday_top, data_top)
    lane_sections = {lane: f"Teil {lane}" for lane in range(1, sections + 1)} if named else None
    resolved = _resolve(grid, legend, lane_sections)
    invariant_error = _check_invariants(resolved.reservations, grid.lane_count)
    if invariant_error is not None:
        return Err(invariant_error)

    plan = _plan_from_resolved(resolved, grid.lane_count, valid_from, None)
    return Ok(ParsedPlan(basin_hint=basin_hint, plan=plan))


def parse_belegungsplan_sheet(
    pdf_bytes: bytes, spec: GridSpec = _DEFAULT_GRID_SPEC
) -> Result[tuple[ParsedPlan, ...], ProviderError]:
    """Parse a Belegungsplan sheet into one `ParsedPlan` per basin.

    A single-basin sheet (City family, Oerlikon-Schwimmerbecken) returns a 1-tuple identical to
    `parse_belegungsplan`, so existing output is byte-for-byte unchanged. A sheet that stacks
    several basins side by side (Oerlikon's Nichtschwimmer-/Sprungbecken) is segmented per basin
    under the repeated weekday row; columns named "Teil 1 / Teil 2" record D's `section`. The
    stacked grids share one right-hand legend, one valid-from date, and one left time-label
    column. Best-effort: a basin sub-grid that can't be segmented is dropped, and only an empty
    result surfaces the (typed) error — never fabricating a shape."""
    words_result = _extract_words(pdf_bytes)
    if isinstance(words_result, Err):
        return words_result
    words, page_width = words_result.value

    anchors = _weekday_row(words)
    groups = _weekday_groups(anchors) if anchors else []
    if len(groups) < 2:
        single = _parse_single_basin(words, spec, page_width)
        if isinstance(single, Err):
            return single
        return Ok((single.value,))

    weekday_top = min(w.top for w in anchors) if anchors else 0.0
    grid_x_max = max(_grid_band(g, spec, page_width)[1] for g in groups)
    legend = _parse_legend(words, grid_x_max, weekday_top)
    if not legend:
        return Err(SchemaMismatch(source=_SOURCE, detail="no legend"))
    valid_from = _header_valid_from(words, grid_x_max, weekday_top)
    left_edge = min(_grid_band(g, spec, page_width)[0] for g in groups)
    labels = _time_labels(words, left_edge)
    if not labels:
        return Err(SchemaMismatch(source=_SOURCE, detail="no time labels"))
    data_top = _first_data_top(words, left_edge)
    data_bottom = _grid_bottom(words, left_edge, spec)

    plans: list[ParsedPlan] = []
    first_error: ProviderError | None = None
    for group in groups:
        result = _parse_sectioned_basin(
            words, group, legend, valid_from, labels, data_top, data_bottom, spec, page_width
        )
        if isinstance(result, Ok):
            plans.append(result.value)
        elif first_error is None:
            first_error = result.error
    if not plans:
        return Err(first_error or SchemaMismatch(source=_SOURCE, detail="no basins parsed"))
    return Ok(tuple(plans))


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


def scrape_belegungsplan_sheet(
    client: HttpClient, url: str
) -> Result[tuple[ParsedPlan, ...], ProviderError]:
    """Fetch + parse a sheet that may stack several basins into one `ParsedPlan` per basin."""
    match fetch_plan(client, url):
        case Err(error):
            return Err(error)
        case Ok(raw):
            return parse_belegungsplan_sheet(raw)
