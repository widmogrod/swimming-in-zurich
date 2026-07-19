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


class FacilityDetailOut(BaseModel):
    facility_id: str
    facility_name: str
    address: str
    website: str | None
    # One panel per basin that carries a parsed Belegungsplan; empty when none do.
    lane_panels: list[BasinLanePanelOut]
