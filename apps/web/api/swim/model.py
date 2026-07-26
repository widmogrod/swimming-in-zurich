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


class LaneTimelineSegmentOut(BaseModel):
    """One constant-availability sub-window of a session — the lane split between two
    reservation boundaries. A derived, never-persisted projection of the stored plan."""

    start: str  # "HH:MM"
    end: str  # "HH:MM"
    lane_count: int
    public_lanes: int
    reserved_lanes: int
    partial: bool


class LaneTimelineOut(BaseModel):
    """The session's lane split as it changes across the session (one segment per boundary),
    so the UI can render "4/6 then 2/6 after 18:00" instead of a single collapsed count."""

    segments: list[LaneTimelineSegmentOut]


class OptionOut(BaseModel):
    facility: str
    facility_id: str  # stable id for the facility-detail (/pools/{id}) lane-panel fetch
    kind: str  # facility kind (indoor/outdoor/…), for the glance badge context
    basin: str
    length_m: float | None  # basin length — the fat left badge; None degrades gracefully
    lanes: int | None  # basin lane count — the badge's "N lane" sub-line; None => length-only
    start: str
    end: str
    access: str
    eligible: bool
    # --- i18n ------------------------------------------------------------------------
    # The message key for the eligibility outcome + its interpolation values. The English
    # `reason` prose this replaced was retired in S5: the server no longer decides what
    # language the answer is in. `rule` is NOT sufficient as a key — four women-only
    # outcomes share one rule.
    reason_code: str
    reason_params: dict[str, str | int] = {}
    price: str | None
    distance_km: float | None
    open_now: bool
    valid_as_of: str | None
    source: str  # provenance source (e.g. stadt-zuerich.ch), for the ⓘ stamp
    curated: bool  # True = hand-curated, False = scraped
    # None = the basin has no parsed Belegungsplan; otherwise the lane-availability badge.
    lane_availability: LaneAvailabilityOut | None = None
    # None = no parsed plan; otherwise the per-boundary lane split across the whole session,
    # for the "4/6 then 2/6 after 18:00" arc.
    lane_timeline: LaneTimelineOut | None = None


class StatusOut(BaseModel):
    facility: str
    status: str  # "closed" | "uncurated"
    # --- i18n ------------------------------------------------------------------------
    # `detail` used to mix languages here: English "schedule not yet curated" in one branch
    # and curated German ("Sommerpause") in the other. Retired in S5 — the code names which
    # sentence it is, and S4's `closure_code` names WHICH closure.
    detail_code: str
    # S4: WHICH closure, from the classified code set — `null` for uncurated. The client
    # renders this; `closure_code == "unmapped"` means we could not classify the curated
    # phrase, and `detail_params.text` carries it verbatim so the UI stays truthful.
    closure_code: str | None = None
    detail_params: dict[str, str] = {}


class NoticeOut(BaseModel):
    facility: str
    text: str


class AnswerOut(BaseModel):
    options: list[OptionOut]
    statuses: list[StatusOut]
    warnings: list[str]
    notices: list[NoticeOut]
