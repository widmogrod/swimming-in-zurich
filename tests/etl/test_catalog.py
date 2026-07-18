"""build_catalog derives stable canonical ids (slug) and dedupes collisions."""

from __future__ import annotations

from swimzh.domain.catalog import slug
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind
from swimzh.etl.catalog import build_catalog
from swimzh.providers.geo_sport import GeoPool


def _gp(name: str, kind: PoolKind) -> GeoPool:
    return GeoPool(
        source_id="x",
        poi_id=None,
        name=name,
        kind=kind,
        address="",
        geo=GeoPoint(lat=0.0, lon=0.0),
        url=None,
        category=None,
        description=None,
        phone=None,
    )


def test_slug_transliterates_umlauts() -> None:
    assert slug("Hallenbad City") == "hallenbad-city"
    assert slug("Wärmebad Käferberg") == "waermebad-kaeferberg"
    assert slug("Flussbad Unterer Letten (Flussteil)") == "flussbad-unterer-letten-flussteil"


def test_build_catalog_dedupes_id_collisions() -> None:
    pools = [
        _gp("Hallenbad City", PoolKind.INDOOR),
        _gp("Planschbecken Park", PoolKind.PADDLING),
        _gp("Planschbecken Park", PoolKind.PADDLING),  # same name → id collision
    ]
    entries = build_catalog(pools)
    ids = [e.pool_id for e in entries]
    assert ids == ["hallenbad-city", "planschbecken-park", "planschbecken-park-2"]
    assert len(set(ids)) == len(ids)
    assert entries[0].kind is PoolKind.INDOOR
