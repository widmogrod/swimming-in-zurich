"""Build the pool catalog (silver) from geo_sport pools: derive canonical ids, dedupe."""

from __future__ import annotations

from swimzh.domain.catalog import PoolCatalogEntry, slug
from swimzh.providers.geo_sport import GeoPool


def build_catalog(geo_pools: list[GeoPool]) -> tuple[PoolCatalogEntry, ...]:
    """Map WFS pools to catalog entries with stable, unique canonical ids (slug of the
    name; collisions get a numeric suffix so no two pools share an id)."""
    seen: dict[str, int] = {}
    entries: list[PoolCatalogEntry] = []
    for pool in geo_pools:
        base = slug(pool.name)
        count = seen.get(base, 0)
        seen[base] = count + 1
        pool_id = base if count == 0 else f"{base}-{count + 1}"
        entries.append(
            PoolCatalogEntry(
                pool_id=pool_id,
                name=pool.name,
                kind=pool.kind,
                address=pool.address,
                geo=pool.geo,
                url=pool.url,
                description=pool.description,
                phone=pool.phone,
            )
        )
    return tuple(entries)
