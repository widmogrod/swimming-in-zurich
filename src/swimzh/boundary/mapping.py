"""Bidirectional mapping between boundary DTOs and the frozen-dataclass domain.

Both directions live here so there is a single source of truth for the shape:
  * `*_from_dto` — used when loading curated YAML and when decoding the gold store.
  * `*_to_dto`   — used when serialising the domain into the gold store.

Domain construction may raise `ValueError` (e.g. an invalid `TimeRange`); callers that
turn failures into `Result` values catch it at their boundary.
"""

from __future__ import annotations

from datetime import time
from typing import assert_never

from swimzh.boundary.curated_dto import (
    AccessDTO,
    BasinDTO,
    ClosureDTO,
    ClubReservedDTO,
    ExceptionDTO,
    FamilyDTO,
    GeoDTO,
    LaneSwimDTO,
    PriceEntryDTO,
    PriceTableDTO,
    PublicDTO,
    ResolvedSessionDTO,
    RuleDTO,
    SchoolReservedDTO,
    SeniorsOnlyDTO,
    WomenOnlyDTO,
    _PriceCategory,
    _Scope,
    _Weekday,
)
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
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import Basin, BasinId
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable
from swimzh.domain.schedule import (
    ClosureRange,
    DayScope,
    ResolvedSession,
    ScheduleException,
    ScheduleRule,
    TimeRange,
    Weekday,
)

# --- token tables (both directions) -------------------------------------------------

_WEEKDAY_FROM: dict[_Weekday, Weekday] = {
    "mon": Weekday.MONDAY,
    "tue": Weekday.TUESDAY,
    "wed": Weekday.WEDNESDAY,
    "thu": Weekday.THURSDAY,
    "fri": Weekday.FRIDAY,
    "sat": Weekday.SATURDAY,
    "sun": Weekday.SUNDAY,
}
_WEEKDAY_TO: dict[Weekday, _Weekday] = {v: k for k, v in _WEEKDAY_FROM.items()}

_SCOPE_FROM: dict[str, DayScope] = {s.value: s for s in DayScope}
_SCOPE_TO: dict[DayScope, _Scope] = {
    DayScope.ALWAYS: "always",
    DayScope.SCHOOL_TERM: "school_term",
    DayScope.SCHOOL_HOLIDAY: "school_holiday",
}
_CATEGORY_FROM: dict[str, PriceCategory] = {c.value: c for c in PriceCategory}
_CATEGORY_TO: dict[PriceCategory, _PriceCategory] = {
    PriceCategory.CHILD: "child",
    PriceCategory.YOUTH: "youth",
    PriceCategory.ADULT: "adult",
    PriceCategory.SENIOR: "senior",
}


# --- access (tagged union) ----------------------------------------------------------


def access_from_dto(dto: AccessDTO) -> SessionAccess:
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


def access_to_dto(access: SessionAccess) -> AccessDTO:
    match access:
        case PublicSwim():
            return PublicDTO(type="public")
        case LaneSwim(note):
            return LaneSwimDTO(type="lane_swim", note=note)
        case FamilyTime(note):
            return FamilyDTO(type="family", note=note)
        case WomenOnly(note):
            return WomenOnlyDTO(type="women_only", note=note)
        case SeniorsOnly(min_age):
            return SeniorsOnlyDTO(type="seniors_only", min_age=min_age)
        case SchoolReserved():
            return SchoolReservedDTO(type="school_reserved")
        case ClubReserved(club):
            return ClubReservedDTO(type="club_reserved", club=club)
        case _ as unreachable:
            assert_never(unreachable)


# --- schedule pieces ----------------------------------------------------------------


def time_range(start: time, end: time) -> TimeRange:
    return TimeRange(start=start, end=end)


def rule_from_dto(dto: RuleDTO) -> ScheduleRule:
    return ScheduleRule(
        weekdays=frozenset(_WEEKDAY_FROM[w] for w in dto.weekdays),
        time=time_range(dto.start, dto.end),
        access=access_from_dto(dto.access),
        scope=_SCOPE_FROM[dto.scope],
    )


def rule_to_dto(rule: ScheduleRule) -> RuleDTO:
    return RuleDTO(
        weekdays=[_WEEKDAY_TO[w] for w in sorted(rule.weekdays)],
        start=rule.time.start,
        end=rule.time.end,
        access=access_to_dto(rule.access),
        scope=_SCOPE_TO[rule.scope],
    )


def resolved_from_dto(dto: ResolvedSessionDTO) -> ResolvedSession:
    return ResolvedSession(time=time_range(dto.start, dto.end), access=access_from_dto(dto.access))


def resolved_to_dto(session: ResolvedSession) -> ResolvedSessionDTO:
    return ResolvedSessionDTO(
        start=session.time.start, end=session.time.end, access=access_to_dto(session.access)
    )


def exception_from_dto(dto: ExceptionDTO) -> ScheduleException:
    return ScheduleException(
        date=dto.date,
        closed=dto.closed,
        reason=dto.reason,
        sessions=tuple(resolved_from_dto(s) for s in dto.sessions),
    )


def exception_to_dto(exc: ScheduleException) -> ExceptionDTO:
    return ExceptionDTO(
        date=exc.date,
        closed=exc.closed,
        reason=exc.reason,
        sessions=[resolved_to_dto(s) for s in exc.sessions],
    )


def closure_from_dto(dto: ClosureDTO) -> ClosureRange:
    return ClosureRange(start=dto.start, end=dto.end, reason=dto.reason)


def closure_to_dto(closure: ClosureRange) -> ClosureDTO:
    return ClosureDTO(start=closure.start, end=closure.end, reason=closure.reason)


def basin_from_dto(dto: BasinDTO) -> Basin:
    return Basin(
        basin_id=BasinId(dto.basin_id),
        name=dto.name,
        rules=tuple(rule_from_dto(r) for r in dto.rules),
        exceptions=tuple(exception_from_dto(e) for e in dto.exceptions),
        length_m=dto.length_m,
    )


def basin_to_dto(basin: Basin) -> BasinDTO:
    return BasinDTO(
        basin_id=str(basin.basin_id),
        name=basin.name,
        rules=[rule_to_dto(r) for r in basin.rules],
        exceptions=[exception_to_dto(e) for e in basin.exceptions],
        length_m=basin.length_m,
    )


# --- pricing & geo ------------------------------------------------------------------


def price_table_from_dto(dto: PriceTableDTO) -> PriceTable:
    return PriceTable(
        entries=tuple(
            PriceEntry(
                category=_CATEGORY_FROM[e.category], amount_chf=e.amount_chf, display=e.display
            )
            for e in dto.entries
        ),
        valid_as_of=dto.valid_as_of,
        source_url=dto.source_url,
    )


def price_table_to_dto(table: PriceTable) -> PriceTableDTO:
    return PriceTableDTO(
        entries=[
            PriceEntryDTO(
                category=_CATEGORY_TO[e.category], amount_chf=e.amount_chf, display=e.display
            )
            for e in table.entries
        ],
        valid_as_of=table.valid_as_of,
        source_url=table.source_url,
    )


def geo_from_dto(dto: GeoDTO) -> GeoPoint:
    return GeoPoint(lat=dto.lat, lon=dto.lon)


def geo_to_dto(geo: GeoPoint) -> GeoDTO:
    return GeoDTO(lat=geo.lat, lon=geo.lon)
