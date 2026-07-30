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
    # The derived three-state schedule freshness (delete-curated-schedule-tier S1): "scraped"
    # (a real schedule), "awaiting_scrape" (indoor, scrapeable, no schedule yet), or "no_source"
    # (no timetable source at all). Replaced the `curated` boolean; never "closed".
    freshness: str


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
    measured_temp_c: float | None  # an actually-measured reading; overrides nominal in the badge
    diving_platforms_m: list[float]  # board/platform heights, e.g. [1, 3, 5]; empty when none
    # Honesty caveat: "curated" (hand-verified) vs "parsed_prose" (auto-extracted, unverified).
    physical_source: str
    # The basin's declared Belegungsplan (lane-plan) PDF source URL; None when the basin
    # declares no `lane_plan_source`. The `section` token stays in the domain (a sheet
    # sub-section, not a URL fragment) — it has no UI use here.
    lane_plan_url: str | None


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


class LiveWaterTempOut(BaseModel):
    """The facility-level LIVE water temperature (Baditicker), resolved at request time — NOT the
    per-basin `measured_temp_c`/`nominal_temp_c` design values. Always present on the detail so
    the UI can distinguish three states honestly:

      * `available=True, celsius=<n>`  — a live reading; show "23 °C · measured N min ago".
      * `available=True, celsius=None` — open but not yet measured (empty feed cell) — a live
        answer, NOT unavailable.
      * `available=False`              — `reason` says why (no key / provider error / not
        configured); the UI shows the reason, never a stale number.
    """

    available: bool  # True = a live reading (LiveTemp); False = TempUnavailable
    celsius: float | None  # the reading; None when open-but-unmeasured, or when unavailable
    measured_at: str | None  # ISO tz-aware timestamp of the reading; None when unavailable
    age_min: int | None  # whole minutes since the reading; None when unavailable
    is_open: bool | None  # feed open/closed at read time; None when unavailable
    is_stale: bool | None  # derived freshness (reading older than the staleness limit)
    source: str | None  # e.g. "baditicker"; None when unavailable
    reason: str | None  # technical detail for operators; None when available
    # The i18n key for `reason` — the UI renders this, never the raw text (which may be a
    # provider diagnostic like "HTTP 503: …", useless to a reader in any language).
    reason_code: str | None = None


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
    amenities: list[str]  # facility amenity tags (sorted); empty when none recorded
    accessibility: str | None  # free-text accessibility note; None when unknown
    last_admission_before_min: int | None  # minutes before closing that admission stops
    # Facility-level LIVE water temperature (Baditicker), resolved at request time. Always
    # present — additive and labelled, it never overwrites a basin's `measured_temp_c`.
    live_water_temp: LiveWaterTempOut
