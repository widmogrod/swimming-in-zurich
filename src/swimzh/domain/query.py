"""The query surface: `find_swim_options` — the library's public answer to
"where can I swim?"

Given a person, a moment (now or future), and optionally a location + radius, it resolves
every curated facility's schedule for that date and returns concrete options, each annotated
with *explainable* eligibility, price, distance, and provenance.

It deliberately distinguishes three outcomes so an empty answer is never ambiguous:
  * an option (open, with eligibility),
  * a facility that is **closed** that day (with reason), and
  * a facility that is **schedule-less** — its `ScheduleFreshness` (`awaiting_scrape` /
    `no_source`; identity known via the roster, schedule not) — never conflated with "closed".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, assert_never
from zoneinfo import ZoneInfo

from swimzh.core.errors import ProviderError, describe
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import EligibilityResult, eligibility
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry, ScheduleFreshness
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
    OperatingSeason,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
    reconstruct_pool_id,
)
from swimzh.domain.person import Person
from swimzh.domain.pricing import PriceEntry, price_for
from swimzh.domain.rentals import RentalItem
from swimzh.domain.resolver import resolve_basin, resolve_hours
from swimzh.domain.schedule import (
    ClosedDay,
    DatePrecision,
    DaySchedule,
    OpenDay,
    OpenUnscheduledDay,
    ResolvedSession,
    Weekday,
)

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
    #: From `openClosedTextPlain`. `None` when the feed cell is EMPTY — absent is not closed.
    #: 5 of the 25 feed rows ship an empty cell (4 Hallenbäder + Männerbad, with
    #: `dateModified` 1–2.5 years stale); mapping that to `False` reported them as closed.
    #: `celsius` above already models an empty cell as `None`; this now matches it.
    is_open: bool | None
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


class TempUnavailableCode(StrEnum):
    """Why a live temperature could not be resolved — the i18n key space for that answer.

    The pseudolocale pass found this: `reason` was rendered verbatim, so a user saw the
    literal string "no baditicker key". That is both untranslated AND jargon; a code lets
    the UI say something a reader can act on while `reason` keeps the technical detail for
    logs.
    """

    #: The facility has no Baditicker id — nothing to ask.
    NO_KEY = "no_key"
    #: The provider was asked and failed. `reason` carries `describe(error)` for operators.
    PROVIDER_ERROR = "provider_error"
    #: No provider is wired at all — a deployment state, not a failure.
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class TempUnavailable:
    """Water temperature was requested but could not be resolved — with a CODE for the UI and
    a technical `reason` for operators, so an empty answer is never ambiguous. Reserved for the
    no-key and provider-error cases; an empty feed cell yields `LiveTemp(celsius=None)` instead."""

    reason: str
    code: TempUnavailableCode = TempUnavailableCode.PROVIDER_ERROR


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
        return TempUnavailable(reason="no baditicker key", code=TempUnavailableCode.NO_KEY)
    match provider.read(identity.baditicker_poiid):
        case Ok(reading):
            return LiveTemp(reading=reading, age=now - reading.measured_at)
        case Err(error):
            return TempUnavailable(reason=describe(error), code=TempUnavailableCode.PROVIDER_ERROR)
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

    `status` says WHICH BUCKET ("closed" / "awaiting_scrape" / "no_source"); the code says which
    SENTENCE. `CLOSED_REASON` is deliberately a passthrough: the reason is still curated German
    free text (`"Sommerpause"`) travelling as a param, because mapping that text to a closed code
    set is S4's job — the ETL owns it, not the query layer.

    The schedule-less codes mirror `ScheduleFreshness` (delete-curated-schedule-tier S1), which
    replaced the single `UNCURATED` code: `AWAITING_SCRAPE` (scrapeable, no schedule yet) vs
    `NO_SOURCE` (no timetable source at all). Neither is ever "closed".

    `OPEN_UNSCHEDULED` (sharedsource-fanout S1) is the fourth honest state: the facility's
    own page states an operating season it is inside, but publishes no hours. It REPLACES
    the `no_source` ghost for a season-carrying facility — the two are exclusive.
    """

    CLOSED_REASON = "closed_reason"
    AWAITING_SCRAPE = "awaiting_scrape"
    NO_SOURCE = "no_source"
    OPEN_UNSCHEDULED = "open_unscheduled"


