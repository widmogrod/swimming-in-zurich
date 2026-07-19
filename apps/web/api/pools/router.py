"""Pools endpoint — list all catalog pools, and one facility's lane-detail panel."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from apps.web.api.pools.model import FacilityDetailOut, PoolsOut
from apps.web.api.pools.service import facility_detail_out, list_pools
from apps.web.deps import get_swim_data
from swimzh.domain.models import PoolKind
from swimzh.domain.query import facility_detail

router = APIRouter()

_KINDS = {k.value for k in PoolKind}
_ZURICH = ZoneInfo("Europe/Zurich")


@router.get("/pools", response_model=PoolsOut)
def pools(request: Request, kind: str | None = None) -> PoolsOut:
    if kind is not None and kind not in _KINDS:
        raise HTTPException(
            status_code=400, detail=f"invalid kind {kind!r}; one of {sorted(_KINDS)}"
        )
    return list_pools(get_swim_data(request).roster(), kind)


@router.get("/pools/{facility_id}", response_model=FacilityDetailOut)
def pool_detail(
    request: Request, facility_id: str, at: datetime | None = None
) -> FacilityDetailOut:
    """Resolve a catalog pool to its schedule from the one store: the facility-detail lane
    panel for `facility_id` (canonical `pool.id`) — per-lane day timeline, best public time,
    and club roster for the weekday of `at` (default: now). Empty `lane_panels` when the
    facility's basins carry no parsed Belegungsplan yet. A pool with no curated schedule (or an
    unknown id) is a 404."""
    data = get_swim_data(request)
    facility = data.facility(facility_id)
    if facility is None:
        raise HTTPException(status_code=404, detail=f"unknown facility {facility_id!r}")
    when = at if at is not None else datetime.now(_ZURICH)
    return facility_detail_out(facility_detail(facility, when, data.calendar()))
