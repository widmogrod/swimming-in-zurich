"""The swim use-case: turn a parsed request into a domain query and shape the answer.

HTTP parsing/validation stays in router.py; this module works with domain types and the
`SwimStore` port, so it is unit-testable without the web layer.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apps.web.api.swim.model import (
    AnswerOut,
    LaneAvailabilityOut,
    LaneDayViewOut,
    LaneSegmentOut,
    LaneStripOut,
    LaneTimelineOut,
    LaneTimelineSegmentOut,
    NoticeOut,
    OptionOut,
    PublicWindowOut,
    StatusOut,
)
from apps.web.services.ports import SwimStore
from swimzh.domain.access import PublicSwim
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import (
    LaneAvailability,
    LaneAvailabilityTimeline,
    LaneDayView,
    PublicWindow,
    owner_label,
)
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import SwimOption, SwimQuery, find_swim_options

_ZURICH = ZoneInfo("Europe/Zurich")


def _lane_availability_out(avail: LaneAvailability | None) -> LaneAvailabilityOut | None:
    if avail is None:
        return None
    return LaneAvailabilityOut(
        lane_count=avail.lane_count,
        public_lanes=avail.public_lanes,
        reserved_lanes=avail.reserved_lanes,
        public_until=avail.public_until.strftime("%H:%M") if avail.public_until else None,
        partial=avail.partial,
    )


def _lane_timeline_out(timeline: LaneAvailabilityTimeline | None) -> LaneTimelineOut | None:
    if timeline is None:
        return None
    return LaneTimelineOut(
        segments=[
            LaneTimelineSegmentOut(
                start=seg.time.start.strftime("%H:%M"),
                end=seg.time.end.strftime("%H:%M"),
                lane_count=seg.availability.lane_count,
                public_lanes=seg.availability.public_lanes,
                reserved_lanes=seg.availability.reserved_lanes,
                partial=seg.availability.partial,
            )
            for seg in timeline.segments
        ]
    )


def _lane_day_view_out(view: LaneDayView | None) -> LaneDayViewOut | None:
    if view is None:
        return None
    return LaneDayViewOut(
        weekday=int(view.weekday),
        lane_count=view.lane_count,
        strips=[
            LaneStripOut(
                lane=strip.lane,
                segments=[
                    LaneSegmentOut(
                        start=seg.time.start.strftime("%H:%M"),
                        end=seg.time.end.strftime("%H:%M"),
                        access=type(seg.access).__name__,
                        # A public segment has no owner to name; anything else is labelled by
                        # the domain's own `owner_label`, never by re-deriving prose here.
                        owner=(
                            None if isinstance(seg.access, PublicSwim) else owner_label(seg.access)
                        ),
                    )
                    for seg in strip.segments
                ],
            )
            for strip in view.strips
        ],
    )


def _public_window_out(window: PublicWindow | None) -> PublicWindowOut | None:
    if window is None:
        return None
    return PublicWindowOut(
        start=window.time.start.strftime("%H:%M"),
        end=window.time.end.strftime("%H:%M"),
        public_lanes=window.public_lanes,
    )


def _option_out(option: SwimOption) -> OptionOut:
    valid = option.provenance.valid_as_of
    return OptionOut(
        facility=option.facility_name,
        facility_id=str(option.facility_id),
        kind=option.facility_kind.value,
        basin=option.basin_name,
        basin_id=str(option.basin_id),
        length_m=float(option.basin_length_m) if option.basin_length_m is not None else None,
        lanes=option.lanes,
        start=option.session.time.start.strftime("%H:%M"),
        end=option.session.time.end.strftime("%H:%M"),
        access=type(option.session.access).__name__,
        weather=option.session.weather.value,
        eligible=option.eligibility.allowed,
        reason_code=option.eligibility.code.value,
        reason_params=dict(option.eligibility.params),
        price=option.price.display if option.price is not None else None,
        distance_km=round(option.distance_km, 2) if option.distance_km is not None else None,
        open_now=option.open_at_query_time,
        valid_as_of=valid.isoformat() if valid is not None else None,
        source=option.provenance.source,
        curated=option.provenance.curated,
        lane_availability=_lane_availability_out(option.lane_availability),
        lane_timeline=_lane_timeline_out(option.lane_timeline),
        lane_day_view=_lane_day_view_out(option.lane_day_view),
        lane_best_public=_public_window_out(option.lane_best_public),
    )


def build_answer(
    data: SwimStore,
    *,
    gender: Gender | None,
    age: int | None,
    at: datetime | None,
    near: GeoPoint | None,
    radius_km: float | None,
    eligible_only: bool,
) -> AnswerOut:
    # `at` is optional: an absent moment means "now", materialised ONCE here at the boundary as
    # server time (Europe/Zurich). Everything downstream reads this resolved, tz-aware moment, so
    # the domain never calls datetime.now() for the query clock.
    resolved_at = at if at is not None else datetime.now(_ZURICH)
    at_local = (
        resolved_at if resolved_at.tzinfo is not None else resolved_at.replace(tzinfo=_ZURICH)
    )
    query = SwimQuery(
        person=Person(gender=gender, age=age), at=at_local, near=near, radius_km=radius_km
    )
    # Pass the full roster so `uncurated` statuses go live (roster − scheduled) — the backend
    # emits them at runtime; the UI no longer guesses schedule status by name.
    result = find_swim_options(query, data.facilities(), data.calendar(), data.roster())
    options = result.eligible_options() if eligible_only else result.options
    return AnswerOut(
        options=[_option_out(o) for o in options],
        statuses=[
            StatusOut(
                facility=s.facility_name,
                status=s.status,
                detail_code=s.code.value,
                closure_code=s.closure.value if s.closure else None,
                detail_params=dict(s.params),
            )
            for s in result.statuses
        ],
        warnings=list(result.warnings),
        notices=[NoticeOut(facility=n.facility_name, text=n.text) for n in result.notices],
    )
