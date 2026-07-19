"""The query surface: `find_swim_options` — the library's public answer to
"where can I swim?"

Given a person, a moment (now or future), and optionally a location + radius, it resolves
every curated facility's schedule for that date and returns concrete options, each annotated
with *explainable* eligibility, price, distance, and provenance.

It deliberately distinguishes three outcomes so an empty answer is never ambiguous:
  * an option (open, with eligibility),
  * a facility that is **closed** that day (with reason), and
  * a facility whose schedule is **not yet curated** (unknown, via the registry) —
    never conflated with "closed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from swimzh.domain.access import EligibilityResult, eligibility
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.geo import GeoPoint, haversine_km
from swimzh.domain.lockers import LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    FacilityId,
    Feature,
    Occupancy,
    Provenance,
)
from swimzh.domain.person import Person
from swimzh.domain.pricing import PriceEntry, price_for
from swimzh.domain.registry import Registry
from swimzh.domain.resolver import resolve_basin, resolve_hours
from swimzh.domain.schedule import ClosedDay, DaySchedule, OpenDay, ResolvedSession

_ZURICH = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True, slots=True)
class SwimQuery:
    person: Person
    at: datetime
    near: GeoPoint | None = None
    radius_km: float | None = None


@dataclass(frozen=True, slots=True)
class SwimOption:
    facility_id: FacilityId
    facility_name: str
    basin_id: BasinId
    basin_name: str
    basin_kind: BasinKind
    lanes: int | None
    water_temp_c: Decimal | None  # the basin's nominal (design) temperature, not live
    session: ResolvedSession
    eligibility: EligibilityResult
    open_at_query_time: bool
    price: PriceEntry | None
    distance_km: float | None
    provenance: Provenance
    # Attached only when the query time ≈ now and an occupancy provider is wired (later).
    live_occupancy: Occupancy | None = None


@dataclass(frozen=True, slots=True)
class FacilityStatus:
    """Why a facility produced no options: closed that day, or not yet curated."""

    facility_id: FacilityId
    facility_name: str
    status: str  # "closed" | "uncurated"
    detail: str


@dataclass(frozen=True, slots=True)
class FacilityNotice:
    """A pool alert active on the queried date (e.g. a maintenance closure)."""

    facility_id: FacilityId
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


def find_swim_options(
    query: SwimQuery,
    facilities: tuple[Facility, ...],
    calendar: ZurichCalendar,
    *,
    registry: Registry | None = None,
) -> QueryResult:
    at_local = query.at.astimezone(_ZURICH) if query.at.tzinfo is not None else query.at
    day = at_local.date()
    now_time = at_local.time()

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
        facility_closed_reason: str | None = None
        produced = False

        for basin in facility.basins:
            schedule = resolve_basin(facility, basin, day, calendar)
            match schedule:
                case ClosedDay(reason):
                    facility_closed_reason = reason
                case OpenDay(sessions):
                    for session in sessions:
                        produced = True
                        options.append(
                            SwimOption(
                                facility_id=facility.identity.facility_id,
                                facility_name=facility.identity.name,
                                basin_id=basin.basin_id,
                                basin_name=basin.name,
                                basin_kind=basin.kind,
                                lanes=basin.lanes,
                                water_temp_c=basin.nominal_temp_c,
                                session=session,
                                eligibility=eligibility(query.person, session.access),
                                open_at_query_time=session.time.contains(now_time),
                                price=price,
                                distance_km=distance,
                                provenance=facility.provenance,
                            )
                        )

        if not produced and facility_closed_reason is not None:
            statuses.append(
                FacilityStatus(
                    facility_id=facility.identity.facility_id,
                    facility_name=facility.identity.name,
                    status="closed",
                    detail=facility_closed_reason,
                )
            )

    if registry is not None:
        statuses.extend(_uncurated_statuses(facilities, registry))

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
class FacilityDetail:
    """Facility-level statics for a detail view (`/pools/{id}`-shaped, not per-session):
    website, features (with hours resolved via the schedule resolver), lockers, and the
    basins with their physical attributes."""

    facility_id: FacilityId
    facility_name: str
    address: str
    website: str | None
    basins: tuple[Basin, ...]
    features: tuple[FeatureStatus, ...]
    lockers: tuple[LockerOption, ...]
    provenance: Provenance


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
    return FacilityDetail(
        facility_id=facility.identity.facility_id,
        facility_name=facility.identity.name,
        address=facility.address,
        website=facility.website,
        basins=facility.basins,
        features=tuple(_feature_status(facility, f, at_local, calendar) for f in facility.features),
        lockers=facility.lockers,
        provenance=facility.provenance,
    )


def _uncurated_statuses(
    facilities: tuple[Facility, ...], registry: Registry
) -> list[FacilityStatus]:
    curated_ids = {f.identity.facility_id for f in facilities}
    uncurated: list[FacilityStatus] = []
    for fid, identity in registry.identities.items():
        if fid not in curated_ids:
            uncurated.append(
                FacilityStatus(
                    facility_id=fid,
                    facility_name=identity.name,
                    status="uncurated",
                    detail="schedule not yet curated",
                )
            )
    return uncurated
