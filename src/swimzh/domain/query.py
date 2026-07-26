"""The query surface: `find_swim_options` — the library's public answer to
"where can I swim?"

Given a person, a moment (now or future), and optionally a location + radius, it resolves
every curated facility's schedule for that date and returns concrete options, each annotated
with *explainable* eligibility, price, distance, and provenance.

It deliberately distinguishes three outcomes so an empty answer is never ambiguous:
  * an option (open, with eligibility),
  * a facility that is **closed** that day (with reason), and
  * a facility whose schedule is **not yet curated** (unknown — identity known via the pool
    roster, schedule not curated) — never conflated with "closed".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, assert_never
from zoneinfo import ZoneInfo

from swimzh.core.errors import ProviderError, describe
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import EligibilityResult, eligibility
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.closure import ClosureCode
from swimzh.domain.geo import GeoPoint, haversine_km
from swimzh.domain.lane_plan import (
    LaneAvailability,
    LaneAvailabilityTimeline,
    LanePanel,
    LanePlan,
    lane_availability_at,
    lane_availability_timeline,
    lane_panel,
)
from swimzh.domain.lockers import LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    Feature,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
    reconstruct_pool_id,
)
from swimzh.domain.person import Person
from swimzh.domain.pricing import PriceEntry, price_for
from swimzh.domain.resolver import resolve_basin, resolve_hours
from swimzh.domain.schedule import ClosedDay, DaySchedule, OpenDay, ResolvedSession, Weekday

_ZURICH = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True, slots=True)
class SwimQuery:
    person: Person
    at: datetime
    near: GeoPoint | None = None
    radius_km: float | None = None


# --- Live occupancy ---------------------------------------------------------------------
#
# Occupancy is LIVE-ONLY: these types live here in `query.py`, are never imported into
# `models.py` or the gold codec (guarded by a regression test), and are attached only
# when `query.at` is ~now — keyed by `identity.crowdmonitor_keys`.


@dataclass(frozen=True, slots=True)
class Occupancy:
    """A raw live occupancy reading (people/percent/capacity) from a provider."""

    facility_id: PoolId
    measured_at: datetime
    percent_full: float | None
    people: int | None
    capacity: int | None
    source: str

    def __post_init__(self) -> None:
        # Guard the tz-aware house convention at construction: a naive `measured_at`
        # would make the derived-age subtraction raise deep inside `find_swim_options`
        # (an exception escape in an errors-as-values surface). Fail loudly here
        # instead, like `TimeRange.__post_init__`.
        if self.measured_at.tzinfo is None:
            raise ValueError("Occupancy.measured_at must be tz-aware (project rule)")


@dataclass(frozen=True, slots=True)
class LiveOccupancy:
    """A reading successfully attached to an option; freshness is *derived* from
    `measured_at` (via `age`), never stored as a separate freshness enum."""

    reading: Occupancy
    age: timedelta  # now - reading.measured_at, computed at attach time

    def is_stale(self, limit: timedelta = timedelta(minutes=10)) -> bool:
        return self.age > limit


@dataclass(frozen=True, slots=True)
class OccupancyUnavailable:
    """Occupancy was requested but could not be resolved — with the reason, so an empty
    answer is never ambiguous ("provider offline" | "no crowdmonitor key" | ...)."""

    reason: str


type OccupancyResult = LiveOccupancy | OccupancyUnavailable


class OccupancyProvider(Protocol):
    """Port for a live-occupancy source (errors as values, per house convention).

    The real CrowdMonitor adapter is deferred until a ToS check is recorded in
    `data/sources.md`; until then only fakes implement this port.
    """

    def read(self, keys: tuple[str, ...]) -> Result[Occupancy, ProviderError]: ...


# --- Live water temperature (Baditicker) ------------------------------------------------
#
# Water temperature is LIVE-ONLY, exactly like occupancy: these types live here in `query.py`,
# are NEVER imported into `models.py` or the gold codec (guarded by an import-token regression
# test — note that `identity.baditicker_poiid`, the *key*, IS persisted; only the reading is
# not). The reading is timestamped and seasonal, so it carries its own freshness (`age`) rather
# than a stored freshness enum. The adapter is keyed by `poiid` and NEVER constructs a `PoolId`;
# `read_temperature` attaches the reading to a known `identity`.


@dataclass(frozen=True, slots=True)
class TempReading:
    """A raw live water-temperature reading for one bath from the Baditicker feed.

    Carries NO `PoolId` — the adapter is poiid-keyed and never mints an identity."""

    measured_at: datetime  # tz-aware Europe/Zurich (the feed's `dateModified`)
    celsius: Decimal | None  # None when the feed cell is empty (measured nothing yet)
    is_open: bool  # from `openClosedTextPlain`
    source: str  # "baditicker"

    def __post_init__(self) -> None:
        # Guard the tz-aware house convention at construction, mirroring `Occupancy`: a naive
        # `measured_at` would make the derived-age subtraction raise deep in `read_temperature`
        # (an exception escape in an errors-as-values surface). Fail loudly here instead.
        if self.measured_at.tzinfo is None:
            raise ValueError("TempReading.measured_at must be tz-aware (project rule)")


@dataclass(frozen=True, slots=True)
class LiveTemp:
    """A reading successfully attached to a facility; freshness is *derived* from `measured_at`
    (via `age`), never stored as a separate freshness enum. `celsius` may be `None` (open but
    not yet measured) — that is still a live answer, distinct from `TempUnavailable`."""

    reading: TempReading
    age: timedelta  # now - reading.measured_at, computed at attach time

    def is_stale(self, limit: timedelta = timedelta(hours=6)) -> bool:
        return self.age > limit


@dataclass(frozen=True, slots=True)
class TempUnavailable:
    """Water temperature was requested but could not be resolved — with the reason, so an empty
    answer is never ambiguous ("no baditicker key" | provider `describe()`). Reserved for the
    no-key and provider-error cases; an empty feed cell yields `LiveTemp(celsius=None)` instead."""

    reason: str


type TempResult = LiveTemp | TempUnavailable


class TemperatureProvider(Protocol):
    """Port for a live water-temperature source (errors as values, per house convention).

    The real Baditicker adapter (`providers/baditicker.py`) lands in a later slice; until then
    only fakes implement this port."""

    def read(self, poiid: str) -> Result[TempReading, ProviderError]: ...


def read_temperature(
    provider: TemperatureProvider, identity: PoolIdentity, now: datetime
) -> TempResult:
    """Resolve one facility's live water temperature, keyed by `identity.baditicker_poiid`.

    No key -> `TempUnavailable("no baditicker key")`. Otherwise the provider's `Ok` reading
    becomes a `LiveTemp` (age derived from `measured_at` at attach) — INCLUDING an empty
    `celsius`, which stays a `LiveTemp(celsius=None)`, never `TempUnavailable`. A provider `Err`
    becomes an explainable `TempUnavailable`, never an exception (errors-as-values)."""
    if identity.baditicker_poiid is None:
        return TempUnavailable(reason="no baditicker key")
    match provider.read(identity.baditicker_poiid):
        case Ok(reading):
            return LiveTemp(reading=reading, age=now - reading.measured_at)
        case Err(error):
            return TempUnavailable(reason=describe(error))
        case _ as unreachable:
            assert_never(unreachable)


# A query counts as "~now" (occupancy-relevant) within this window of wall-clock now.
_NOW_TOLERANCE = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class SwimOption:
    facility_id: PoolId
    facility_name: str
    facility_kind: PoolKind  # indoor/outdoor/… — from the pool identity
    basin_id: BasinId
    basin_name: str
    basin_kind: BasinKind
    basin_length_m: Decimal | None  # the immutable physical fact behind the glance badge
    lanes: int | None
    water_temp_c: Decimal | None  # the basin's nominal (design) temperature, not live
    session: ResolvedSession
    eligibility: EligibilityResult
    open_at_query_time: bool
    price: PriceEntry | None
    distance_km: float | None
    provenance: Provenance
    # None = not requested (no provider wired, or query.at is not ~now).
    # LiveOccupancy / OccupancyUnavailable = requested and resolved.
    live_occupancy: OccupancyResult | None = None
    # None = the basin has no parsed lane plan. A `LaneAvailability` is a pure derivation of
    # the STORED recurring plan, so — unlike live_occupancy — it is attached for ANY query
    # time (incl. future dates), computed at the QUERIED moment clamped into the session.
    lane_availability: LaneAvailability | None = None
    # The full lane split across the session (one segment per reservation boundary), also a
    # pure derivation of the stored plan — never stored. Powers the "4/6 then 2/6 after 18:00"
    # arc. None when the basin has no parsed plan.
    lane_timeline: LaneAvailabilityTimeline | None = None


class StatusCode(StrEnum):
    """The message identity of a no-options status — the i18n key space for `detail`.

    `status` says WHICH BUCKET ("closed" / "uncurated"); the code says which SENTENCE.
    `CLOSED_REASON` is deliberately a passthrough: the reason is still curated German free
    text (`"Sommerpause"`) travelling as a param, because mapping that text to a closed code
    set is S4's job — the ETL owns it, not the query layer. Recording it as a distinct code
    now means S4 replaces a known shape rather than discovering one.
    """

    CLOSED_REASON = "closed_reason"
    UNCURATED = "uncurated"


@dataclass(frozen=True, slots=True)
class FacilityStatus:
    """Why a facility produced no options: closed that day, or not yet curated."""

    facility_id: PoolId
    facility_name: str
    status: str  # "closed" | "uncurated"
    detail: str
    #: The message key + its interpolation values. `detail` is the current rendering of
    #: exactly this; it stays on the wire until S5.
    code: StatusCode = StatusCode.UNCURATED
    #: For a closure, WHICH closure (S4). None for `uncurated`.
    closure: ClosureCode | None = None
    params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FacilityNotice:
    """A pool alert active on the queried date (e.g. a maintenance closure)."""

    facility_id: PoolId
    facility_name: str
    text: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    options: tuple[SwimOption, ...]
    statuses: tuple[FacilityStatus, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    notices: tuple[FacilityNotice, ...] = field(default_factory=tuple)

    def eligible_options(self) -> tuple[SwimOption, ...]:
        return tuple(o for o in self.options if o.eligibility.allowed)


def _distance_km(query: SwimQuery, facility: Facility) -> float | None:
    if query.near is None or facility.geo is None:
        return None
    return haversine_km(query.near, facility.geo)


def _read_occupancy(
    provider: OccupancyProvider, identity: PoolIdentity, now: datetime
) -> OccupancyResult:
    """Resolve one facility's live occupancy, keyed by `identity.crowdmonitor_keys`.
    Provider errors become an explainable `OccupancyUnavailable`, never an exception."""
    if not identity.crowdmonitor_keys:
        return OccupancyUnavailable(reason="no crowdmonitor key")
    match provider.read(identity.crowdmonitor_keys):
        case Ok(reading):
            return LiveOccupancy(reading=reading, age=now - reading.measured_at)
        case Err(error):
            return OccupancyUnavailable(reason=describe(error))
        case _ as unreachable:
            assert_never(unreachable)


def find_swim_options(
    query: SwimQuery,
    facilities: tuple[Facility, ...],
    calendar: ZurichCalendar,
    roster: tuple[RosterEntry, ...] = (),
    *,
    occupancy: OccupancyProvider | None = None,
) -> QueryResult:
    at_local = query.at.astimezone(_ZURICH) if query.at.tzinfo is not None else query.at
    day = at_local.date()
    now_time = at_local.time()
    now = datetime.now(_ZURICH)
    at_aware = at_local if at_local.tzinfo is not None else at_local.replace(tzinfo=_ZURICH)
    # Occupancy is only meaningful for a "~now" query; a future (or past) `at` yields None.
    want_occupancy = abs(at_aware - now) <= _NOW_TOLERANCE

    warnings: list[str] = []
    if not calendar.covers(day):
        warnings.append(
            f"calendar data not available for {day.year}; "
            "holiday-dependent schedules may be inaccurate"
        )

    options: list[SwimOption] = []
    statuses: list[FacilityStatus] = []
    notices: list[FacilityNotice] = []

    for facility in facilities:
        distance = _distance_km(query, facility)
        if query.radius_km is not None and distance is not None and distance > query.radius_km:
            continue

        notices.extend(
            FacilityNotice(facility.identity.facility_id, facility.identity.name, notice.text)
            for notice in facility.notices
            if notice.active_on(day)
        )
        price = price_for(facility.prices, query.person.age) if facility.prices else None
        live: OccupancyResult | None = None
        if occupancy is not None and want_occupancy:
            live = _read_occupancy(occupancy, facility.identity, now)
        facility_closed_reason: str | None = None
        facility_closed: ClosedDay | None = None
        produced = False

        for basin in facility.basins:
            # Decision #5 gate: a basin with NO schedule rules has no verified session data — e.g.
            # a `PARSED_PROSE` basin whose physicals were auto-extracted from WFS prose. It is
            # surfaced in `/pools/{id}` detail (with its caveat) but MUST NOT yield a `/swim`
            # option. Skip it here explicitly, before `resolve_basin` — so it neither produces an
            # option nor a spurious "closed" status (a prose-only facility flows to `uncurated`).
            if not basin.rules:
                continue
            schedule = resolve_basin(facility, basin, day, calendar)
            match schedule:
                case ClosedDay(reason):
                    facility_closed_reason = reason
                    facility_closed = schedule
                case OpenDay(sessions):
                    for session in sessions:
                        produced = True
                        # Clamp the point eval to the QUERIED moment (`now_time`, the queried
                        # time-of-day already used by `open_at_query_time`) when it falls in the
                        # session, else the session start — so 12:00 and 18:00 report different
                        # lane splits. NOT the wall-clock `now` (that is reserved for occupancy
                        # freshness); using it would collapse a future/other-time query back to
                        # `session.time.start`.
                        weekday = Weekday(day.weekday())
                        t = now_time if session.time.contains(now_time) else session.time.start
                        lane_avail: LaneAvailability | None = None
                        lane_timeline: LaneAvailabilityTimeline | None = None
                        # `lane_plan` now carries a third state (`LanePlanUnavailable`); only a
                        # parsed `LanePlan` yields a derivation — a recorded failure is inert here.
                        if isinstance(basin.lane_plan, LanePlan):
                            lane_avail = lane_availability_at(basin.lane_plan, weekday, t)
                            lane_timeline = lane_availability_timeline(
                                basin.lane_plan, weekday, session.time
                            )
                        options.append(
                            SwimOption(
                                facility_id=facility.identity.facility_id,
                                facility_name=facility.identity.name,
                                facility_kind=facility.identity.kind,
                                basin_id=basin.basin_id,
                                basin_name=basin.name,
                                basin_kind=basin.kind,
                                basin_length_m=(
                                    basin.dimensions.length_m
                                    if basin.dimensions is not None
                                    else None
                                ),
                                lanes=basin.lanes,
                                water_temp_c=basin.nominal_temp_c,
                                session=session,
                                eligibility=eligibility(query.person, session.access),
                                open_at_query_time=session.time.contains(now_time),
                                price=price,
                                distance_km=distance,
                                provenance=facility.provenance,
                                live_occupancy=live,
                                lane_availability=lane_avail,
                                lane_timeline=lane_timeline,
                            )
                        )

        if not produced and facility_closed_reason is not None:
            statuses.append(
                FacilityStatus(
                    facility_id=facility.identity.facility_id,
                    facility_name=facility.identity.name,
                    status="closed",
                    detail=facility_closed_reason,
                    # S4: the classified code from the resolver, not a prose passthrough.
                    # `UNMAPPED` still carries the original German in `params.text`, so an
                    # unrecognised phrase degrades to the truth rather than to a blank.
                    code=StatusCode.CLOSED_REASON,
                    closure=facility_closed.code if facility_closed else None,
                    params=dict(facility_closed.params) if facility_closed else {},
                )
            )

    # The three-state answer goes live: every roster pool whose schedule is not among the
    # curated facilities we just resolved is `uncurated` (roster − scheduled) — never merged
    # with `closed`. An empty roster yields no uncurated rows (callers that only exercise
    # options pass none), so this stays a single uniform path, not a `registry is None` branch.
    statuses.extend(_uncurated_statuses(facilities, roster))

    options.sort(
        key=lambda o: (
            o.distance_km if o.distance_km is not None else float("inf"),
            o.session.time.start,
            o.facility_name,
        )
    )
    return QueryResult(
        options=tuple(options),
        statuses=tuple(statuses),
        warnings=tuple(warnings),
        notices=tuple(notices),
    )


@dataclass(frozen=True, slots=True)
class FeatureStatus:
    """A facility feature with its schedule resolved for the queried day.

    `schedule`/`open_at_query_time` are `None` when the feature has no separately
    stated hours (assume facility opening hours) — unknown, never conflated with
    closed."""

    feature: Feature
    schedule: DaySchedule | None
    open_at_query_time: bool | None


@dataclass(frozen=True, slots=True)
class BasinLanePanel:
    """A basin's lane panel for the facility-detail view — the basin's identity paired with
    the pure `LanePanel` derivation of its stored `LanePlan` (only basins with a plan)."""

    basin_id: BasinId
    basin_name: str
    panel: LanePanel


@dataclass(frozen=True, slots=True)
class FacilityDetail:
    """Facility-level statics for a detail view (`/pools/{id}`-shaped, not per-session):
    website, features (with hours resolved via the schedule resolver), lockers, and the
    basins with their physical attributes. `lane_panels` carries, for each basin that has a
    parsed Belegungsplan, the per-lane day timeline / best-time / roster derivations for the
    queried weekday (empty when no basin has a plan)."""

    facility_id: PoolId
    facility_name: str
    address: str
    website: str | None
    basins: tuple[Basin, ...]
    features: tuple[FeatureStatus, ...]
    lockers: tuple[LockerOption, ...]
    provenance: Provenance
    lane_panels: tuple[BasinLanePanel, ...] = field(default_factory=tuple)
    amenities: tuple[str, ...] = field(default_factory=tuple)
    accessibility: str | None = None
    last_admission_before: timedelta | None = None


def _feature_status(
    facility: Facility, feature: Feature, at_local: datetime, calendar: ZurichCalendar
) -> FeatureStatus:
    if not feature.hours:
        return FeatureStatus(feature=feature, schedule=None, open_at_query_time=None)
    schedule = resolve_hours(facility, feature.hours, (), at_local.date(), calendar)
    match schedule:
        case OpenDay(sessions):
            open_now = any(s.time.contains(at_local.time()) for s in sessions)
        case ClosedDay():
            open_now = False
    return FeatureStatus(feature=feature, schedule=schedule, open_at_query_time=open_now)


def facility_detail(facility: Facility, at: datetime, calendar: ZurichCalendar) -> FacilityDetail:
    """Assemble the static facility-level answer ("what does this pool offer?") with each
    feature's hours resolved for the queried moment via the existing resolver."""
    at_local = at.astimezone(_ZURICH) if at.tzinfo is not None else at
    weekday = Weekday(at_local.date().weekday())
    lane_panels = tuple(
        BasinLanePanel(
            basin_id=basin.basin_id,
            basin_name=basin.name,
            panel=lane_panel(basin.lane_plan, weekday),
        )
        for basin in facility.basins
        if isinstance(basin.lane_plan, LanePlan)
    )
    return FacilityDetail(
        facility_id=facility.identity.facility_id,
        facility_name=facility.identity.name,
        address=facility.address,
        website=facility.website,
        basins=facility.basins,
        features=tuple(_feature_status(facility, f, at_local, calendar) for f in facility.features),
        lockers=facility.lockers,
        provenance=facility.provenance,
        lane_panels=lane_panels,
        amenities=tuple(sorted(facility.amenities)),
        accessibility=facility.accessibility,
        last_admission_before=facility.last_admission_before,
    )


def _uncurated_statuses(
    facilities: tuple[Facility, ...], roster: tuple[RosterEntry, ...]
) -> list[FacilityStatus]:
    """`uncurated = roster − scheduled`: every roster pool whose canonical id is not among the
    curated facilities resolved this query. Identity is known (the roster), the schedule is
    not — so it is `uncurated`, distinct from a curated pool that is `closed` today.

    "Scheduled" is a facility carrying at least one basin with a schedule rule — NOT merely a
    facility_doc: a prose-only pool (auto-extracted PARSED_PROSE basins, no rules — Decision #5)
    has a facility_doc but no schedule, so it stays `uncurated` here, never silently dropped."""
    scheduled_ids = {
        str(f.identity.facility_id) for f in facilities if any(basin.rules for basin in f.basins)
    }
    return [
        FacilityStatus(
            facility_id=reconstruct_pool_id(row.entry.pool_id),
            facility_name=row.entry.name,
            status="uncurated",
            detail="schedule not yet curated",
            code=StatusCode.UNCURATED,
        )
        for row in roster
        if row.entry.pool_id not in scheduled_ids
    ]
