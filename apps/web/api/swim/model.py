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


# --- The per-lane day view (lane-stack-board S2) -----------------------------------------
#
# D1, settled here: these four DTOs are DECLARED IN THIS PACKAGE even though `/pools` declares
# structurally identical ones (`apps/web/api/pools/model.py`). No `apps/web/api/*` module
# imports another endpoint's model — the endpoint packages are self-contained per the
# `python-dev:fastapi-service` package rule, and one endpoint's response schema is not a
# contract the other may be dragged behind. Duplicating four field-only models is cheaper than
# a shared-model module every future endpoint must then reason about. Independent evolution is
# the point, not an accident: `/pools` serves a whole facility's panel, `/swim` serves one
# session's basin, and either may add a field the other must not grow.


class LaneSegmentOut(BaseModel):
    """One owner's hold on a single lane for a time range — a cell of a lane's day strip."""

    start: str  # "HH:MM"
    end: str
    access: str  # SessionAccess class name, e.g. "PublicSwim" / "ClubReserved"
    owner: str | None  # club/school label for a reserved lane; None when public


class LaneStripOut(BaseModel):
    """One lane's whole day, sorted by start. Gaps are implicit (absent), never public."""

    lane: int  # 1-based
    segments: list[LaneSegmentOut]


class LaneDayViewOut(BaseModel):
    """The basin's per-lane day — one strip per lane `1..lane_count`. Unlike `LaneTimelineOut`
    (counts only) this carries WHICH lane and WHOSE, which is what the lane stack paints. It
    spans the whole weekday, not the session window."""

    weekday: int  # 0 = Monday, matching date.weekday()
    lane_count: int
    strips: list[LaneStripOut]


class PublicWindowOut(BaseModel):
    """This SESSION's "best time to come": the window with the most public lanes free, bounded
    by the option's own hours. `/pools`' identically-shaped DTO carries the WHOLE-DAY window —
    it hangs off a per-day panel, this one off one session. The two must not be conflated."""

    start: str
    end: str
    public_lanes: int


class OptionOut(BaseModel):
    facility: str
    facility_id: str  # stable id for the facility-detail (/pools/{id}) lane-panel fetch
    kind: str  # facility kind (indoor/outdoor/…), for the glance badge context
    basin: str
    # The basin's stable id — the board row key. Deliberately carried BESIDE `basin`: names are
    # not guaranteed unique within a facility, so a row keyed on the name can silently collide;
    # the name stays the human label and the `/pools` lane-panel match.
    basin_id: str
    length_m: float | None  # basin length — the fat left badge; None degrades gracefully
    lanes: int | None  # basin lane count — the badge's "N lane" sub-line; None => length-only
    start: str
    end: str
    access: str
    # Whether this BLOCK is published unconditionally ("any") or only for fair weather
    # ("fair_only"). Read off `SwimOption.session.weather` — deliberately NOT a new
    # `query.py` field, and deliberately PER-SESSION: on a summer day Heuried is certainly
    # open 09:00–14:00 and conditionally open 14:00–21:00, so a day-level flag would launder
    # a known fact into an unknown.
    weather: str
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
    # None = no parsed plan; otherwise the basin's per-lane day (who holds which lane, when) —
    # what the board's lane stack paints. Additive: `lane_availability` and `lane_timeline` keep
    # their exact shapes and their existing readers.
    lane_day_view: LaneDayViewOut | None = None
    # None = no parsed plan, OR no lane is public anywhere inside THIS session. Bounded by the
    # option's hours, so its `public_lanes` equals the peak of this option's `lane_timeline` by
    # construction. NOT nested inside `lane_day_view`: the day view is {weekday, lane_count,
    # strips} and the window is a separate derivation, as `/pools` also keeps it.
    lane_best_public: PublicWindowOut | None = None


class StatusOut(BaseModel):
    facility: str
    # The schedule status of a no-options pool (delete-curated-schedule-tier S1):
    # "closed" (curated but shut today) | "awaiting_scrape" (indoor, no schedule yet) | "no_source"
    # (no timetable source) | "open_unscheduled" (sharedsource-fanout S1: the pool's own page
    # states an operating season it is inside, but publishes no hours — season + weather ride
    # `detail_params`). A schedule-less pool is NEVER "closed": that invariant protects pools
    # whose schedule is UNKNOWN, and a pool whose own page states its season is knowably shut
    # outside it — such a pool serves "closed" + closure_code "out_of_season", the same pair a
    # seasonal scraped pool already serves, and "open_unscheduled" (never "no_source") in season.
    status: str
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
