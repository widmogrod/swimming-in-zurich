"""Serialise the pool catalog to/from the committed `data/catalog.json` (generated from the
WFS by `swimzh build-catalog`). A committed artifact so the app lists all pools offline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from swimzh.boundary.curated_dto import _PoolKind
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.storage.codec import _KIND_FROM, _KIND_TO


class _EntryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool_id: str
    name: str
    kind: _PoolKind
    address: str
    lat: float | None
    lon: float | None
    url: str | None
    description: str | None
    phone: str | None


class _CatalogDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generated_at: datetime
    count: int
    entries: list[_EntryDTO]


def _to_dto(entry: PoolCatalogEntry) -> _EntryDTO:
    return _EntryDTO(
        pool_id=entry.pool_id,
        name=entry.name,
        kind=_KIND_TO[entry.kind],
        address=entry.address,
        lat=entry.geo.lat if entry.geo is not None else None,
        lon=entry.geo.lon if entry.geo is not None else None,
        url=entry.url,
        description=entry.description,
        phone=entry.phone,
    )


def _from_dto(dto: _EntryDTO) -> PoolCatalogEntry:
    geo = (
        GeoPoint(lat=dto.lat, lon=dto.lon) if dto.lat is not None and dto.lon is not None else None
    )
    return PoolCatalogEntry(
        pool_id=dto.pool_id,
        name=dto.name,
        kind=_KIND_FROM[dto.kind],
        address=dto.address,
        geo=geo,
        url=dto.url,
        description=dto.description,
        phone=dto.phone,
    )


def dumps(entries: tuple[PoolCatalogEntry, ...], generated_at: datetime) -> str:
    catalog = _CatalogDTO(
        generated_at=generated_at, count=len(entries), entries=[_to_dto(e) for e in entries]
    )
    return catalog.model_dump_json(indent=2)


def loads(text: str) -> tuple[PoolCatalogEntry, ...]:
    catalog = _CatalogDTO.model_validate_json(text)
    return tuple(_from_dto(e) for e in catalog.entries)


def entry_dumps(entry: PoolCatalogEntry) -> str:
    """Serialise a single catalog entry to JSON (one gold-store `catalog` row's `doc`)."""
    return _to_dto(entry).model_dump_json()


def entry_loads(text: str) -> PoolCatalogEntry:
    """Inverse of `entry_dumps`: rehydrate one catalog entry from a stored `doc`."""
    return _from_dto(_EntryDTO.model_validate_json(text))
