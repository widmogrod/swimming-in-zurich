"""The iOS export: a projection of the gold store in which every date is ALREADY RESOLVED.

`gold.sqlite` stores schedule *rules*; turning them into "what is open on 4 September" is the
job of `domain/resolver.py` + `domain/query.py` — 2,000 lines of correctness core the iOS app
cannot run. Rather than port that core to Swift and maintain two copies of it, the build gains
one more derived artifact ([[ios-resolved-export]]): a small SQLite store carrying the *answers*
for every date in a fixed forward horizon, so the client is left with only what genuinely
depends on the user — eligibility (gender/age), the price bracket (age), distance (lat/lon) —
plus the clock.

**Invariant E1 — no date-dependent RULE runs on the client.** Weekday scope, school-term scope,
seasons, holiday policy, exceptions and closures are all resolved here, in Python. Comparing the
wall clock against a *baked* time window is not a date rule and stays in Swift.

**Invariant E2 — the horizon matches the web's honesty, not a stricter one.** `find_swim_options`
does not withhold answers outside `ZurichCalendar.covers()`; it appends a warning and serves. So
the export bakes a fixed 400-day horizon regardless of calendar coverage and carries the identical
coverage warning on every out-of-coverage date. `ExportReport.uncovered_days` counts them, so the
"seed the next year" signal is visible at every build.

The export takes the **connection**, not a `GoldRepository`: the repo exposes only the schedule
blobs, while the export also needs `load_calendar`, `load_roster` and `load_alias_rows` — without
the roster every schedule-less pool's status row would be missing. It is network-free (it reads
gold and nothing else) and, like every other store this project emits, is written through
`storage/atomic.py`.

**The file must be readable from an iOS app bundle**, which is where a plausible-looking export
would have shipped broken: a WAL-mode database in a read-only directory *opens* fine and fails on
the first `sqlite3_prepare` with `SQLITE_CANTOPEN`, because WAL needs its `-wal`/`-shm` sidecars
and a writable directory. So the export finishes with a fixed, asserted sequence — DELETE journal,
`VACUUM`, `ANALYZE` (so the device's first query has real `sqlite_stat1` statistics), an
`integrity_check`, sidecar removal, and a header-byte assertion. The byte check is not
belt-and-braces: `PRAGMA journal_mode` can fail *silently* and return the previous mode, so its
own return value is not evidence. Header bytes 18-19 read `0101` for `delete`/`truncate`/`memory`/
`off` and `0202` only for `wal`, so the assertion proves the property that matters — **not WAL**.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, assert_never
from zoneinfo import ZoneInfo

from swimzh.core.errors import ProviderError, ProviderSpecific, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import PublicSwim, SessionAccess
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.lane_plan import (
    LanePlan,
    LaneStrip,
    lane_day_view,
    owner_label,
)
from swimzh.domain.models import Basin, Facility, Feature, OperatingSeason
from swimzh.domain.person import Person
from swimzh.domain.pricing import PriceTable
from swimzh.domain.query import FacilityStatus, QueryResult, SwimQuery, find_swim_options
from swimzh.domain.rentals import Gratis, Priced, RentalFee, Unstated
from swimzh.domain.resolver import resolve_basin, resolve_hours
from swimzh.domain.schedule import (
    ClosedDay,
    DatePrecision,
    OpenDay,
    OpenUnscheduledDay,
    Weekday,
)
from swimzh.storage.atomic import atomic_swap
from swimzh.storage.sqlite_repo import GoldRepository, load_alias_rows, load_calendar, load_roster

_ZURICH = ZoneInfo("Europe/Zurich")

#: Bumped whenever a client would read the store wrongly. The iOS refresh path rejects a
#: downloaded store whose `schema_version` is not the one the installed app was built against.
SCHEMA_VERSION: Final = 1

#: The horizon length. 400 days ≈ 13 months, so a weekly release always answers "a year from now".
DEFAULT_DAYS: Final = 400

#: The neutral hour every horizon date is resolved at. Nothing in the BAKED half depends on it:
#: `open_at_query_time` and the lane derivations are the client's job (E1), so this only has to
#: be a valid time of day.
_RESOLVE_AT: Final = time(12, 0)

#: `FacilityStatus`'s domain field names vs the client-facing `StatusOut` names the export's
#: columns keep. One fixed mapping, applied in one place, so the parity test can assert THROUGH it.
STATUS_FIELD_TO_COLUMN: Final[Mapping[str, str]] = {
    "code": "detail_code",
    "closure": "closure_code",
    "params": "detail_params",
}

#: Warning codes. The export stores the CODE + its params; the client renders it in its own
#: language. `render_warning` reproduces `find_swim_options`'s English rendering byte for byte,
#: which is how the parity test proves the decomposition loses nothing.
WARNING_CALENDAR_COVERAGE: Final = "calendar_coverage"
WARNING_HOLIDAY_HOURS_UNVERIFIED: Final = "holiday_hours_unverified"

_SCHEMA: Final = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;
CREATE TABLE pool (
    pool_id                  TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    kind                     TEXT NOT NULL,
    address                  TEXT,
    lat                      REAL,
    lon                      REAL,
    url                      TEXT,
    description              TEXT,
    phone                    TEXT,
    freshness                TEXT NOT NULL,
    admission_state          TEXT NOT NULL,
    prices_doc               TEXT,
    source                   TEXT,
    curated                  INTEGER,
    valid_as_of              TEXT,
    last_admission_before_s  INTEGER,
    operating_season         TEXT
) STRICT;
CREATE TABLE pool_basin (
    pool_id            TEXT NOT NULL REFERENCES pool(pool_id),
    basin_id           TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    kind               TEXT NOT NULL,
    length_m           REAL,
    width_m            REAL,
    lanes              INTEGER,
    nominal_temp_c     REAL,
    measured_temp_c    REAL,
    diving_platforms_m TEXT NOT NULL,
    physical_source    TEXT NOT NULL,
    lane_plan_url      TEXT
) STRICT;
CREATE TABLE pool_locker (
    pool_id TEXT NOT NULL REFERENCES pool(pool_id),
    ord     INTEGER NOT NULL,
    doc     TEXT NOT NULL,
    PRIMARY KEY (pool_id, ord)
) STRICT;
CREATE TABLE pool_rental (
    pool_id TEXT NOT NULL REFERENCES pool(pool_id),
    ord     INTEGER NOT NULL,
    doc     TEXT NOT NULL,
    PRIMARY KEY (pool_id, ord)
) STRICT;
CREATE TABLE pool_feature (
    pool_id     TEXT NOT NULL REFERENCES pool(pool_id),
    feature_key TEXT NOT NULL,
    doc         TEXT NOT NULL,
    PRIMARY KEY (pool_id, feature_key)
) STRICT;
CREATE TABLE day (
    pool_id       TEXT NOT NULL REFERENCES pool(pool_id),
    date          TEXT NOT NULL,
    status        TEXT NOT NULL,
    detail_code   TEXT NOT NULL,
    closure_code  TEXT,
    detail_params TEXT NOT NULL,
    PRIMARY KEY (pool_id, date)
) STRICT;
CREATE TABLE session (
    pool_id       TEXT NOT NULL REFERENCES pool(pool_id),
    date          TEXT NOT NULL,
    basin_id      TEXT NOT NULL,
    basin_name    TEXT NOT NULL,
    length_m      REAL,
    lanes         INTEGER,
    start         TEXT NOT NULL,
    end           TEXT NOT NULL,
    access_kind   TEXT NOT NULL,
    access_params TEXT NOT NULL,
    weather       TEXT NOT NULL
) STRICT;
CREATE TABLE day_notice (
    pool_id TEXT NOT NULL REFERENCES pool(pool_id),
    date    TEXT NOT NULL,
    text    TEXT NOT NULL
) STRICT;
CREATE TABLE day_warning (
    date   TEXT NOT NULL,
    code   TEXT NOT NULL,
    params TEXT NOT NULL
) STRICT;
CREATE TABLE lane_day (
    basin_id         TEXT NOT NULL,
    weekday          INTEGER NOT NULL,
    lane_count       INTEGER NOT NULL,
    strips           TEXT NOT NULL,
    unresolved_lanes TEXT NOT NULL,
    confidence       TEXT NOT NULL,
    PRIMARY KEY (basin_id, weekday)
) STRICT;
CREATE TABLE alias (
    pool_id TEXT NOT NULL REFERENCES pool(pool_id),
    norm    TEXT NOT NULL
) STRICT;
CREATE INDEX session_by_date ON session(date, pool_id);
CREATE INDEX day_by_date ON day(date, pool_id);
"""

