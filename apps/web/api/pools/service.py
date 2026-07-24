"""Pools listing use-case: filter the catalog and shape the response."""

from __future__ import annotations

from apps.web.api.pools.model import (
    BasinLanePanelOut,
    BasinOut,
    ClubSlotOut,
    FacilityDetailOut,
    FeatureStatusOut,
    LaneDayViewOut,
    LanePanelOut,
    LaneSegmentOut,
    LaneStripOut,
    LockerOut,
    PoolOut,
    PoolsOut,
    PriceEntryOut,
    PriceTableOut,
    ProvenanceOut,
    PublicWindowOut,
    TimeRangeOut,
)
from swimzh.domain.access import PublicSwim
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.lane_plan import (
    ClubSlot,
    LanePanel,
    LaneStrip,
    PublicWindow,
    owner_label,
)
from swimzh.domain.lockers import LockerOption
from swimzh.domain.models import Basin, Provenance
from swimzh.domain.pricing import PriceTable
from swimzh.domain.query import BasinLanePanel, FacilityDetail, FeatureStatus
from swimzh.domain.schedule import ClosedDay, OpenDay, TimeRange


def _pool_out(row: RosterEntry) -> PoolOut:
    entry = row.entry
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
        curated=row.curated,
    )


def list_pools(roster: tuple[RosterEntry, ...], kind: str | None) -> PoolsOut:
    items = [r for r in roster if kind is None or r.entry.kind.value == kind]
    items.sort(key=lambda r: (r.entry.kind.value, r.entry.name))
    kinds = sorted({r.entry.kind.value for r in roster})
    return PoolsOut(count=len(items), kinds=kinds, pools=[_pool_out(r) for r in items])


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


def _basin_out(basin: Basin) -> BasinOut:
    dims = basin.dimensions
    return BasinOut(
        basin_id=str(basin.basin_id),
        name=basin.name,
        kind=basin.kind.value,
        length_m=float(dims.length_m) if dims is not None else None,
        width_m=float(dims.width_m) if dims is not None and dims.width_m is not None else None,
        lanes=basin.lanes,
        nominal_temp_c=float(basin.nominal_temp_c) if basin.nominal_temp_c is not None else None,
        measured_temp_c=(
            float(basin.measured_temp_c) if basin.measured_temp_c is not None else None
        ),
        diving_platforms_m=[float(h) for h in basin.diving_platforms_m],
        physical_source=basin.physical_source.value,
        lane_plan_url=(basin.lane_plan_source.url if basin.lane_plan_source is not None else None),
    )


def _feature_status_out(status: FeatureStatus) -> FeatureStatusOut:
    feature = status.feature
    hours: list[TimeRangeOut] = []
    closed_reason: str | None = None
    # `schedule` is the queried day's resolution (or None when the feature states no hours).
    match status.schedule:
        case OpenDay(sessions):
            start_end = (_hhmm(s.time) for s in sessions)
            hours = [TimeRangeOut(start=start, end=end) for start, end in start_end]
        case ClosedDay(reason):
            closed_reason = reason
        case None:
            pass
    return FeatureStatusOut(
        kind=feature.kind.value,
        name=feature.name,
        surcharge_chf=float(feature.surcharge_chf) if feature.surcharge_chf is not None else None,
        temp_c=float(feature.temp_c) if feature.temp_c is not None else None,
        note=feature.note,
        open_now=status.open_at_query_time,
        hours=hours,
        closed_reason=closed_reason,
    )


def _locker_out(locker: LockerOption) -> LockerOut:
    return LockerOut(
        category=locker.category.value,
        fee_chf=float(locker.fee_chf) if locker.fee_chf is not None else None,
        deposit_chf=float(locker.deposit_chf) if locker.deposit_chf is not None else None,
        period=locker.period,
        mechanism=locker.mechanism.value if locker.mechanism is not None else None,
        raw=locker.raw,
    )


def _price_table_out(table: PriceTable) -> PriceTableOut:
    return PriceTableOut(
        entries=[
            PriceEntryOut(
                category=e.category.value, amount_chf=float(e.amount_chf), display=e.display
            )
            for e in table.entries
        ],
        valid_as_of=table.valid_as_of.isoformat() if table.valid_as_of is not None else None,
        source_url=table.source_url,
    )


def _provenance_out(provenance: Provenance) -> ProvenanceOut:
    return ProvenanceOut(
        source=provenance.source,
        curated=provenance.curated,
        valid_as_of=(
            provenance.valid_as_of.isoformat() if provenance.valid_as_of is not None else None
        ),
        fetched_at=provenance.fetched_at.isoformat() if provenance.fetched_at is not None else None,
    )


def facility_detail_out(detail: FacilityDetail, prices: PriceTable | None) -> FacilityDetailOut:
    """Shape the domain facility-detail answer for the API: the physical basins (size, lanes,
    water temperature + `physical_source` caveat), features with hours resolved for the queried
    moment, lockers, the facility price table, provenance, and the per-basin lane panels.

    Every field is a pure projection of what the domain already computes; `prices` is the
    facility's own `PriceTable` (the query surface computes a per-person `price` inside
    `find_swim_options`, but the price *table* rides on the `Facility`, so the thin router hands
    it in rather than re-reading the store)."""
    return FacilityDetailOut(
        facility_id=str(detail.facility_id),
        facility_name=detail.facility_name,
        address=detail.address,
        website=detail.website,
        basins=[_basin_out(b) for b in detail.basins],
        features=[_feature_status_out(f) for f in detail.features],
        lockers=[_locker_out(locker) for locker in detail.lockers],
        prices=_price_table_out(prices) if prices is not None else None,
        provenance=_provenance_out(detail.provenance),
        lane_panels=[_basin_panel_out(p) for p in detail.lane_panels],
        amenities=list(detail.amenities),
        accessibility=detail.accessibility,
        last_admission_before_min=(
            int(detail.last_admission_before.total_seconds() // 60)
            if detail.last_admission_before is not None
            else None
        ),
    )