@dataclass(frozen=True, slots=True)
class FacilityStatus:
    """Why a facility produced no options: closed that day, or not yet curated."""

    facility_id: PoolId
    facility_name: str
    status: str  # "closed" | "awaiting_scrape" | "no_source"
    #: The message key + its interpolation values. The mixed-language `detail` prose this
    #: replaced was retired in S5 — it was English in one branch and curated German in the
    #: other, which is the seam the whole i18n plan existed to close.
    code: StatusCode = StatusCode.NO_SOURCE
    #: For a closure, WHICH closure (S4). None for a schedule-less status.
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


def _price_of(admission: Admission, age: int | None) -> PriceEntry | None:
    """The per-person price the closed admission union resolves: only a `Tariff` pool has one.
    A `Free` pool's option still carries `price=None` (rendering free-ness is UI, deferred) —
    but the *data* distinguishes it from `Unknown` now, all the way to the store."""
    match admission:
        case Tariff(table):
            return price_for(table, age)
        case Free() | Unknown():
            return None
        case _ as unreachable:
            assert_never(unreachable)


def _seasonal_status(
    facility: Facility, season: OperatingSeason, schedule: DaySchedule
) -> FacilityStatus:
    """Project a rule-less season-carrying facility's day resolution onto a `/swim` status.

    In season -> `status: "open_unscheduled"` carrying the season window + weather as params;
    out of season (or under a facility closure) -> the SAME `"closed"` shape a seasonal scraped
    pool already serves (`closure_code: "out_of_season"` from the resolver's gate) — no new
    closed shape on the wire.
    """
    match schedule:
        case OpenUnscheduledDay(weather):
            window = season.window
            params = {
                "weather": weather.value,
                "season_start_month": str(window.start.month),
                "season_end_month": str(window.end.month),
                "season_precision": window.precision.value,
            }
            if window.precision is DatePrecision.DAY:
                params["season_start_day"] = str(window.start.day)
                params["season_end_day"] = str(window.end.day)
            return FacilityStatus(
                facility_id=facility.identity.facility_id,
                facility_name=facility.identity.name,
                status="open_unscheduled",
                code=StatusCode.OPEN_UNSCHEDULED,
                params=params,
            )
        case ClosedDay():
            return FacilityStatus(
                facility_id=facility.identity.facility_id,
                facility_name=facility.identity.name,
                status="closed",
                code=StatusCode.CLOSED_REASON,
                closure=schedule.code,
                params=dict(schedule.params),
            )
        case OpenDay():
            # A rule-less, exception-less resolution cannot produce sessions; reaching this
            # arm means the season gate itself is broken. Fail loudly rather than fabricate
            # a status.
            raise AssertionError("facility-level seasonal resolution cannot yield OpenDay")
        case _ as unreachable:
            assert_never(unreachable)


def _seasonal_status_for(
    facility: Facility, day: date, calendar: ZurichCalendar
) -> FacilityStatus | None:
    """The facility-level SEASON GATE (sharedsource-fanout S1): a rule-less facility whose
    page states an operating season resolves at FACILITY level — `/swim` reports it as
    `open_unscheduled` inside the window, or `closed`/`out_of_season` outside it. This
    REPLACES its `no_source` ghost (see `_schedule_less_statuses`), so the facility appears
    exactly once per query. `None` for every facility the gate does not apply to."""
    if facility.operating_season is None or any(b.rules for b in facility.basins):
        return None
    return _seasonal_status(
        facility,
        facility.operating_season,
        resolve_hours(facility, (), (), day, calendar),
    )


