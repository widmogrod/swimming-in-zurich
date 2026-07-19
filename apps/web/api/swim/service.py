"""The swim use-case: turn a parsed request into a domain query and shape the answer.

HTTP parsing/validation stays in router.py; this module works with domain types and the
`SwimData` port, so it is unit-testable without the web layer.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apps.web.api.swim.model import AnswerOut, NoticeOut, OptionOut, StatusOut
from apps.web.services.ports import SwimData
from swimzh.domain.geo import GeoPoint
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import SwimOption, SwimQuery, find_swim_options

_ZURICH = ZoneInfo("Europe/Zurich")


def _option_out(option: SwimOption) -> OptionOut:
    valid = option.provenance.valid_as_of
    return OptionOut(
        facility=option.facility_name,
        kind=option.facility_kind.value,
        basin=option.basin_name,
        length_m=float(option.basin_length_m) if option.basin_length_m is not None else None,
        lanes=option.lanes,
        start=option.session.time.start.strftime("%H:%M"),
        end=option.session.time.end.strftime("%H:%M"),
        access=type(option.session.access).__name__,
        eligible=option.eligibility.allowed,
        reason=option.eligibility.reason,
        price=option.price.display if option.price is not None else None,
        distance_km=round(option.distance_km, 2) if option.distance_km is not None else None,
        open_now=option.open_at_query_time,
        valid_as_of=valid.isoformat() if valid is not None else None,
        source=option.provenance.source,
        curated=option.provenance.curated,
    )


def build_answer(
    data: SwimData,
    *,
    gender: Gender | None,
    age: int | None,
    at: datetime,
    near: GeoPoint | None,
    radius_km: float | None,
    eligible_only: bool,
) -> AnswerOut:
    at_local = at if at.tzinfo is not None else at.replace(tzinfo=_ZURICH)
    query = SwimQuery(
        person=Person(gender=gender, age=age), at=at_local, near=near, radius_km=radius_km
    )
    result = find_swim_options(query, data.facilities(), data.calendar())
    options = result.eligible_options() if eligible_only else result.options
    return AnswerOut(
        options=[_option_out(o) for o in options],
        statuses=[
            StatusOut(facility=s.facility_name, status=s.status, detail=s.detail)
            for s in result.statuses
        ],
        warnings=list(result.warnings),
        notices=[NoticeOut(facility=n.facility_name, text=n.text) for n in result.notices],
    )
