"""Request/response models for the swim endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class LaneAvailabilityOut(BaseModel):
    """The lane-reservation glance badge: how many of the basin's lanes are public at this
    session's time. A derived, live-only-style projection — never persisted to gold."""

    lane_count: int
    public_lanes: int  # count of EXPLICITLY-public lanes (never derived by complement)
    reserved_lanes: int
    public_until: str | None  # "HH:MM" end of the current public run, or None if not public now
    partial: bool  # the slot touches an unresolved lane, so the counts may be incomplete


class OptionOut(BaseModel):
    facility: str
    kind: str  # facility kind (indoor/outdoor/…), for the glance badge context
    basin: str
    length_m: float | None  # basin length — the fat left badge; None degrades gracefully
    lanes: int | None  # basin lane count — the badge's "N lane" sub-line; None => length-only
    start: str
    end: str
    access: str
    eligible: bool
    reason: str
    price: str | None
    distance_km: float | None
    open_now: bool
    valid_as_of: str | None
    source: str  # provenance source (e.g. stadt-zuerich.ch), for the ⓘ stamp
    curated: bool  # True = hand-curated, False = scraped
    # None = the basin has no parsed Belegungsplan; otherwise the lane-availability badge.
    lane_availability: LaneAvailabilityOut | None = None


class StatusOut(BaseModel):
    facility: str
    status: str  # "closed" | "uncurated"
    detail: str


class NoticeOut(BaseModel):
    facility: str
    text: str


class AnswerOut(BaseModel):
    options: list[OptionOut]
    statuses: list[StatusOut]
    warnings: list[str]
    notices: list[NoticeOut]