#: The insert columns per table, in schema order. A test asserts these against the store's own
#: `PRAGMA table_info`, so the DDL above and the row builders below cannot drift apart.
TABLE_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "pool": (
        "pool_id",
        "name",
        "kind",
        "address",
        "lat",
        "lon",
        "url",
        "description",
        "phone",
        "freshness",
        "admission_state",
        "prices_doc",
        "source",
        "curated",
        "valid_as_of",
        "last_admission_before_s",
        "operating_season",
    ),
    "pool_basin": (
        "pool_id",
        "basin_id",
        "name",
        "kind",
        "length_m",
        "width_m",
        "lanes",
        "nominal_temp_c",
        "measured_temp_c",
        "diving_platforms_m",
        "physical_source",
        "lane_plan_url",
    ),
    "pool_locker": ("pool_id", "ord", "doc"),
    "pool_rental": ("pool_id", "ord", "doc"),
    "pool_feature": ("pool_id", "feature_key", "doc"),
    "day": ("pool_id", "date", "status", "detail_code", "closure_code", "detail_params"),
    "session": (
        "pool_id",
        "date",
        "basin_id",
        "basin_name",
        "length_m",
        "lanes",
        "start",
        "end",
        "access_kind",
        "access_params",
        "weather",
    ),
    "day_notice": ("pool_id", "date", "text"),
    "day_warning": ("date", "code", "params"),
    "lane_day": (
        "basin_id",
        "weekday",
        "lane_count",
        "strips",
        "unresolved_lanes",
        "confidence",
    ),
    "alias": ("pool_id", "norm"),
}

