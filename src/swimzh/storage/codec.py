"""Faithful domain <-> JSON codec for the gold store.

A `Facility` is a deeply nested frozen-dataclass tree (basins → rules → tagged-union
access, plus prices, closures, exceptions). Rather than hand-roll JSON, we round-trip it
through a pydantic `StoredFacilityDTO` that reuses the same nested DTOs and shared
`boundary.mapping` as the curated loader — one source of truth for the shape, in both
directions. `dumps(f)` / `loads(s)` are exact inverses (verified by a round-trip test).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import (
    BasinDTO,
    ClosureDTO,
    FeatureDTO,
    GeoDTO,
    LockerOptionDTO,
    PriceTableDTO,
    _HolidayPolicy,
    _PoolKind,
)
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.domain.models import (
    Facility,
    Notice,
    PoolIdentity,
    PoolKind,
    Provenance,
    reconstruct_pool_id,
)
from swimzh.domain.schedule import HolidayPolicy

_KIND_TO: dict[PoolKind, _PoolKind] = {
    PoolKind.INDOOR: "indoor",
    PoolKind.OUTDOOR: "outdoor",
    PoolKind.RIVER: "river",
    PoolKind.LAKE: "lake",
    PoolKind.SCHOOL: "school",
    PoolKind.PADDLING: "paddling",
    PoolKind.THERMAL: "thermal",
}
_KIND_FROM: dict[str, PoolKind] = {k.value: k for k in PoolKind}

_POLICY_TO: dict[HolidayPolicy, _HolidayPolicy] = {
    HolidayPolicy.NORMAL: "normal",
    HolidayPolicy.SUNDAY_SCHEDULE: "sunday_schedule",
    HolidayPolicy.CLOSED: "closed",
}
_POLICY_FROM: dict[str, HolidayPolicy] = {p.value: p for p in HolidayPolicy}


class _NoticeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    active_from: date | None
    active_to: date | None


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
    # Baditicker water-temp feed poiid — the *key* (persisted); the live reading is never stored.
    # Defaulted so a pre-existing gold blob (which lacks this key) still validates under
    # `extra="forbid"`, matching the other facility-level optionals (emitted unconditionally).
    baditicker_poiid: str | None = None
    aliases: list[str]
    geo: GeoDTO | None
    amenities: list[str]
    public_holiday_policy: _HolidayPolicy
    prices: PriceTableDTO | None
    closures: list[ClosureDTO]
    basins: list[BasinDTO]
    notices: list[_NoticeDTO]
    website: str | None
    features: list[FeatureDTO]
    lockers: list[LockerOptionDTO]
    # Slice F additive facility-level statics. Defaulted so a pre-Slice-F gold blob (which lacks
    # these keys) still validates under `extra="forbid"` and re-dumps faithfully. NOTE: these are
    # emitted UNCONDITIONALLY (as `null` when unset), matching the existing facility-level optional
    # keys (`website`, `prices`, …) — NOT popped when None. The Slice-D-style pop-when-default
    # serializer is applied only to the deeply-nested basin/lane-plan DTOs, whose byte-stability
    # the round-trip fixtures assert; facility-level keys carry no such byte-identity contract.
    accessibility: str | None = None
    last_admission_before: timedelta | None = None


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
        baditicker_poiid=ident.baditicker_poiid,
        aliases=list(ident.aliases),
        geo=mapping.geo_to_dto(facility.geo) if facility.geo is not None else None,
        amenities=sorted(facility.amenities),
        public_holiday_policy=_POLICY_TO[facility.public_holiday_policy],
        prices=mapping.price_table_to_dto(facility.prices) if facility.prices is not None else None,
        closures=[mapping.closure_to_dto(c) for c in facility.closures],
        basins=[mapping.basin_to_dto(b) for b in facility.basins],
        notices=[
            _NoticeDTO(text=n.text, active_from=n.active_from, active_to=n.active_to)
            for n in facility.notices
        ],
        website=facility.website,
        features=[mapping.feature_to_dto(f) for f in facility.features],
        lockers=[mapping.locker_to_dto(lo) for lo in facility.lockers],
        accessibility=facility.accessibility,
        last_admission_before=facility.last_admission_before,
    )


def from_stored(stored: StoredFacilityDTO) -> Facility:
    identity = PoolIdentity(
        facility_id=reconstruct_pool_id(stored.facility_id),
        name=stored.name,
        kind=_KIND_FROM[stored.kind],
        geo_sport_id=stored.geo_sport_id,
        crowdmonitor_keys=tuple(stored.crowdmonitor_keys),
        baditicker_poiid=stored.baditicker_poiid,
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
        notices=tuple(
            Notice(text=n.text, active_from=n.active_from, active_to=n.active_to)
            for n in stored.notices
        ),
        website=stored.website,
        features=tuple(mapping.feature_from_dto(f) for f in stored.features),
        lockers=tuple(mapping.locker_from_dto(lo) for lo in stored.lockers),
        accessibility=stored.accessibility,
        last_admission_before=stored.last_admission_before,
    )


def dumps(facility: Facility) -> str:
    return to_stored(facility).model_dump_json()


def loads(payload: str) -> Facility:
    return from_stored(StoredFacilityDTO.model_validate_json(payload))


def schedule_freshness(facility_doc: str | None) -> ScheduleFreshness:
    """The single source of the three-state curation model: derive a pool's `ScheduleFreshness`
    from its schedule blob (kind + rules presence), never a stored column — so the status can
    never disagree with the blob it describes. Replaced the `is_curated` boolean in S1.

    * `SCRAPED` — the decoded facility has ≥1 basin carrying ≥1 rule.
    * `AWAITING_SCRAPE` — no rule yet, but the pool is scrapeable. The scrapeable set is what
      `scrape_indoor_facilities` fetches: WFS-`indoor` stadt-zuerich pools. A `Wärmebad` (`THERMAL`)
      like Käferberg is WFS-`indoor` but registry-overridden to `thermal` for display, so it IS
      scraped and must read `AWAITING_SCRAPE`, not `NO_SOURCE` — hence both kinds count here.
    * `NO_SOURCE` — no rule and not a scrapeable kind (e.g. an `aemtler`-style `school` pool, or an
      outdoor/lake/river pool), OR a NULL blob: no schedule source at all.

    Both the read path (``load_roster``) and any build-time consumer share this one function so
    the rule cannot diverge.
    """
    if facility_doc is None:
        return ScheduleFreshness.NO_SOURCE
    facility = loads(facility_doc)
    if any(basin.rules for basin in facility.basins):
        return ScheduleFreshness.SCRAPED
    if facility.identity.kind in (PoolKind.INDOOR, PoolKind.THERMAL):
        return ScheduleFreshness.AWAITING_SCRAPE
    return ScheduleFreshness.NO_SOURCE
