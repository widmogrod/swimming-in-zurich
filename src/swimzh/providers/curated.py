"""The curated-data provider: loads hand-authored YAML into the domain.

Curated YAML is a first-class provider — the same `Result[..., ProviderError]` contract as
any network adapter. For v1 it is the *only* source of schedules/prices (we deliberately do
not scrape), so it is where the product's accuracy lives. Every facility carries provenance
(`valid_as_of`, `curated=True`) so downstream answers can be honest about freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import assert_never

import yaml
from pydantic import ValidationError

from swimzh.boundary.curated_dto import (
    AccessDTO,
    BasinDTO,
    CalendarDTO,
    ClubReservedDTO,
    FacilityDTO,
    FamilyDTO,
    LaneSwimDTO,
    PublicDTO,
    RegistryDTO,
    RuleDTO,
    SchoolReservedDTO,
    SeniorsOnlyDTO,
    WomenOnlyDTO,
)
from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.access import (
    ClubReserved,
    FamilyTime,
    LaneSwim,
    PublicSwim,
    SchoolReserved,
    SeniorsOnly,
    SessionAccess,
    WomenOnly,
)
from swimzh.domain.calendar import HolidayRange, ZurichCalendar
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.registry import Registry
from swimzh.domain.schedule import (
    ClosureRange,
    DayScope,
    HolidayPolicy,
    ResolvedSession,
    ScheduleException,
    ScheduleRule,
    TimeRange,
    Weekday,
)

_SOURCE = "curated"

_WEEKDAYS: dict[str, Weekday] = {
    "mon": Weekday.MONDAY,
    "tue": Weekday.TUESDAY,
    "wed": Weekday.WEDNESDAY,
    "thu": Weekday.THURSDAY,
    "fri": Weekday.FRIDAY,
    "sat": Weekday.SATURDAY,
    "sun": Weekday.SUNDAY,
}
_SCOPES: dict[str, DayScope] = {
    "always": DayScope.ALWAYS,
    "school_term": DayScope.SCHOOL_TERM,
    "school_holiday": DayScope.SCHOOL_HOLIDAY,
}
_POLICIES: dict[str, HolidayPolicy] = {
    "normal": HolidayPolicy.NORMAL,
    "sunday_schedule": HolidayPolicy.SUNDAY_SCHEDULE,
    "closed": HolidayPolicy.CLOSED,
}
_KINDS: dict[str, PoolKind] = {
    "indoor": PoolKind.INDOOR,
    "thermal": PoolKind.THERMAL,
    "school": PoolKind.SCHOOL,
}
_CATEGORIES: dict[str, PriceCategory] = {
    "child": PriceCategory.CHILD,
    "youth": PriceCategory.YOUTH,
    "adult": PriceCategory.ADULT,
    "senior": PriceCategory.SENIOR,
}


@dataclass(frozen=True, slots=True)
class Dataset:
    """Everything the query surface needs, loaded and cross-checked."""

    calendar: ZurichCalendar
    registry: Registry
    facilities: tuple[Facility, ...]


class _CuratedError(Exception):
    """Internal: carries a ProviderError so mapping code can raise and be caught once."""

    def __init__(self, error: ProviderError) -> None:
        super().__init__()
        self.error = error


def _load_yaml(path: Path) -> object:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _CuratedError(
            ParseError(source=_SOURCE, detail=f"cannot read {path}: {exc}", raw_snippet="")
        ) from exc
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise _CuratedError(
            ParseError(
                source=_SOURCE, detail=f"invalid YAML in {path}: {exc}", raw_snippet=raw[:200]
            )
        ) from exc


def _validate[T](model: type[T], data: object, where: str) -> T:
    from pydantic import TypeAdapter

    try:
        return TypeAdapter(model).validate_python(data)
    except ValidationError as exc:
        raise _CuratedError(SchemaMismatch(source=_SOURCE, detail=f"{where}: {exc}")) from exc


def _map_access(dto: AccessDTO) -> SessionAccess:
    match dto:
        case PublicDTO():
            return PublicSwim()
        case LaneSwimDTO(note=note):
            return LaneSwim(note=note)
        case FamilyDTO(note=note):
            return FamilyTime(note=note)
        case WomenOnlyDTO(note=note):
            return WomenOnly(note=note)
        case SeniorsOnlyDTO(min_age=min_age):
            return SeniorsOnly(min_age=min_age)
        case SchoolReservedDTO():
            return SchoolReserved()
        case ClubReservedDTO(club=club):
            return ClubReserved(club=club)
        case _ as unreachable:
            assert_never(unreachable)


def _time_range(start: time, end: time, where: str) -> TimeRange:
    try:
        return TimeRange(start=start, end=end)
    except ValueError as exc:
        raise _CuratedError(SchemaMismatch(source=_SOURCE, detail=f"{where}: {exc}")) from exc


def _map_rule(dto: RuleDTO, where: str) -> ScheduleRule:
    return ScheduleRule(
        weekdays=frozenset(_WEEKDAYS[w] for w in dto.weekdays),
        time=_time_range(dto.start, dto.end, where),
        access=_map_access(dto.access),
        scope=_SCOPES[dto.scope],
    )


def _map_basin(dto: BasinDTO, facility_id: str) -> Basin:
    where = f"{facility_id}/{dto.basin_id}"
    rules = tuple(_map_rule(r, where) for r in dto.rules)
    exceptions = tuple(
        ScheduleException(
            date=e.date,
            closed=e.closed,
            reason=e.reason,
            sessions=tuple(
                ResolvedSession(
                    time=_time_range(s.start, s.end, where), access=_map_access(s.access)
                )
                for s in e.sessions
            ),
        )
        for e in dto.exceptions
    )
    return Basin(
        basin_id=BasinId(dto.basin_id),
        name=dto.name,
        rules=rules,
        exceptions=exceptions,
        length_m=dto.length_m,
    )


def _map_prices(dto: FacilityDTO) -> PriceTable | None:
    if dto.prices is None:
        return None
    entries = tuple(
        PriceEntry(category=_CATEGORIES[e.category], amount_chf=e.amount_chf, display=e.display)
        for e in dto.prices.entries
    )
    return PriceTable(
        entries=entries, valid_as_of=dto.prices.valid_as_of, source_url=dto.prices.source_url
    )


def _map_facility(dto: FacilityDTO, identity: PoolIdentity) -> Facility:
    from swimzh.domain.geo import GeoPoint

    geo = GeoPoint(lat=dto.geo.lat, lon=dto.geo.lon) if dto.geo is not None else None
    closures = tuple(ClosureRange(start=c.start, end=c.end, reason=c.reason) for c in dto.closures)
    return Facility(
        identity=identity,
        address=dto.address,
        provenance=Provenance(source=dto.source, curated=True, valid_as_of=dto.valid_as_of),
        basins=tuple(_map_basin(b, dto.facility_id) for b in dto.basins),
        geo=geo,
        amenities=frozenset(dto.amenities),
        closures=closures,
        public_holiday_policy=_POLICIES[dto.public_holiday_policy],
        prices=_map_prices(dto),
    )


def _build_calendar(dto: CalendarDTO) -> ZurichCalendar:
    return ZurichCalendar(
        public_holidays={h.date: h.name for h in dto.public_holidays},
        school_holidays=[
            HolidayRange(name=r.name, start=r.start, end=r.end) for r in dto.school_holidays
        ],
        known_years=dto.known_years,
    )


def _build_registry(dto: RegistryDTO) -> Registry:
    identities = [
        PoolIdentity(
            facility_id=FacilityId(i.facility_id),
            name=i.name,
            kind=_KINDS[i.kind],
            geo_sport_id=i.geo_sport_id,
            crowdmonitor_keys=tuple(i.crowdmonitor_keys),
            aliases=tuple(i.aliases),
        )
        for i in dto.facilities
    ]
    try:
        return Registry(identities)
    except ValueError as exc:
        raise _CuratedError(SchemaMismatch(source=_SOURCE, detail=f"registry: {exc}")) from exc


def load_dataset(data_dir: Path) -> Result[Dataset, ProviderError]:
    """Load calendar + registry + all pool files under `data_dir` into a `Dataset`."""
    try:
        calendar_dto = _validate(
            CalendarDTO, _load_yaml(data_dir / "calendar" / "zurich.yaml"), "calendar"
        )
        registry_dto = _validate(RegistryDTO, _load_yaml(data_dir / "registry.yaml"), "registry")
        registry = _build_registry(registry_dto)

        facilities: list[Facility] = []
        for pool_path in sorted((data_dir / "pools").glob("*.yaml")):
            facility_dto = _validate(FacilityDTO, _load_yaml(pool_path), pool_path.name)
            identity = registry.get(FacilityId(facility_dto.facility_id))
            if identity is None:
                # Intentional raise-and-catch: _CuratedError is the internal channel that
                # the outer handler converts into a Result. This is the provider boundary.
                raise _CuratedError(  # noqa: TRY301
                    SchemaMismatch(
                        source=_SOURCE,
                        detail=f"{pool_path.name}: facility_id "
                        f"{facility_dto.facility_id!r} not in registry",
                    )
                )
            facilities.append(_map_facility(facility_dto, identity))
    except _CuratedError as exc:
        return Err(exc.error)

    return Ok(
        Dataset(
            calendar=_build_calendar(calendar_dto), registry=registry, facilities=tuple(facilities)
        )
    )
