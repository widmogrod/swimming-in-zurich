"""Faithful domain <-> JSON codec for the gold store.

A `Facility` is a deeply nested frozen-dataclass tree (basins → rules → tagged-union
access, plus prices, closures, exceptions). Rather than hand-roll JSON, we round-trip it
through a pydantic `StoredFacilityDTO` that reuses the same nested DTOs and shared
`boundary.mapping` as the curated loader — one source of truth for the shape, in both
directions. `dumps(f)` / `loads(s)` are exact inverses (verified by a round-trip test).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import (
    BasinDTO,
    ClosureDTO,
    GeoDTO,
    PriceTableDTO,
    _HolidayPolicy,
    _PoolKind,
)
from swimzh.domain.models import (
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.schedule import HolidayPolicy

_KIND_TO: dict[PoolKind, _PoolKind] = {
    PoolKind.INDOOR: "indoor",
    PoolKind.THERMAL: "thermal",
    PoolKind.SCHOOL: "school",
}
_KIND_FROM: dict[str, PoolKind] = {k.value: k for k in PoolKind}

_POLICY_TO: dict[HolidayPolicy, _HolidayPolicy] = {
    HolidayPolicy.NORMAL: "normal",
    HolidayPolicy.SUNDAY_SCHEDULE: "sunday_schedule",
    HolidayPolicy.CLOSED: "closed",
}
_POLICY_FROM: dict[str, HolidayPolicy] = {p.value: p for p in HolidayPolicy}


class StoredFacilityDTO(BaseModel):
    """The full gold representation of a facility (identity + provenance + schedule tree)."""

    model_config = ConfigDict(extra="forbid")

    facility_id: str
    name: str
    kind: _PoolKind
    address: str
    source: str
    curated: bool
    valid_as_of: date | None
    fetched_at: datetime | None
    geo_sport_id: str | None
    crowdmonitor_keys: list[str]
    aliases: list[str]
    geo: GeoDTO | None
    amenities: list[str]
    public_holiday_policy: _HolidayPolicy
    prices: PriceTableDTO | None
    closures: list[ClosureDTO]
    basins: list[BasinDTO]


def to_stored(facility: Facility) -> StoredFacilityDTO:
    ident = facility.identity
    prov = facility.provenance
    return StoredFacilityDTO(
        facility_id=str(ident.facility_id),
        name=ident.name,
        kind=_KIND_TO[ident.kind],
        address=facility.address,
        source=prov.source,
        curated=prov.curated,
        valid_as_of=prov.valid_as_of,
        fetched_at=prov.fetched_at,
        geo_sport_id=ident.geo_sport_id,
        crowdmonitor_keys=list(ident.crowdmonitor_keys),
        aliases=list(ident.aliases),
        geo=mapping.geo_to_dto(facility.geo) if facility.geo is not None else None,
        amenities=sorted(facility.amenities),
        public_holiday_policy=_POLICY_TO[facility.public_holiday_policy],
        prices=mapping.price_table_to_dto(facility.prices) if facility.prices is not None else None,
        closures=[mapping.closure_to_dto(c) for c in facility.closures],
        basins=[mapping.basin_to_dto(b) for b in facility.basins],
    )


def from_stored(stored: StoredFacilityDTO) -> Facility:
    identity = PoolIdentity(
        facility_id=FacilityId(stored.facility_id),
        name=stored.name,
        kind=_KIND_FROM[stored.kind],
        geo_sport_id=stored.geo_sport_id,
        crowdmonitor_keys=tuple(stored.crowdmonitor_keys),
        aliases=tuple(stored.aliases),
    )
    return Facility(
        identity=identity,
        address=stored.address,
        provenance=Provenance(
            source=stored.source,
            curated=stored.curated,
            valid_as_of=stored.valid_as_of,
            fetched_at=stored.fetched_at,
        ),
        basins=tuple(mapping.basin_from_dto(b) for b in stored.basins),
        geo=mapping.geo_from_dto(stored.geo) if stored.geo is not None else None,
        amenities=frozenset(stored.amenities),
        closures=tuple(mapping.closure_from_dto(c) for c in stored.closures),
        public_holiday_policy=_POLICY_FROM[stored.public_holiday_policy],
        prices=mapping.price_table_from_dto(stored.prices) if stored.prices is not None else None,
    )


def dumps(facility: Facility) -> str:
    return to_stored(facility).model_dump_json()


def loads(payload: str) -> Facility:
    return from_stored(StoredFacilityDTO.model_validate_json(payload))
