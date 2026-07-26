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
    AdultsOnlyDTO,
    BasinDTO,
    ClosureDTO,
    ClubReservedDTO,
    ConnectionFailedDTO,
    DecodeErrorDTO,
    DimensionsDTO,
    ExceptionDTO,
    FamilyDTO,
    FeatureDTO,
    GeoDTO,
    HttpStatusDTO,
    LanePlanDTO,
    LanePlanSourceDTO,
    LanePlanUnavailableDTO,
    LaneReservationDTO,
    LaneSwimDTO,
    LockerOptionDTO,
    ParseErrorDTO,
    PlanCoverageDTO,
    PriceEntryDTO,
    PriceTableDTO,
    ProviderErrorDTO,
    ProviderSpecificDTO,
    PublicDTO,
    RateLimitedDTO,
    RedirectDTO,
    ResolvedSessionDTO,
    RuleDTO,
    SchemaMismatchDTO,
    SchoolReservedDTO,
    SeniorsOnlyDTO,
    TimeoutDTO,
    TooLargeDTO,
    WomenOnlyDTO,
    _BasinKind,
    _BasinSource,
    _FeatureKind,
    _LockerCategory,
    _LockerMechanism,
    _PlanConfidence,
    _PriceCategory,
    _Scope,
    _Weekday,
)
from swimzh.core.errors import (
    ConnectionFailed,
    DecodeError,
    HttpStatus,
    ParseError,
    ProviderError,
    ProviderSpecific,
    RateLimited,
    Redirect,
    SchemaMismatch,
    Timeout,
    TooLarge,
)
from swimzh.domain.access import (
    AdultsOnly,
    ClubReserved,
    FamilyTime,
    LaneSwim,
    PublicSwim,
    SchoolReserved,
    SeniorsOnly,
    SessionAccess,
    WomenOnly,
)
from swimzh.domain.closure import classify_closure
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import (
    LanePlan,
    LaneReservation,
    PlanConfidence,
    PlanCoverage,
)
from swimzh.domain.lockers import LockerCategory, LockerMechanism, LockerOption
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    BasinSource,
    Dimensions,
    Feature,
    FeatureKind,
    LanePlanSource,
    LanePlanUnavailable,
)
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
_BASIN_KIND_FROM: dict[str, BasinKind] = {k.value: k for k in BasinKind}
_BASIN_KIND_TO: dict[BasinKind, _BasinKind] = {
    BasinKind.LAP: "lap",
    BasinKind.NON_SWIMMER: "non_swimmer",
    BasinKind.DIVING: "diving",
    BasinKind.VARIO: "vario",
    BasinKind.TEACHING: "teaching",
    BasinKind.CHILDREN: "children",
    BasinKind.OUTDOOR: "outdoor",
    BasinKind.OTHER: "other",
}
_BASIN_SOURCE_FROM: dict[str, BasinSource] = {s.value: s for s in BasinSource}
_BASIN_SOURCE_TO: dict[BasinSource, _BasinSource] = {
    BasinSource.CURATED: "curated",
    BasinSource.PARSED_PROSE: "parsed_prose",
}
_PLAN_CONFIDENCE_FROM: dict[str, PlanConfidence] = {c.value: c for c in PlanConfidence}
_PLAN_CONFIDENCE_TO: dict[PlanConfidence, _PlanConfidence] = {
    PlanConfidence.COMPLETE: "complete",
    PlanConfidence.PARTIAL: "partial",
}
_FEATURE_KIND_FROM: dict[str, FeatureKind] = {k.value: k for k in FeatureKind}
_FEATURE_KIND_TO: dict[FeatureKind, _FeatureKind] = {
    FeatureKind.SAUNA: "sauna",
    FeatureKind.STEAM_BATH: "steam_bath",
    FeatureKind.WELLNESS: "wellness",
    FeatureKind.SLIDE: "slide",
    FeatureKind.HOT_TUB: "hot_tub",
    FeatureKind.TERRACE: "terrace",
    FeatureKind.REST: "rest",
    FeatureKind.GASTRONOMY: "gastronomy",
}
_LOCKER_CATEGORY_FROM: dict[str, LockerCategory] = {c.value: c for c in LockerCategory}
_LOCKER_CATEGORY_TO: dict[LockerCategory, _LockerCategory] = {
    LockerCategory.WARDROBE: "wardrobe",
    LockerCategory.VALUABLES: "valuables",
    LockerCategory.LAUNDRY: "laundry",
}
_LOCKER_MECHANISM_FROM: dict[str, LockerMechanism] = {m.value: m for m in LockerMechanism}
_LOCKER_MECHANISM_TO: dict[LockerMechanism, _LockerMechanism] = {
    LockerMechanism.COIN: "coin",
    LockerMechanism.KEY: "key",
    LockerMechanism.CHIP: "chip",
    LockerMechanism.WRISTBAND: "wristband",
    LockerMechanism.OTHER: "other",
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
        case AdultsOnlyDTO(min_age=min_age, note=note):
            return AdultsOnly(min_age=min_age, note=note)
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
        case AdultsOnly(min_age, note):
            return AdultsOnlyDTO(type="adults_only", min_age=min_age, note=note)
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
    # Classify the curated German HERE — on the way in, at build time. The query layer
    # must never parse prose; by the time it reads the gold store the code is settled.
    code, params = classify_closure(dto.reason)
    return ScheduleException(
        date=dto.date,
        closed=dto.closed,
        reason=dto.reason,
        code=code,
        params=params,
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
    code, params = classify_closure(dto.reason)
    return ClosureRange(start=dto.start, end=dto.end, reason=dto.reason, code=code, params=params)


def closure_to_dto(closure: ClosureRange) -> ClosureDTO:
    return ClosureDTO(start=closure.start, end=closure.end, reason=closure.reason)


def dimensions_from_dto(dto: DimensionsDTO) -> Dimensions:
    return Dimensions(length_m=dto.length_m, width_m=dto.width_m)


def dimensions_to_dto(dims: Dimensions) -> DimensionsDTO:
    return DimensionsDTO(length_m=dims.length_m, width_m=dims.width_m)


# --- ProviderError (lossless closed-union codec) ------------------------------------


def provider_error_to_dto(error: ProviderError) -> ProviderErrorDTO:
    match error:
        case Timeout(url, after_s):
            return TimeoutDTO(type="timeout", url=url, after_s=after_s)
        case ConnectionFailed(url, detail):
            return ConnectionFailedDTO(type="connection_failed", url=url, detail=detail)
        case HttpStatus(url, status, body_snippet):
            return HttpStatusDTO(
                type="http_status", url=url, status=status, body_snippet=body_snippet
            )
        case RateLimited(url, retry_after_s):
            return RateLimitedDTO(type="rate_limited", url=url, retry_after_s=retry_after_s)
        case DecodeError(source, detail):
            return DecodeErrorDTO(type="decode_error", source=source, detail=detail)
        case ParseError(source, detail, raw_snippet):
            return ParseErrorDTO(
                type="parse_error", source=source, detail=detail, raw_snippet=raw_snippet
            )
        case SchemaMismatch(source, detail):
            return SchemaMismatchDTO(type="schema_mismatch", source=source, detail=detail)
        case TooLarge(url, limit_bytes):
            return TooLargeDTO(type="too_large", url=url, limit_bytes=limit_bytes)
        case Redirect(url, location, count):
            return RedirectDTO(type="redirect", url=url, location=location, count=count)
        case ProviderSpecific(provider, detail):
            return ProviderSpecificDTO(type="provider_specific", provider=provider, detail=detail)
        case _ as unreachable:
            assert_never(unreachable)


def provider_error_from_dto(dto: ProviderErrorDTO) -> ProviderError:
    match dto:
        case TimeoutDTO(url=url, after_s=after_s):
            return Timeout(url=url, after_s=after_s)
        case ConnectionFailedDTO(url=url, detail=detail):
            return ConnectionFailed(url=url, detail=detail)
        case HttpStatusDTO(url=url, status=status, body_snippet=body_snippet):
            return HttpStatus(url=url, status=status, body_snippet=body_snippet)
        case RateLimitedDTO(url=url, retry_after_s=retry_after_s):
            return RateLimited(url=url, retry_after_s=retry_after_s)
        case DecodeErrorDTO(source=source, detail=detail):
            return DecodeError(source=source, detail=detail)
        case ParseErrorDTO(source=source, detail=detail, raw_snippet=raw_snippet):
            return ParseError(source=source, detail=detail, raw_snippet=raw_snippet)
        case SchemaMismatchDTO(source=source, detail=detail):
            return SchemaMismatch(source=source, detail=detail)
        case TooLargeDTO(url=url, limit_bytes=limit_bytes):
            return TooLarge(url=url, limit_bytes=limit_bytes)
        case RedirectDTO(url=url, location=location, count=count):
            return Redirect(url=url, location=location, count=count)
        case ProviderSpecificDTO(provider=provider, detail=detail):
            return ProviderSpecific(provider=provider, detail=detail)
        case _ as unreachable:
            assert_never(unreachable)


# --- lane reservations (Belegungsplan) ----------------------------------------------


def lane_plan_source_from_dto(dto: LanePlanSourceDTO) -> LanePlanSource:
    return LanePlanSource(url=dto.url, section=dto.section)


def lane_plan_source_to_dto(source: LanePlanSource) -> LanePlanSourceDTO:
    return LanePlanSourceDTO(url=source.url, section=source.section)


def lane_plan_unavailable_from_dto(dto: LanePlanUnavailableDTO) -> LanePlanUnavailable:
    return LanePlanUnavailable(
        source_url=dto.source_url,
        section=dto.section,
        cause=provider_error_from_dto(dto.cause),
        observed_at=dto.observed_at,
    )


def lane_plan_unavailable_to_dto(unavailable: LanePlanUnavailable) -> LanePlanUnavailableDTO:
    return LanePlanUnavailableDTO(
        source_url=unavailable.source_url,
        section=unavailable.section,
        cause=provider_error_to_dto(unavailable.cause),
        observed_at=unavailable.observed_at,
    )


def lane_reservation_from_dto(dto: LaneReservationDTO) -> LaneReservation:
    return LaneReservation(
        weekdays=frozenset(_WEEKDAY_FROM[w] for w in dto.weekdays),
        time=time_range(dto.start, dto.end),
        lanes=frozenset(dto.lanes),
        access=access_from_dto(dto.access),
        section=dto.section,
    )


def lane_reservation_to_dto(reservation: LaneReservation) -> LaneReservationDTO:
    return LaneReservationDTO(
        weekdays=[_WEEKDAY_TO[w] for w in sorted(reservation.weekdays)],
        start=reservation.time.start,
        end=reservation.time.end,
        lanes=sorted(reservation.lanes),
        access=access_to_dto(reservation.access),
        section=reservation.section,
    )


def plan_coverage_from_dto(dto: PlanCoverageDTO) -> PlanCoverage:
    return PlanCoverage(
        confidence=_PLAN_CONFIDENCE_FROM[dto.confidence],
        cells_total=dto.cells_total,
        cells_resolved=dto.cells_resolved,
        unresolved_lanes=frozenset(dto.unresolved_lanes),
    )


def plan_coverage_to_dto(coverage: PlanCoverage) -> PlanCoverageDTO:
    return PlanCoverageDTO(
        confidence=_PLAN_CONFIDENCE_TO[coverage.confidence],
        cells_total=coverage.cells_total,
        cells_resolved=coverage.cells_resolved,
        unresolved_lanes=sorted(coverage.unresolved_lanes),
    )


def lane_plan_from_dto(dto: LanePlanDTO) -> LanePlan:
    return LanePlan(
        lane_count=dto.lane_count,
        reservations=tuple(lane_reservation_from_dto(r) for r in dto.reservations),
        valid_from=dto.valid_from,
        coverage=plan_coverage_from_dto(dto.coverage),
        fetched_at=dto.fetched_at,
        lanes_by_weekday=(
            {_WEEKDAY_FROM[w]: n for w, n in dto.lanes_by_weekday.items()}
            if dto.lanes_by_weekday is not None
            else None
        ),
    )


def lane_plan_to_dto(plan: LanePlan) -> LanePlanDTO:
    return LanePlanDTO(
        lane_count=plan.lane_count,
        reservations=[lane_reservation_to_dto(r) for r in plan.reservations],
        valid_from=plan.valid_from,
        coverage=plan_coverage_to_dto(plan.coverage),
        fetched_at=plan.fetched_at,
        lanes_by_weekday=(
            # Serialise in weekday order so a set map has one canonical, stable form.
            {_WEEKDAY_TO[w]: plan.lanes_by_weekday[w] for w in sorted(plan.lanes_by_weekday)}
            if plan.lanes_by_weekday is not None
            else None
        ),
    )


def _basin_lane_plan_from_dto(
    dto: LanePlanDTO | LanePlanUnavailableDTO | None,
) -> LanePlan | LanePlanUnavailable | None:
    match dto:
        case None:
            return None
        case LanePlanUnavailableDTO():
            return lane_plan_unavailable_from_dto(dto)
        case LanePlanDTO():
            return lane_plan_from_dto(dto)


def _basin_lane_plan_to_dto(
    lane_plan: LanePlan | LanePlanUnavailable | None,
) -> LanePlanDTO | LanePlanUnavailableDTO | None:
    match lane_plan:
        case None:
            return None
        case LanePlanUnavailable():
            return lane_plan_unavailable_to_dto(lane_plan)
        case LanePlan():
            return lane_plan_to_dto(lane_plan)


def basin_from_dto(dto: BasinDTO) -> Basin:
    return Basin(
        basin_id=BasinId(dto.basin_id),
        name=dto.name,
        rules=tuple(rule_from_dto(r) for r in dto.rules),
        exceptions=tuple(exception_from_dto(e) for e in dto.exceptions),
        kind=_BASIN_KIND_FROM[dto.kind],
        dimensions=dimensions_from_dto(dto.dimensions) if dto.dimensions is not None else None,
        lanes=dto.lanes,
        nominal_temp_c=dto.nominal_temp_c,
        measured_temp_c=dto.measured_temp_c,
        diving_platforms_m=tuple(dto.diving_platforms_m),
        physical_source=_BASIN_SOURCE_FROM[dto.physical_source],
        lane_plan_source=(
            lane_plan_source_from_dto(dto.lane_plan_source)
            if dto.lane_plan_source is not None
            else None
        ),
        lane_plan=_basin_lane_plan_from_dto(dto.lane_plan),
    )


def basin_to_dto(basin: Basin) -> BasinDTO:
    return BasinDTO(
        basin_id=str(basin.basin_id),
        name=basin.name,
        rules=[rule_to_dto(r) for r in basin.rules],
        exceptions=[exception_to_dto(e) for e in basin.exceptions],
        kind=_BASIN_KIND_TO[basin.kind],
        dimensions=dimensions_to_dto(basin.dimensions) if basin.dimensions is not None else None,
        lanes=basin.lanes,
        nominal_temp_c=basin.nominal_temp_c,
        measured_temp_c=basin.measured_temp_c,
        diving_platforms_m=list(basin.diving_platforms_m),
        physical_source=_BASIN_SOURCE_TO[basin.physical_source],
        lane_plan_source=(
            lane_plan_source_to_dto(basin.lane_plan_source)
            if basin.lane_plan_source is not None
            else None
        ),
        lane_plan=_basin_lane_plan_to_dto(basin.lane_plan),
    )


# --- features & lockers -------------------------------------------------------------


def feature_from_dto(dto: FeatureDTO) -> Feature:
    return Feature(
        kind=_FEATURE_KIND_FROM[dto.kind],
        name=dto.name,
        hours=tuple(rule_from_dto(r) for r in dto.hours),
        surcharge_chf=dto.surcharge_chf,
        temp_c=dto.temp_c,
        note=dto.note,
    )


def feature_to_dto(feature: Feature) -> FeatureDTO:
    return FeatureDTO(
        kind=_FEATURE_KIND_TO[feature.kind],
        name=feature.name,
        hours=[rule_to_dto(r) for r in feature.hours],
        surcharge_chf=feature.surcharge_chf,
        temp_c=feature.temp_c,
        note=feature.note,
    )


def locker_from_dto(dto: LockerOptionDTO) -> LockerOption:
    return LockerOption(
        category=_LOCKER_CATEGORY_FROM[dto.category],
        fee_chf=dto.fee_chf,
        deposit_chf=dto.deposit_chf,
        period=dto.period,
        mechanism=_LOCKER_MECHANISM_FROM[dto.mechanism] if dto.mechanism is not None else None,
        raw=dto.raw,
    )


def locker_to_dto(locker: LockerOption) -> LockerOptionDTO:
    return LockerOptionDTO(
        category=_LOCKER_CATEGORY_TO[locker.category],
        fee_chf=locker.fee_chf,
        deposit_chf=locker.deposit_chf,
        period=locker.period,
        mechanism=_LOCKER_MECHANISM_TO[locker.mechanism] if locker.mechanism is not None else None,
        raw=locker.raw,
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