#: `meta` is written last (it carries the content hash over every other table), so it sits
#: outside the row-building map but takes the same insert path.
TABLE_COLUMNS_WITH_META: Final[Mapping[str, tuple[str, ...]]] = {
    **TABLE_COLUMNS,
    "meta": ("key", "value"),
}

#: One row, as the values its table's columns take (str/int/float/None only — every Decimal,
#: enum and nested document is flattened at build time, so the content hash is exact JSON).
type Row = tuple[str | int | float | None, ...]


@dataclass(frozen=True, slots=True)
class ExportReport:
    """What one export produced — the line the CLI prints and the numbers CI watches."""

    horizon_start: date
    horizon_end: date
    pools: int
    sessions: int
    day_rows: int
    notices: int
    warnings: int
    bytes: int
    content_hash: str
    #: Horizon days whose year is outside `calendar.known_years` (E2's reseed signal). They are
    #: still exported — with the same coverage warning `/swim` serves — never withheld.
    uncovered_days: int


@dataclass(frozen=True, slots=True)
class _Tables:
    """Every exported row, table by table, before it reaches SQLite. Built whole so the content
    hash is computed over the exact bytes that get inserted."""

    rows: Mapping[str, tuple[Row, ...]]

    def count(self, table: str) -> int:
        return len(self.rows[table])


# --- JSON helpers ------------------------------------------------------------------------


