"""Pools listing use-case: filter the catalog and shape the response."""

from __future__ import annotations

from datetime import datetime
from typing import assert_never

from apps.web.api.pools.model import (
    AdmissionOut,
    BasinLanePanelOut,
    BasinOut,
    ClubSlotOut,
    FacilityDetailOut,
    FeatureStatusOut,
    LaneDayViewOut,
    LanePanelOut,
    LaneSegmentOut,
    LaneStripOut,
    LiveWaterTempOut,
    LockerOut,
    OperatingSeasonOut,
    PoolOut,
    PoolsOut,
    PriceEntryOut,
    PriceTableOut,
    ProvenanceOut,
    PublicWindowOut,
    RentalFeeOut,
    RentalOut,
    TimeRangeOut,
)
from apps.web.services.ports import TemperatureProvider
from swimzh.domain.access import PublicSwim
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.catalog import RosterEntry, ScheduleFreshness
from swimzh.domain.lane_plan import (
    ClubSlot,
    LanePanel,
    LaneStrip,
    PublicWindow,
    owner_label,
)
from swimzh.domain.lockers import LockerOption
from swimzh.domain.models import Basin, OperatingSeason, PoolIdentity, Provenance
from swimzh.domain.pricing import PriceTable
from swimzh.domain.query import (
    BasinLanePanel,
    FacilityDetail,
    FeatureStatus,
    LiveTemp,
    TempResult,
    TempUnavailable,
    TempUnavailableCode,
    read_temperature,
)
from swimzh.domain.rentals import Gratis, Priced, RentalItem, Unstated
from swimzh.domain.schedule import (
    ClosedDay,
    DatePrecision,
    OpenDay,
    OpenUnscheduledDay,
    TimeRange,
)


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
        freshness=row.freshness.value,
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
        case OpenUnscheduledDay():
            # Open per the facility's operating season, hours unpublished: nothing to list
            # and no closed reason — `hours` stays empty and `open_now` is the domain's
            # honest None. (Unreachable today: a feature resolves only when it HAS hours.)
            pass
        case None:
            pass
        case _ as unreachable:
            assert_never(unreachable)
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


def _rental_out(rental: RentalItem) -> RentalOut:
    """Project the closed fee union onto the wire: the kind string plus the amount (non-null
    exactly in the `Priced` arm — a stated-gratis rental is `("gratis", None)`, never conflated
    with the unstated `("unstated", None)`)."""
    fee: RentalFeeOut
    amount: float | None = None
    match rental.fee:
        case Priced(amount_chf):
            fee, amount = "priced", float(amount_chf)
        case Gratis():
            fee = "gratis"
        case Unstated():
            fee = "unstated"
        case _ as unreachable:
            assert_never(unreachable)
    return RentalOut(
        kind=rental.kind.value,
        fee=fee,
        fee_chf=amount,
        deposit_chf=float(rental.deposit_chf) if rental.deposit_chf is not None else None,
        period=rental.period,
        raw=rental.raw,
    )


def _price_table_out(table: PriceTable) -> PriceTableOut:
    return PriceTableOut(
        entries=[
            PriceEntryOut(
                category=e.category.value,
                amount_chf=float(e.amount_chf),
                display=e.display,
                min_age=e.min_age,
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


def resolve_live_water_temp(
    provider: TemperatureProvider | None, identity: PoolIdentity, now: datetime
) -> TempResult:
    """Resolve the facility's live water temperature, fail-open. A `None` provider (none wired /
    not configured) is a valid state — it becomes an explainable `TempUnavailable`, never an
    exception; otherwise the domain `read_temperature` keys by `identity.baditicker_poiid`."""
    if provider is None:
        return TempUnavailable(
            reason="live temperature not configured",
            code=TempUnavailableCode.NOT_CONFIGURED,
        )
    return read_temperature(provider, identity, now)


def _live_water_temp_out(result: TempResult) -> LiveWaterTempOut:
    match result:
        case LiveTemp(reading, age):
            return LiveWaterTempOut(
                available=True,
                # An empty feed cell stays a live answer: celsius=None, NOT unavailable.
                celsius=float(reading.celsius) if reading.celsius is not None else None,
                measured_at=reading.measured_at.isoformat(),
                age_min=int(age.total_seconds() // 60),
                is_open=reading.is_open,
                is_stale=result.is_stale(),
                source=reading.source,
                reason=None,
            )
        case TempUnavailable(reason, code):
            return LiveWaterTempOut(
                available=False,
                celsius=None,
                measured_at=None,
                age_min=None,
                is_open=None,
                is_stale=None,
                source=None,
                reason=reason,
                reason_code=code.value,
            )


def _admission_out(admission: Admission) -> tuple[AdmissionOut, PriceTable | None]:
    """Project the closed union onto the wire: the kind string plus the tariff table (the table
    exists exactly in the `Tariff` arm — a free pool is `("free", None)`, never conflated with
    `("unknown", None)`)."""
    match admission:
        case Tariff(table):
            return "tariff", table
        case Free():
            return "free", None
        case Unknown():
            return "unknown", None
        case _ as unreachable:
            assert_never(unreachable)


def _operating_season_out(season: OperatingSeason) -> OperatingSeasonOut:
    """Project the page-stated season: months always; days ONLY at `DAY` precision, so a
    `MONTH` window is never rendered more precisely than the page published it."""
    window = season.window
    day_precise = window.precision is DatePrecision.DAY
    return OperatingSeasonOut(
        start_month=window.start.month,
        end_month=window.end.month,
        precision=window.precision.value,
        weather=season.weather.value,
        start_day=window.start.day if day_precise else None,
        end_day=window.end.day if day_precise else None,
    )


def facility_detail_out(
    detail: FacilityDetail,
    admission: Admission,
    live_water_temp: TempResult,
    freshness: ScheduleFreshness,
    operating_season: OperatingSeason | None,
) -> FacilityDetailOut:
    """Shape the domain facility-detail answer for the API: the physical basins (size, lanes,
    water temperature + `physical_source` caveat), features with hours resolved for the queried
    moment, lockers, the facility admission (kind + tariff table), provenance, and the per-basin
    lane panels.

    Every field is a pure projection of what the domain already computes; `admission` — and
    `operating_season` (sharedsource-fanout S3), which rides the same way — is the facility's
    own fact (the query surface computes a per-person `price` inside `find_swim_options`, but
    the fact rides on the `Facility`, so the thin router hands it in rather than re-reading
    the store)."""
    admission_kind, price_table = _admission_out(admission)
    return FacilityDetailOut(
        facility_id=str(detail.facility_id),
        facility_name=detail.facility_name,
        address=detail.address,
        freshness=freshness.value,
        basins=[_basin_out(b) for b in detail.basins],
        features=[_feature_status_out(f) for f in detail.features],
        lockers=[_locker_out(locker) for locker in detail.lockers],
        rentals=[_rental_out(rental) for rental in detail.rentals],
        admission=admission_kind,
        prices=_price_table_out(price_table) if price_table is not None else None,
        operating_season=(
            _operating_season_out(operating_season) if operating_season is not None else None
        ),
        provenance=_provenance_out(detail.provenance),
        lane_panels=[_basin_panel_out(p) for p in detail.lane_panels],
        last_admission_before_min=(
            int(detail.last_admission_before.total_seconds() // 60)
            if detail.last_admission_before is not None
            else None
        ),
        live_water_temp=_live_water_temp_out(live_water_temp),
    )
