"""The pool catalog: flat metadata for every Zürich swimming facility.

Distinct from `Facility` (which carries schedules): a catalog entry is just what the WFS
publishes — identity, location, official link, description. It answers "show me all pools",
independent of whether we have that pool's timetable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind

_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def slug(name: str) -> str:
    """A stable, url-safe canonical id derived from a pool name.

    e.g. "Hallenbad City" -> "hallenbad-city", "Wärmebad Käferberg" -> "waermebad-kaeferberg".
    """
    lowered = name.strip().lower().translate(_TRANSLIT)
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


@dataclass(frozen=True, slots=True)
class PoolCatalogEntry:
    pool_id: str
    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint | None
    url: str | None
    description: str | None
    phone: str | None