def _json(value: object) -> str:
    """Canonical JSON: sorted keys, no whitespace, unicode kept. Deterministic by construction,
    which is what makes the content hash stable across runs (acceptance 5)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _hhmm(t: time) -> str:
    return t.strftime("%H:%M")


def _access_doc(access: SessionAccess) -> tuple[str, str]:
    """The access arm's class name plus its own fields as JSON — the exact pair the parity
    sweep compares against `type(session.access).__name__` and `dataclasses.asdict(access)`."""
    return type(access).__name__, _json(dataclasses.asdict(access))


# --- Facility-level (date-independent) rows ----------------------------------------------


def _admission_doc(admission: Admission) -> tuple[str, str | None]:
    """The admission state plus, for a `Tariff`, its whole table as JSON. `price` is
    deliberately not a table: the bracket depends on the person, so Swift picks it (mirroring
    `domain/pricing.price_for`) from the doc."""
    match admission:
        case Tariff(table):
            return "tariff", _price_doc(table)
        case Free():
            return "free", None
        case Unknown():
            return "unknown", None
        case _ as unreachable:
            assert_never(unreachable)


def _price_doc(table: PriceTable) -> str:
    return _json(
        {
            "entries": [
                {
                    "category": e.category.value,
                    "amount_chf": float(e.amount_chf),
                    "display": e.display,
                    "min_age": e.min_age,
                }
                for e in table.entries
            ],
            "valid_as_of": table.valid_as_of.isoformat() if table.valid_as_of is not None else None,
            "source_url": table.source_url,
        }
    )


def _season_doc(season: OperatingSeason) -> str:
    """The page-stated season. Days are named ONLY at `DAY` precision — a `MONTH` window is
    whole months inclusive, and rendering it day-precise would overstate the page."""
    window = season.window
    doc: dict[str, object] = {
        "start_month": window.start.month,
        "end_month": window.end.month,
        "precision": window.precision.value,
        "weather": season.weather.value,
        "start_day": None,
        "end_day": None,
    }
    if window.precision is DatePrecision.DAY:
        doc["start_day"] = window.start.day
        doc["end_day"] = window.end.day
    return _json(doc)


def _pool_row(row: RosterEntry, facility: Facility | None) -> Row:
    entry = row.entry
    admission_state, prices_doc = (
        _admission_doc(facility.admission) if facility is not None else ("unknown", None)
    )
    provenance = facility.provenance if facility is not None else None
    last_admission = facility.last_admission_before if facility is not None else None
    season = facility.operating_season if facility is not None else None
    return (
        entry.pool_id,
        entry.name,
        entry.kind.value,
        # The domain keeps "" as "no published address"; the export renders absence as NULL,
        # exactly as `/pools` renders it as JSON null.
        entry.address or None,
        entry.geo.lat if entry.geo is not None else None,
        entry.geo.lon if entry.geo is not None else None,
        entry.url,
        entry.description,
        entry.phone,
        row.freshness.value,
        admission_state,
        prices_doc,
        provenance.source if provenance is not None else None,
        int(provenance.curated) if provenance is not None else None,
        (
            provenance.valid_as_of.isoformat()
            if provenance is not None and provenance.valid_as_of is not None
            else None
        ),
        int(last_admission.total_seconds()) if last_admission is not None else None,
        _season_doc(season) if season is not None else None,
    )


def _basin_row(facility: Facility, basin: Basin) -> Row:
    dims = basin.dimensions
    return (
        str(facility.identity.facility_id),
        str(basin.basin_id),
        basin.name,
        basin.kind.value,
        _num(dims.length_m) if dims is not None else None,
        _num(dims.width_m) if dims is not None else None,
        basin.lanes,
        _num(basin.nominal_temp_c),
        _num(basin.measured_temp_c),
        _json([float(h) for h in basin.diving_platforms_m]),
        basin.physical_source.value,
        basin.lane_plan_source.url if basin.lane_plan_source is not None else None,
    )


def _locker_rows(facility: Facility) -> Iterator[Row]:
    for ordinal, locker in enumerate(facility.lockers):
        doc = _json(
            {
                "category": locker.category.value,
                "fee_chf": _num(locker.fee_chf),
                "deposit_chf": _num(locker.deposit_chf),
                "period": locker.period,
                "mechanism": locker.mechanism.value if locker.mechanism is not None else None,
                "raw": locker.raw,
            }
        )
        yield (str(facility.identity.facility_id), ordinal, doc)


def _rental_fee(fee: RentalFee) -> tuple[str, float | None]:
    """The closed fee union on the wire: a stated-gratis rental is `("gratis", None)`, never
    conflated with the unstated `("unstated", None)`."""
    match fee:
        case Priced(amount_chf):
            return "priced", float(amount_chf)
        case Gratis():
            return "gratis", None
        case Unstated():
            return "unstated", None
        case _ as unreachable:
            assert_never(unreachable)


def _rental_rows(facility: Facility) -> Iterator[Row]:
    for ordinal, rental in enumerate(facility.rentals):
        fee, amount = _rental_fee(rental.fee)
        doc = _json(
            {
                "kind": rental.kind.value,
                "fee": fee,
                "fee_chf": amount,
                "deposit_chf": _num(rental.deposit_chf),
                "period": rental.period,
                "raw": rental.raw,
            }
        )
        yield (str(facility.identity.facility_id), ordinal, doc)


def _feature_day_docs(
    facility: Facility, feature: Feature, days: Sequence[date], calendar: ZurichCalendar
) -> dict[str, object]:
    """A feature's own hours, resolved per horizon date.

    There is deliberately NO `feature_day` table: measured, every feature citywide has
    `hours=()`, so a date-keyed table would ship zero rows over the whole horizon. When a feature
    DOES state hours, its resolved windows ride inside its `doc` — same table, no schema change.
    """
    resolved: dict[str, object] = {}
    for day in days:
        schedule = resolve_hours(facility, feature.hours, (), day, calendar)
        match schedule:
            case OpenDay(sessions):
                resolved[day.isoformat()] = {
                    "windows": [[_hhmm(s.time.start), _hhmm(s.time.end)] for s in sessions],
                    "closed_reason": None,
                }
            case ClosedDay(code):
                resolved[day.isoformat()] = {"windows": [], "closed_reason": code.value}
            case OpenUnscheduledDay():
                # Open per the facility's season with hours unpublished: nothing to list and no
                # closed reason — unknown, never conflated with closed.
                resolved[day.isoformat()] = {"windows": [], "closed_reason": None}
            case _ as unreachable:
                assert_never(unreachable)
    return resolved


def _feature_key(feature: Feature, seen: Counter[str]) -> str:
    """`kind` is the natural key, but a facility may publish two features of one kind (two
    saunas, two terraces), and the table is keyed `(pool_id, feature_key)`. So a repeat kind
    takes a deterministic `#n` suffix rather than silently colliding — a `UNIQUE` failure would
    abort the whole export, and dropping the second feature would lose a published fact."""
    seen[feature.kind.value] += 1
    ordinal = seen[feature.kind.value]
    return feature.kind.value if ordinal == 1 else f"{feature.kind.value}#{ordinal}"


def _feature_rows(
    facility: Facility, days: Sequence[date], calendar: ZurichCalendar
) -> Iterator[Row]:
    seen: Counter[str] = Counter()
    for feature in facility.features:
        doc = _json(
            {
                "kind": feature.kind.value,
                "name": feature.name,
                "surcharge_chf": _num(feature.surcharge_chf),
                "temp_c": _num(feature.temp_c),
                "note": feature.note,
                "hours": [
                    {
                        "weekdays": sorted(int(w) for w in rule.weekdays),
                        "start": _hhmm(rule.time.start),
                        "end": _hhmm(rule.time.end),
                    }
                    for rule in feature.hours
                ],
                "days": _feature_day_docs(facility, feature, days, calendar)
                if feature.hours
                else {},
            }
        )
        yield (str(facility.identity.facility_id), _feature_key(feature, seen), doc)


def _strip_doc(strip: LaneStrip) -> dict[str, object]:
    return {
        "lane": strip.lane,
        "segments": [
            {
                "start": _hhmm(seg.time.start),
                "end": _hhmm(seg.time.end),
                "access": type(seg.access).__name__,
                "owner": None if isinstance(seg.access, PublicSwim) else owner_label(seg.access),
            }
            for seg in strip.segments
        ],
    }


def _lane_day_rows(facility: Facility) -> Iterator[Row]:
    """Seven rows per basin carrying a parsed plan — keyed by WEEKDAY, because a Belegungsplan
    IS a weekly plan. Keying it by date would multiply the largest payload by ~400 for no new
    information. `unresolved_lanes` and `confidence` ride along because `partial` (a rendered
    field on the client's lane badges) is derived from them, not from the strips."""
    for basin in facility.basins:
        plan = basin.lane_plan
        if not isinstance(plan, LanePlan):
            continue
        for weekday in Weekday:
            view = lane_day_view(plan, weekday)
            yield (
                str(basin.basin_id),
                int(weekday),
                view.lane_count,
                _json([_strip_doc(s) for s in view.strips]),
                _json(sorted(plan.coverage.unresolved_lanes)),
                plan.coverage.confidence.value,
            )


# --- Date-resolved rows -------------------------------------------------------------------


def _status_row(status: FacilityStatus, day: date) -> Row:
    """One `FacilityStatus`, through the fixed domain→client field mapping
    (`STATUS_FIELD_TO_COLUMN`).

    A pool-day with sessions has no `day` row: `find_swim_options` emits a status only when the
    facility produced no options that day, and the export keeps exactly that shape.
    """
    return (
        str(status.facility_id),
        day.isoformat(),
        status.status,
        status.code.value,
        status.closure.value if status.closure is not None else None,
        _json(dict(status.params)),
    )


def _session_rows(result: QueryResult, day: date) -> Iterator[Row]:
    for option in result.options:
        access_kind, access_params = _access_doc(option.session.access)
        yield (
            str(option.facility_id),
            day.isoformat(),
            str(option.basin_id),
            option.basin_name,
            _num(option.basin_length_m),
            option.lanes,
            _hhmm(option.session.time.start),
            _hhmm(option.session.time.end),
            access_kind,
            access_params,
            option.session.weather.value,
        )


def render_warning(code: str, params: Mapping[str, str]) -> str:
    """Render a `day_warning` row exactly as `find_swim_options` renders that warning today.

    The export stores the CODE + params so the client can say it in its own language; this
    function is what lets the parity sweep assert that the decomposition lost nothing — it
    compares `render_warning(...)` against `QueryResult.warnings` verbatim.
    """
    if code == WARNING_CALENDAR_COVERAGE:
        return (
            f"calendar data not available for {params['year']}; "
            "holiday-dependent schedules may be inaccurate"
        )
    return (
        f"{params['date']} is a public holiday and these pools do not publish their "
        f"holiday hours; the times shown are their usual weekday hours and are "
        f"unconfirmed: {params['pools']}"
    )


def _unverified_holiday_pools(
    facilities: Iterable[Facility], day: date, calendar: ZurichCalendar
) -> tuple[str, ...]:
    """The pools showing ordinary weekday hours on a public holiday because no source states
    their holiday policy — the same set `find_swim_options` names in its warning, derived from
    the same resolver call rather than by parsing the rendered sentence back apart."""
    named: set[str] = set()
    for facility in facilities:
        for basin in facility.basins:
            if not basin.rules:
                continue
            schedule = resolve_basin(facility, basin, day, calendar)
            if isinstance(schedule, OpenDay) and schedule.holiday_policy_unverified:
                named.add(facility.identity.name)
    return tuple(sorted(named))


def _warning_rows(
    facilities: tuple[Facility, ...], day: date, calendar: ZurichCalendar
) -> list[Row]:
    """The day's warnings, decomposed into (code, params) — in the order `find_swim_options`
    appends them: coverage first, holiday-hours last."""
    rows: list[Row] = []
    if not calendar.covers(day):
        rows.append((day.isoformat(), WARNING_CALENDAR_COVERAGE, _json({"year": str(day.year)})))
    unverified = _unverified_holiday_pools(facilities, day, calendar)
    if unverified:
        rows.append(
            (
                day.isoformat(),
                WARNING_HOLIDAY_HOURS_UNVERIFIED,
                _json({"date": day.isoformat(), "pools": ", ".join(unverified)}),
            )
        )
    return rows


def resolve_day(
    facilities: tuple[Facility, ...],
    calendar: ZurichCalendar,
    roster: tuple[RosterEntry, ...],
    day: date,
) -> QueryResult:
    """The one live-query call the whole export is a projection of: a person-free, place-free
    query at noon. Person- and place-dependent fields (eligibility, price, distance) and
    time-of-day-dependent ones (`open_at_query_time`, the lane derivations) are the client's
    half of the seam (E1) and are deliberately not read from this result."""
    return find_swim_options(
        SwimQuery(
            person=Person(gender=None, age=None),
            at=datetime.combine(day, _RESOLVE_AT, tzinfo=_ZURICH),
            near=None,
            radius_km=None,
        ),
        facilities,
        calendar,
        roster,
    )


# --- Assembly ------------------------------------------------------------------------------


def horizon(today: date, days: int) -> tuple[date, ...]:
    """The exported dates: `days` of them, starting today. Fixed regardless of calendar
    coverage (E2) — an unseeded year degrades to term-time scope and carries the warning that
    says so, which is exactly what the web serves."""
    return tuple(today + timedelta(days=offset) for offset in range(days))


def _static_tables(
    facilities: tuple[Facility, ...],
    roster: tuple[RosterEntry, ...],
    aliases: tuple[tuple[str, str], ...],
    calendar: ZurichCalendar,
    dates: Sequence[date],
) -> dict[str, list[Row]]:
    by_id = {str(f.identity.facility_id): f for f in facilities}
    tables: dict[str, list[Row]] = {name: [] for name in TABLE_COLUMNS}
    for row in roster:
        facility = by_id.get(row.entry.pool_id)
        tables["pool"].append(_pool_row(row, facility))
        if facility is None:
            continue
        tables["pool_basin"].extend(_basin_row(facility, b) for b in facility.basins)
        tables["pool_locker"].extend(_locker_rows(facility))
        tables["pool_rental"].extend(_rental_rows(facility))
        tables["pool_feature"].extend(_feature_rows(facility, dates, calendar))
        tables["lane_day"].extend(_lane_day_rows(facility))
    known = {str(r.entry.pool_id) for r in roster}
    tables["alias"].extend((pool_id, norm) for norm, pool_id in aliases if str(pool_id) in known)
    return tables


def _resolved_tables(
    tables: dict[str, list[Row]],
    facilities: tuple[Facility, ...],
    roster: tuple[RosterEntry, ...],
    calendar: ZurichCalendar,
    dates: Sequence[date],
) -> None:
    """Sweep the horizon, one `find_swim_options` per date, and project each answer onto the
    `session` / `day` / `day_notice` / `day_warning` rows."""
    for day in dates:
        result = resolve_day(facilities, calendar, roster, day)
        tables["session"].extend(_session_rows(result, day))
        tables["day"].extend(_status_row(s, day) for s in result.statuses)
        tables["day_notice"].extend(
            (str(n.facility_id), day.isoformat(), n.text) for n in result.notices
        )
        tables["day_warning"].extend(_warning_rows(facilities, day, calendar))


def _content_hash(tables: _Tables, start: date, end: date) -> str:
    """sha256 over the exact rows, the schema version and the horizon — but NOT `built_at`, so
    a re-export of unchanged gold over the same horizon hashes identically (acceptance 5)."""
    digest = hashlib.sha256()
    digest.update(
        _json(
            {
                "schema_version": SCHEMA_VERSION,
                "horizon_start": start.isoformat(),
                "horizon_end": end.isoformat(),
                "tables": {name: list(rows) for name, rows in tables.rows.items()},
            }
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _gold_valid_as_of(facilities: tuple[Facility, ...]) -> str | None:
    stamps = [f.provenance.valid_as_of for f in facilities if f.provenance.valid_as_of is not None]
    return max(stamps).isoformat() if stamps else None


def _meta_rows(
    tables: _Tables, *, start: date, end: date, built_at: datetime, gold_valid_as_of: str | None
) -> tuple[tuple[str, str], ...]:
    return (
        ("schema_version", str(SCHEMA_VERSION)),
        ("built_at", built_at.isoformat()),
        ("horizon_start", start.isoformat()),
        ("horizon_end", end.isoformat()),
        ("gold_valid_as_of", gold_valid_as_of or ""),
        ("content_hash", _content_hash(tables, start, end)),
    )


# --- Writing the file ----------------------------------------------------------------------


def _insert(conn: sqlite3.Connection, table: str, rows: Sequence[Row]) -> None:
    columns = TABLE_COLUMNS_WITH_META[table]
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{c}"' for c in columns)
    conn.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', rows)  # noqa: S608


def _sidecars(path: Path) -> tuple[Path, Path]:
    """A WAL sidecar pair survives a journal-mode conversion, and a store shipped beside one is
    a store an iOS bundle cannot read."""
    return Path(f"{path}-wal"), Path(f"{path}-shm")


def _integrity_error(row: tuple[str, ...] | None) -> ProviderError | None:
    """`PRAGMA integrity_check`'s answer, judged. A pure function so the failure arm is testable:
    a corrupt store cannot be conjured on demand, but the judgement about its answer can."""
    if row is None or row[0] != "ok":
        return ProviderSpecific(provider="ios_export", detail=f"integrity_check failed: {row!r}")
    return None


def _analyzed(conn: sqlite3.Connection) -> bool:
    """Whether `ANALYZE` left any statistics behind (the table itself is always created)."""
    present = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1'"
    ).fetchone()[0]
    if present != 1:
        return False
    return int(conn.execute("SELECT count(*) FROM sqlite_stat1").fetchone()[0]) > 0


def _finalize(conn: sqlite3.Connection) -> ProviderError | None:
    """The bundle-readability sequence. `journal_mode` can fail SILENTLY (returning the previous
    mode), which is why the caller also asserts the header bytes; `ANALYZE` gives the device's
    first query real statistics; `VACUUM` shrinks the file before it is bundled."""
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    integrity = _integrity_error(conn.execute("PRAGMA integrity_check").fetchone())
    if integrity is not None:
        return integrity
    # `ANALYZE` always CREATES `sqlite_stat1`; what matters is whether it wrote any statistics
    # into it, which is what gives the device's first query a real plan. So count the ROWS.
    if not _analyzed(conn):
        return ProviderSpecific(provider="ios_export", detail="ANALYZE wrote no statistics")
    return None


def _not_wal(path: Path) -> ProviderError | None:
    """Header bytes 18-19: `0101` for delete/truncate/memory/off, `0202` only for WAL. This
    proves the property that matters — a WAL file opens fine on read-only media and fails on the
    FIRST PREPARE, so nothing short of a byte check is evidence."""
    with path.open("rb") as handle:
        handle.seek(18)
        marker = handle.read(2)
    if marker == b"\x02\x02":
        return ProviderSpecific(provider="ios_export", detail="exported store is in WAL mode")
    return None


def _write_store(
    path: Path, tables: _Tables, meta: Sequence[tuple[str, str]]
) -> ProviderError | None:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.executescript(_SCHEMA)
        conn.execute("BEGIN")
        for table, rows in tables.rows.items():
            _insert(conn, table, rows)
        _insert(conn, "meta", tuple(meta))
        conn.execute("COMMIT")
        return _finalize(conn)
    except sqlite3.DatabaseError as exc:  # pragma: no cover - a schema/id defect, not a flow
        return SchemaMismatch(source="ios_export", detail=str(exc))
    finally:
        conn.close()


def export_ios(
    conn: sqlite3.Connection, out: Path, *, today: date, days: int = DEFAULT_DAYS
) -> Result[ExportReport, ProviderError]:
    """Project the gold store into the iOS store at `out`, resolved for `days` days from `today`.

    Network-free (gold is the only input) and written through `atomic_swap`, so a failure at any
    step leaves any previous export content-unchanged rather than half-written.
    """
    if days < 1:
        # `--days 0` would index an empty horizon; a typed refusal beats an IndexError escaping
        # an errors-as-values surface.
        return Err(ProviderSpecific(provider="ios_export", detail=f"days must be >= 1, got {days}"))
    try:
        calendar = load_calendar(conn)
    except LookupError as exc:
        return Err(SchemaMismatch(source="gold", detail=str(exc)))
    facilities = GoldRepository(conn).load_all()
    roster = load_roster(conn)
    aliases = load_alias_rows(conn)
    dates = horizon(today, days)

    rows = _static_tables(facilities, roster, aliases, calendar, dates)
    _resolved_tables(rows, facilities, roster, calendar, dates)
    tables = _Tables(rows={name: tuple(values) for name, values in rows.items()})
    meta = _meta_rows(
        tables,
        start=dates[0],
        end=dates[-1],
        built_at=datetime.now(_ZURICH),
        gold_valid_as_of=_gold_valid_as_of(facilities),
    )

    with atomic_swap(out) as staging:
        failure = _write_store(staging.path, tables, meta)
        if failure is None:
            failure = _not_wal(staging.path)
        for sidecar in _sidecars(staging.path):
            sidecar.unlink(missing_ok=True)
        if failure is not None:
            return Err(failure)  # no commit -> any previous export is content-unchanged
        size = staging.path.stat().st_size
        staging.commit()
    for sidecar in _sidecars(out):
        sidecar.unlink(missing_ok=True)

    return Ok(
        ExportReport(
            horizon_start=dates[0],
            horizon_end=dates[-1],
            pools=tables.count("pool"),
            sessions=tables.count("session"),
            day_rows=tables.count("day"),
            notices=tables.count("day_notice"),
            warnings=tables.count("day_warning"),
            bytes=size,
            content_hash=dict(meta)["content_hash"],
            uncovered_days=sum(1 for day in dates if not calendar.covers(day)),
        )
    )