def _session_option(
    facility: Facility,
    basin: Basin,
    session: ResolvedSession,
    day: date,
    now_time: time,
    price: PriceEntry | None,
    distance: float | None,
    live: OccupancyResult | None,
    person: Person,
) -> SwimOption:
    """Shape one resolved session into a `SwimOption`, deriving the lane split at the
    QUERIED moment (`now_time`, the queried time-of-day already used by
    `open_at_query_time`) clamped into the session, else the session start — so 12:00 and
    18:00 report different lane splits. NOT the wall-clock now (that is reserved for
    occupancy freshness); using it would collapse a future/other-time query back to
    `session.time.start`."""
    weekday = Weekday(day.weekday())
    t = now_time if session.time.contains(now_time) else session.time.start
    lane_avail: LaneAvailability | None = None
    lane_timeline: LaneAvailabilityTimeline | None = None
    # `lane_plan` carries a third state (`LanePlanUnavailable`); only a parsed `LanePlan`
    # yields a derivation — a recorded failure is inert here.
    if isinstance(basin.lane_plan, LanePlan):
        lane_avail = lane_availability_at(basin.lane_plan, weekday, t)
        lane_timeline = lane_availability_timeline(basin.lane_plan, weekday, session.time)
    return SwimOption(
        facility_id=facility.identity.facility_id,
        facility_name=facility.identity.name,
        facility_kind=facility.identity.kind,
        basin_id=basin.basin_id,
        basin_name=basin.name,
        basin_kind=basin.kind,
        basin_length_m=(basin.dimensions.length_m if basin.dimensions is not None else None),
        lanes=basin.lanes,
        water_temp_c=basin.nominal_temp_c,
        session=session,
        eligibility=eligibility(person, session.access),
        open_at_query_time=session.time.contains(now_time),
        price=price,
        distance_km=distance,
        provenance=facility.provenance,
        live_occupancy=live,
        lane_availability=lane_avail,
        lane_timeline=lane_timeline,
    )


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
    # Pools showing ordinary weekday hours on a public holiday because no source states their
    # holiday policy. The hours are real, so the option stands — but it is not confirmed for
    # today, and saying nothing would present a guess as a fact.
    unverified_holiday_pools: set[str] = set()

    for facility in facilities:
        distance = _distance_km(query, facility)
        if query.radius_km is not None and distance is not None and distance > query.radius_km:
            continue

        notices.extend(
            FacilityNotice(facility.identity.facility_id, facility.identity.name, notice.text)
            for notice in facility.notices
            if notice.active_on(day)
        )
        price = _price_of(facility.admission, query.person.age)
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
                    if schedule.holiday_policy_unverified:
                        unverified_holiday_pools.add(facility.identity.name)
                    for session in sessions:
                        produced = True
                        options.append(
                            _session_option(
                                facility,
                                basin,
                                session,
                                day,
                                now_time,
                                price,
                                distance,
                                live,
                                query.person,
                            )
                        )
                case OpenUnscheduledDay():
                    # Unreachable via a basin: the rule-less skip above means `resolve_basin`
                    # always runs with rules, and the season gate emits this variant only for
                    # a RULE-LESS schedule. The facility-level seasonal path below is its one
                    # producer. Guarded so the NEXT variant is a loud error here, not a silent
                    # fall-through.
                    pass
                case _ as unreachable:
                    assert_never(unreachable)

        seasonal = _seasonal_status_for(facility, day, calendar)
        if seasonal is not None:
            statuses.append(seasonal)

        if not produced and facility_closed_reason is not None:
            statuses.append(
                FacilityStatus(
                    facility_id=facility.identity.facility_id,
                    facility_name=facility.identity.name,
                    status="closed",
                    # S4: the classified code from the resolver, not a prose passthrough.
                    # `UNMAPPED` still carries the original German in `params.text`, so an
                    # unrecognised phrase degrades to the truth rather than to a blank.
                    code=StatusCode.CLOSED_REASON,
                    closure=facility_closed.code if facility_closed else None,
                    params=dict(facility_closed.params) if facility_closed else {},
                )
            )

    # The freshness answer goes live: every roster pool whose schedule is not among the
    # facilities we just resolved carries its `ScheduleFreshness` status (roster − scheduled) —
    # `awaiting_scrape` or `no_source`, never merged with `closed`. An empty roster yields no such
    # rows (callers that only exercise options pass none), so this stays a single uniform path.
    statuses.extend(_schedule_less_statuses(facilities, roster))

    options.sort(
        key=lambda o: (
            o.distance_km if o.distance_km is not None else float("inf"),
            o.session.time.start,
            o.facility_name,
        )
    )
    if unverified_holiday_pools:
        named = ", ".join(sorted(unverified_holiday_pools))
        warnings.append(
            f"{day.isoformat()} is a public holiday and these pools do not publish their "
            f"holiday hours; the times shown are their usual weekday hours and are "
            f"unconfirmed: {named}"
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
    basins: tuple[Basin, ...]
    features: tuple[FeatureStatus, ...]
    lockers: tuple[LockerOption, ...]
    rentals: tuple[RentalItem, ...]
    provenance: Provenance
    lane_panels: tuple[BasinLanePanel, ...] = field(default_factory=tuple)
    last_admission_before: timedelta | None = None


def _feature_status(
    facility: Facility, feature: Feature, at_local: datetime, calendar: ZurichCalendar
) -> FeatureStatus:
    if not feature.hours:
        return FeatureStatus(feature=feature, schedule=None, open_at_query_time=None)
    schedule = resolve_hours(facility, feature.hours, (), at_local.date(), calendar)
    open_now: bool | None
    match schedule:
        case OpenDay(sessions):
            open_now = any(s.time.contains(at_local.time()) for s in sessions)
        case ClosedDay():
            open_now = False
        case OpenUnscheduledDay():
            # Only reachable if a season-carrying facility's feature had rule-less hours —
            # impossible today (`feature.hours` is non-empty above), but the honest answer
            # would be "open, hours unpublished": unknown at this instant, never closed.
            open_now = None
        case _ as unreachable:
            assert_never(unreachable)
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
        basins=facility.basins,
        features=tuple(_feature_status(facility, f, at_local, calendar) for f in facility.features),
        lockers=facility.lockers,
        rentals=facility.rentals,
        provenance=facility.provenance,
        lane_panels=lane_panels,
        last_admission_before=facility.last_admission_before,
    )


