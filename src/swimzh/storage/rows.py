"""The identity-spine row DTOs: the shape the gold ``pool`` tables are written from.

These sit in ``storage`` (below ``build``): the write side (``storage/sqlite_repo``) types on
them directly, and the seed loader (``build/seed``) — which mints the ``PoolId`` and folds the
roster into a ``PoolSpine`` — imports them from here (a correct downward ``build → storage`` edge).
"""

from __future__ import annotations

from dataclasses import dataclass

from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolId, PoolKind


@dataclass(frozen=True, slots=True)
class PoolRow:
    """One roster row: canonical identity + catalog metadata + the (optional) curated blob."""

    id: PoolId
    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint | None
    url: str | None
    description: str | None
    phone: str | None
    facility_doc: str | None  # curated Facility JSON (codec), else None; also the curation fact


@dataclass(frozen=True, slots=True)
class PoolAliasRow:
    pool_id: PoolId
    alias: str
    norm: str


@dataclass(frozen=True, slots=True)
class PoolXrefRow:
    pool_id: PoolId
    namespace: str
    ext_id: str


@dataclass(frozen=True, slots=True)
class PoolSpine:
    """The identity spine: the ``pool`` rows plus the alias/xref crosswalk that points at them."""

    pools: tuple[PoolRow, ...]
    aliases: tuple[PoolAliasRow, ...]
    xrefs: tuple[PoolXrefRow, ...]
