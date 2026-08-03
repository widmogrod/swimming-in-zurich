"""The curated-data provider: loads the thin-crosswalk YAML into the domain.

Curated YAML is a first-class provider — the same `Result[..., ProviderError]` contract as
any network adapter. Post-strip it is a **thin crosswalk** (`facility_id` + basins carrying only
`lane_plan_source`), not a source of schedules/prices/physicals: those are all sourced (WFS
roster + page/price/notice scrapers). A loaded facility carries `curated=True` provenance here,
but `build/compose.py` overrides it to `curated=False` once the scraped timetable wins, so a
scraped-schedule pool never reads as hand-verified. `ScheduleFreshness` is the primary freshness
signal downstream.

DTO↔domain mapping lives in `swimzh.boundary.mapping` (shared with the gold codec); this
module handles YAML I/O, validation, and the facility-level assembly that needs the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import CalendarDTO, FacilityDTO, RegistryDTO
from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.calendar import HolidayRange, ZurichCalendar
from swimzh.domain.models import (
    Facility,
    PoolIdentity,
    PoolKind,
    Provenance,
    reconstruct_pool_id,
)
from swimzh.domain.registry import Registry
from swimzh.domain.schedule import HolidayPolicy

_SOURCE = "curated"

_POLICIES: dict[str, HolidayPolicy] = {p.value: p for p in HolidayPolicy}
_KINDS: dict[str, PoolKind] = {k.value: k for k in PoolKind}


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
    try:
        return TypeAdapter(model).validate_python(data)
    except ValidationError as exc:
        raise _CuratedError(SchemaMismatch(source=_SOURCE, detail=f"{where}: {exc}")) from exc


def _map_facility(dto: FacilityDTO, identity: PoolIdentity) -> Facility:
    # `address`/`source` are optional since S1 (a stripped pool file omits them). This provider
    # has NO roster, so it cannot source the address here — it leaves an empty sentinel that the
    # build/seed path (`build_spine`) overwrites with the WFS roster's `entry.address` before the
    # blob is serialized (never a served ""). `source` falls back to the build-assigned `_SOURCE`.
    return Facility(
        identity=identity,
        address=dto.address or "",
        provenance=Provenance(
            source=dto.source or _SOURCE, curated=True, valid_as_of=dto.valid_as_of
        ),
        basins=tuple(mapping.basin_from_dto(b) for b in dto.basins),
        geo=mapping.geo_from_dto(dto.geo) if dto.geo is not None else None,
        closures=tuple(mapping.closure_from_dto(c) for c in dto.closures),
        public_holiday_policy=(
            _POLICIES[dto.public_holiday_policy] if dto.public_holiday_policy is not None else None
        ),
        prices=mapping.price_table_from_dto(dto.prices) if dto.prices is not None else None,
        features=tuple(mapping.feature_from_dto(f) for f in dto.features),
        lockers=tuple(mapping.locker_from_dto(lo) for lo in dto.lockers),
        last_admission_before=dto.last_admission_before,
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
            facility_id=reconstruct_pool_id(i.facility_id),
            name=i.name,
            kind=_KINDS[i.kind],
            # `geo_sport_id` is left at its domain default (`None`) here: it is no longer read from
            # the registry crosswalk but SOURCED from the WFS `poi_id` in `build_spine` (S5b).
            crowdmonitor_keys=tuple(i.crowdmonitor_keys),
            baditicker_poiid=i.baditicker_poiid,
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
            identity = registry.get(reconstruct_pool_id(facility_dto.facility_id))
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
    except ValueError as exc:
        # Domain construction (e.g. an invalid TimeRange) rejected the validated data.
        return Err(SchemaMismatch(source=_SOURCE, detail=str(exc)))

    return Ok(
        Dataset(
            calendar=_build_calendar(calendar_dto),
            registry=registry,
            facilities=tuple(facilities),
        )
    )