_FRESHNESS_STATUS_CODE: dict[ScheduleFreshness, StatusCode] = {
    ScheduleFreshness.AWAITING_SCRAPE: StatusCode.AWAITING_SCRAPE,
    ScheduleFreshness.NO_SOURCE: StatusCode.NO_SOURCE,
}


def _schedule_less_statuses(
    facilities: tuple[Facility, ...], roster: tuple[RosterEntry, ...]
) -> list[FacilityStatus]:
    """`schedule-less = roster − scheduled`: every roster pool whose canonical id is not among the
    facilities resolved this query. Identity is known (the roster), the schedule is not — so it
    carries its `ScheduleFreshness` (`awaiting_scrape` / `no_source`), distinct from a pool that is
    `closed` today. A schedule-less pool is NEVER reported "closed".

    "Scheduled" is a facility carrying at least one basin with a schedule rule — NOT merely a
    facility_doc: a prose-only pool (auto-extracted PARSED_PROSE basins, no rules — Decision #5)
    has a facility_doc but no schedule, so it stays schedule-less here, never silently dropped.
    Its `freshness` is thus `awaiting_scrape` or `no_source` (never `scraped`), so the status
    string is the freshness value and the code mirrors it.

    A facility carrying an `operating_season` is ALSO excluded (sharedsource-fanout S1): its
    seasonal path already reported it (`open_unscheduled` / `closed`), and the two statuses are
    exclusive — the facility appears exactly once per query, never also as a `no_source` ghost.
    (`ScheduleFreshness` itself is untouched: the season is not a timetable, so the pool's
    `/pools` freshness stays `no_source` — the honest answer about its SCHEDULE.)"""
    scheduled_ids = {
        str(f.identity.facility_id)
        for f in facilities
        if any(basin.rules for basin in f.basins) or f.operating_season is not None
    }
    return [
        FacilityStatus(
            facility_id=reconstruct_pool_id(row.entry.pool_id),
            facility_name=row.entry.name,
            status=row.freshness.value,
            code=_FRESHNESS_STATUS_CODE[row.freshness],
        )
        for row in roster
        if row.entry.pool_id not in scheduled_ids and row.freshness is not ScheduleFreshness.SCRAPED
    ]
