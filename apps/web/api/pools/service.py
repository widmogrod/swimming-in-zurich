"""Pools listing use-case: filter the catalog and shape the response."""

from __future__ import annotations

from apps.web.api.pools.model import PoolOut, PoolsOut
from swimzh.domain.catalog import PoolCatalogEntry


def _pool_out(entry: PoolCatalogEntry) -> PoolOut:
    return PoolOut(
        pool_id=entry.pool_id,
        name=entry.name,
        kind=entry.kind.value,
        address=entry.address,
        lat=entry.geo.lat if entry.geo is not None else None,
        lon=entry.geo.lon if entry.geo is not None else None,
        url=entry.url,
        description=entry.description,
        phone=entry.phone,
    )


def list_pools(catalog: tuple[PoolCatalogEntry, ...], kind: str | None) -> PoolsOut:
    items = [e for e in catalog if kind is None or e.kind.value == kind]
    items.sort(key=lambda e: (e.kind.value, e.name))
    kinds = sorted({e.kind.value for e in catalog})
    return PoolsOut(count=len(items), kinds=kinds, pools=[_pool_out(e) for e in items])
