"""Faithful domain <-> JSON codec for the gold store.

A `Facility` is a deeply nested frozen-dataclass tree (basins → rules → tagged-union
access, plus prices, closures, exceptions). Rather than hand-roll JSON, we round-trip it
through a pydantic `StoredFacilityDTO` that reuses the same nested DTOs and shared
`boundary.mapping` as the curated loader — one source of truth for the shape, in both
directions. `dumps(f)` / `loads(s)` are exact inverses (verified by a round-trip test).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, assert_never

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from swimzh.boundary import mapping
from swimzh.boundary.curated_dto import (
    BasinDTO,
    ClosureDTO,
    FeatureDTO,
    GeoDTO,
    LockerOptionDTO,
    OperatingSeasonDTO,
    PriceTableDTO,
    RentalItemDTO,
    _AdmissionState,
    _HolidayPolicy,
    _PoolKind,
)
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.catalog import ScheduleFreshness, freshness_of
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
    # `None` == no source states this pool's public-holiday behaviour. Distinct from "normal",
    # which is a positive claim. Defaulted so a pre-existing blob (whose value was the
    # fabricated "normal") still validates; a rebuild replaces it with the honest unknown.
    public_holiday_policy: _HolidayPolicy | None = None
    # The admission union rides the EXISTING `prices` key plus one optional discriminant:
    #   Tariff(t) -> prices: <table>                        (byte-identical to pre-union blobs)
    #   Unknown   -> prices: null                           (byte-identical to pre-union blobs)
    #   Free      -> prices: null, admission_state: "free"  (the only new bytes)
    # A pre-union blob therefore loads as `Unknown` for unpriced pools — the honest reading of a
    # blob that predates the distinction. `admission_state` is popped when absent (the `min_age`
    # precedent), so only the 4 Free pools' blobs gain a key.
    prices: PriceTableDTO | None
    admission_state: _AdmissionState | None = None
    # The facility-level, timetable-free operating season (sharedsource-fanout S1). Defaulted so
    # every pre-existing blob validates, and POPPED when `None` (the `admission_state`/`min_age`
    # precedent) so the 44 pools without one serialize byte-identically to before the field.
    operating_season: OperatingSeasonDTO | None = None
    closures: list[ClosureDTO]
    basins: list[BasinDTO]
    notices: list[_NoticeDTO]
    features: list[FeatureDTO]
    lockers: list[LockerOptionDTO]
    # The non-locker half of the same page table (mietobjekt-extraction S2). Defaulted so every
    # pre-S2 blob (which lacks the key) still validates under `extra="forbid"`, and POPPED when
    # empty (see `_serialize`) so the 37 pools without a `Mietobjekt` table serialize
    # byte-identically to before the field.
    rentals: list[RentalItemDTO] = []
    # Slice F additive facility-level statics. Defaulted so a pre-Slice-F gold blob (which lacks
    # these keys) still validates under `extra="forbid"` and re-dumps faithfully. NOTE: these are
    # emitted UNCONDITIONALLY (as `null` when unset), matching the existing facility-level optional
    # keys (`website`, `prices`, …) — NOT popped when None. Recorded deviations from that rule:
    # `admission_state` (admission-union), `operating_season` (sharedsource-fanout) and `rentals`
    # (mietobjekt-extraction S2) ARE popped when None/empty — each is a rare-to-partial,
    # positively-stated fact (4 free pools; 13 seasonal pools; 20 rental-carrying pools), so
    # popping keeps every blob that lacks the fact byte-identical to its pre-field form, exactly
    # like the Slice-D-style pop-when-default serializers on the nested basin/lane-plan DTOs.
    last_admission_before: timedelta | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible (the `min_age` precedent): a facility that is not `Free` (or
        # carries no operating season, or no rentals) must serialise to exactly the same bytes
        # as before the `admission_state` / `operating_season` / `rentals` fields existed.
        data: dict[str, Any] = handler(self)
        if self.admission_state is None:
            data.pop("admission_state", None)
        if self.operating_season is None:
            data.pop("operating_season", None)
        if not self.rentals:
            data.pop("rentals", None)
        return data


def _admission_to_stored(
    admission: Admission,
) -> tuple[PriceTableDTO | None, _AdmissionState | None]:
    """Project the union onto the two stored keys (`prices`, `admission_state`)."""
    match admission:
        case Tariff(table):
            return mapping.price_table_to_dto(table), None
        case Free():
            return None, "free"
        case Unknown():
            return None, None
        case _ as unreachable:
            assert_never(unreachable)


def _admission_from_stored(stored: StoredFacilityDTO) -> Admission:
    """A table means `Tariff`; the discriminant means `Free`; anything else — including every
    pre-union blob with `prices: null` — is the honest `Unknown`."""
    if stored.prices is not None:
        return Tariff(mapping.price_table_from_dto(stored.prices))
    if stored.admission_state == "free":
        return Free()
    return Unknown()


def to_stored(facility: Facility) -> StoredFacilityDTO:
    ident = facility.identity
    prov = facility.provenance
    prices, admission_state = _admission_to_stored(facility.admission)
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
        public_holiday_policy=(
            _POLICY_TO[facility.public_holiday_policy]
            if facility.public_holiday_policy is not None
            else None
        ),
        prices=prices,
        admission_state=admission_state,
        operating_season=(
            mapping.operating_season_to_dto(facility.operating_season)
            if facility.operating_season is not None
            else None
        ),
        closures=[mapping.closure_to_dto(c) for c in facility.closures],
        basins=[mapping.basin_to_dto(b) for b in facility.basins],
        notices=[
            _NoticeDTO(text=n.text, active_from=n.active_from, active_to=n.active_to)
            for n in facility.notices
        ],
        features=[mapping.feature_to_dto(f) for f in facility.features],
        lockers=[mapping.locker_to_dto(lo) for lo in facility.lockers],
        rentals=[mapping.rental_to_dto(r) for r in facility.rentals],
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
        closures=tuple(mapping.closure_from_dto(c) for c in stored.closures),
        public_holiday_policy=(
            _POLICY_FROM[stored.public_holiday_policy]
            if stored.public_holiday_policy is not None
            else None
        ),
        operating_season=(
            mapping.operating_season_from_dto(stored.operating_season)
            if stored.operating_season is not None
            else None
        ),
        admission=_admission_from_stored(stored),
        notices=tuple(
            Notice(text=n.text, active_from=n.active_from, active_to=n.active_to)
            for n in stored.notices
        ),
        features=tuple(mapping.feature_from_dto(f) for f in stored.features),
        lockers=tuple(mapping.locker_from_dto(lo) for lo in stored.lockers),
        rentals=tuple(mapping.rental_from_dto(r) for r in stored.rentals),
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
    * `AWAITING_SCRAPE` — no rule yet, but every pool of this kind is a declared source
      (`etl.scrape.declared_sources`): WFS-`indoor` stadt-zuerich pools. A `Wärmebad` (`THERMAL`)
      like Käferberg is WFS-`indoor` but registry-overridden to `thermal` for display, so it IS
      scraped and must read `AWAITING_SCRAPE`, not `NO_SOURCE` — hence both kinds count here.
      `SCHOOL` does NOT: only 4 of the 18 Schulschwimmanlagen have their own page, and those 4
      carry rules, so they read `SCRAPED` from the blob without needing the kind test.
    * `NO_SOURCE` — no rule and not such a kind (e.g. a `schulschwimmanlage-hardau`-style `school`
      pool with no page of its own, or an outdoor/lake/river pool), OR a NULL blob: no schedule
      source at all.

    Both the read path (``load_roster``) and any build-time consumer share this one function so
    the rule cannot diverge. This is the BLOB door onto it: the rule itself is
    ``domain.catalog.freshness_of`` over the decoded facility, which `/pools/{id}` calls directly
    on the facility it already resolved.
    """
    if facility_doc is None:
        return ScheduleFreshness.NO_SOURCE
    return freshness_of(loads(facility_doc))
