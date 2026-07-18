"""Facility-level domain models: identity, basins, provenance, occupancy, and the
`Facility` aggregate that the query surface reads.

A `Facility` (e.g. "Hallenbad City") contains one or more `Basin`s, each with its *own*
schedule — modelled explicitly because one address can host basins with independent hours
and access rules. Closures and public-holiday policy sit at the facility level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import NewType

from swimzh.domain.geo import GeoPoint
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import (
    ClosureRange,
    HolidayPolicy,
    ScheduleException,
    ScheduleRule,
)

FacilityId = NewType("FacilityId", str)
BasinId = NewType("BasinId", str)


class PoolKind(Enum):
    INDOOR = "indoor"  # Hallenbad
    OUTDOOR = "outdoor"  # Freibad
    RIVER = "river"  # Flussbad
    LAKE = "lake"  # Seebad
    SCHOOL = "school"  # Schulschwimmanlage
    PADDLING = "paddling"  # Planschbecken
    THERMAL = "thermal"  # Wärmebad


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a piece of data came from and how fresh it is. Attached to every answer so a
    stale-but-typed wrong answer is at least visibly stale."""

    source: str
    curated: bool
    valid_as_of: date | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PoolIdentity:
    """Canonical identity + crosswalk into other data sources' namespaces."""

    facility_id: FacilityId
    name: str
    kind: PoolKind
    geo_sport_id: str | None = None
    crowdmonitor_keys: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Occupancy:
    """A live occupancy reading (attached only when the query time is ~now)."""

    facility_id: FacilityId
    measured_at: datetime
    percent_full: float | None
    people: int | None
    capacity: int | None
    source: str


@dataclass(frozen=True, slots=True)
class Basin:
    basin_id: BasinId
    name: str
    rules: tuple[ScheduleRule, ...]
    exceptions: tuple[ScheduleException, ...] = field(default_factory=tuple)
    length_m: int | None = None


@dataclass(frozen=True, slots=True)
class Facility:
    identity: PoolIdentity
    address: str
    provenance: Provenance
    basins: tuple[Basin, ...]
    geo: GeoPoint | None = None
    amenities: frozenset[str] = frozenset()
    closures: tuple[ClosureRange, ...] = field(default_factory=tuple)
    public_holiday_policy: HolidayPolicy = HolidayPolicy.NORMAL
    prices: PriceTable | None = None
