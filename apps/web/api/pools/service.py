"""Pools listing use-case: filter the catalog and shape the response."""

from __future__ import annotations

from apps.web.api.pools.model import (
    BasinLanePanelOut,
    ClubSlotOut,
    FacilityDetailOut,
    LaneDayViewOut,
    LanePanelOut,
    LaneSegmentOut,
    LaneStripOut,
    PoolOut,
    PoolsOut,
    PublicWindowOut,
)
from swimzh.domain.access import PublicSwim
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.lane_plan import (
    ClubSlot,
    LanePanel,
    LaneStrip,
    PublicWindow,
    owner_label,
)
from swimzh.domain.query import BasinLanePanel, FacilityDetail
from swimzh.domain.schedule import TimeRange


def _pool_out(entry: PoolCatalogEntry) -> PoolOut:
    return PoolOut(
        pool_id=entry.pool_id,
        name=entry.name,
        kind=entry.kind.value,
        address=entry.address,
        lat=entry.geo.lat if entry.geo is not None else None,
        lon=entry.geo.lon if entry.geo is not None else None,
        url=entry.url,
        description=entry.description,
        phone=entry.phone,
    )


def list_pools(catalog: tuple[PoolCatalogEntry, ...], kind: str | None) -> PoolsOut:
    items = [e for e in catalog if kind is None or e.kind.value == kind]
    items.sort(key=lambda e: (e.kind.value, e.name))
    kinds = sorted({e.kind.value for e in catalog})
    return PoolsOut(count=len(items), kinds=kinds, pools=[_pool_out(e) for e in items])


def _hhmm(t: TimeRange) -> tuple[str, str]:
    return t.start.strftime("%H:%M"), t.end.strftime("%H:%M")


def _strip_out(strip: LaneStrip) -> LaneStripOut:
    segments: list[LaneSegmentOut] = []
    for seg in strip.segments:
        start, end = _hhmm(seg.time)
        public = isinstance(seg.access, PublicSwim)
        segments.append(
            LaneSegmentOut(
                start=start,
                end=end,
                access=type(seg.access).__name__,
                owner=None if public else owner_label(seg.access),
            )
        )
    return LaneStripOut(lane=strip.lane, segments=segments)


def _club_slot_out(slot: ClubSlot) -> ClubSlotOut:
    start, end = _hhmm(slot.time)
    return ClubSlotOut(
        club=slot.club, weekday=int(slot.weekday), start=start, end=end, lanes=list(slot.lanes)
    )


def _public_window_out(window: PublicWindow) -> PublicWindowOut:
    start, end = _hhmm(window.time)
    return PublicWindowOut(start=start, end=end, public_lanes=window.public_lanes)


def _panel_out(panel: LanePanel) -> LanePanelOut:
    day = panel.day_view
    return LanePanelOut(
        day_view=LaneDayViewOut(
            weekday=int(day.weekday),
            lane_count=day.lane_count,
            strips=[_strip_out(s) for s in day.strips],
        ),
        best_public=(
            _public_window_out(panel.best_public) if panel.best_public is not None else None
        ),
        roster=[_club_slot_out(s) for s in panel.roster],
    )


def _basin_panel_out(basin_panel: BasinLanePanel) -> BasinLanePanelOut:
    return BasinLanePanelOut(
        basin_id=str(basin_panel.basin_id),
        basin_name=basin_panel.basin_name,
        panel=_panel_out(basin_panel.panel),
    )


def facility_detail_out(detail: FacilityDetail) -> FacilityDetailOut:
    """Shape the domain facility-detail answer for the API, surfacing the per-basin lane
    panels (day timeline + best public time + club roster)."""
    return FacilityDetailOut(
        facility_id=str(detail.facility_id),
        facility_name=detail.facility_name,
        address=detail.address,
        website=detail.website,
        lane_panels=[_basin_panel_out(p) for p in detail.lane_panels],
    )
