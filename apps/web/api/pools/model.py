"""Request/response models for the pools listing."""

from __future__ import annotations

from pydantic import BaseModel


class PoolOut(BaseModel):
    pool_id: str
    name: str
    kind: str
    address: str
    lat: float | None
    lon: float | None
    url: str | None
    description: str | None
    phone: str | None
    curated: bool  # True = a curated timetable exists (derived); False = location only


class PoolsOut(BaseModel):
    count: int
    kinds: list[str]  # kinds present, for filter UIs
    pools: list[PoolOut]


# --- Facility detail: the lane panel (per-basin Belegungsplan derivations) ---------------


class LaneSegmentOut(BaseModel):
    start: str  # "HH:MM"
    end: str
    access: str  # SessionAccess class name, e.g. "PublicSwim" / "ClubReserved"
    owner: str | None  # club/school label for a reserved lane; None when public


class LaneStripOut(BaseModel):
    lane: int  # 1-based
    segments: list[LaneSegmentOut]  # sorted by start; gaps are implicit (absent), not public


class LaneDayViewOut(BaseModel):
    weekday: int  # 0 = Monday, matching date.weekday()
    lane_count: int
    strips: list[LaneStripOut]


class ClubSlotOut(BaseModel):
    club: str
    weekday: int
    start: str
    end: str
    lanes: list[int]


class PublicWindowOut(BaseModel):
    start: str
    end: str
    public_lanes: int


class LanePanelOut(BaseModel):
    day_view: LaneDayViewOut
    best_public: PublicWindowOut | None  # "best time to come"; None when never public that day
    roster: list[ClubSlotOut]


class BasinLanePanelOut(BaseModel):
    basin_id: str
    basin_name: str
    panel: LanePanelOut


# --- Facility detail: the physical statics the domain already computes -------------------
# Pure projection of `domain.FacilityDetail` (basins, features with resolved hours, lockers,
# provenance) plus the facility's price table. No domain change — the query surface already
# computes every field; these DTOs only shape it for JSON.


class TimeRangeOut(BaseModel):
    start: str  # "HH:MM"
    end: str


class BasinOut(BaseModel):
    basin_id: str
    name: str
    kind: str  # BasinKind value, e.g. "lap" / "teaching" / "vario"
    length_m: float | None  # from Dimensions; None when unknown
    width_m: float | None
    lanes: int | None
    nominal_temp_c: float | None  # the basin's DESIGN temperature (not a live reading)
    # Honesty caveat: "curated" (hand-verified) vs "parsed_prose" (auto-extracted, unverified).
    physical_source: str


class FeatureStatusOut(BaseModel):
    kind: str  # FeatureKind value, e.g. "sauna"
    name: str
    surcharge_chf: float | None
    temp_c: float | None
    note: str
    # None = the feature has no separately stated hours (assume facility hours) — unknown,
    # never conflated with closed. True/False = resolved against the queried moment.
    open_now: bool | None
    hours: list[TimeRangeOut]  # resolved sessions for the queried day; empty when none/closed
    closed_reason: str | None  # set only when the feature is closed that day


class LockerOut(BaseModel):
    category: str  # LockerCategory value: "wardrobe" / "valuables" / "laundry"
    fee_chf: float | None  # None = free to use
    deposit_chf: float | None  # refundable Pfand
    period: str | None  # free text ("1 Jahr", "Saison")
    mechanism: str | None
    raw: str


class PriceEntryOut(BaseModel):
    category: str  # PriceCategory value
    amount_chf: float
    display: str


class PriceTableOut(BaseModel):
    entries: list[PriceEntryOut]
    valid_as_of: str | None  # ISO date the tariff was checked
    source_url: str | None


class ProvenanceOut(BaseModel):
    source: str
    curated: bool  # True = hand-curated, False = scraped
    valid_as_of: str | None
    fetched_at: str | None


class FacilityDetailOut(BaseModel):
    facility_id: str
    facility_name: str
    address: str
    website: str | None
    # The physical statics the domain already computes — surfaced so water temperature, basin
    # size, sauna/lockers, and prices reach the swimmer (they existed in the store but were
    # dropped at this boundary before Slice C).
    basins: list[BasinOut]
    features: list[FeatureStatusOut]
    lockers: list[LockerOut]
    prices: PriceTableOut | None  # the facility's price table; None when not curated
    provenance: ProvenanceOut
    # One panel per basin that carries a parsed Belegungsplan; empty when none do.
    lane_panels: list[BasinLanePanelOut]
