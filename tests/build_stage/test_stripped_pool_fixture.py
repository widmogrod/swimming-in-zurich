"""delete-curated-schedule-tier S1 acceptance (against a stripped *fixture*, not real `data/`).

A pool blob reduced to the kept allowlist — `facility_id` + basins with only
`basin_id`/`name`/`lane_plan_source` — must:

1. validate under `FacilityDTO` (address/source/rules/physicals now optional);
2. build through `build_spine`, taking its `address` from the WFS roster (never a served "");
3. gain basin physicals (kind/dimensions/lanes) from the WFS `infrastruktur` prose via the
   wired `apply_physicals` — the "prose pool" (city/bungertwies) analogue;
4. derive `awaiting_scrape` freshness (indoor, no rule yet) and, on `/swim`, report that
   freshness — NEVER "closed", no option, no error.

No real `data/pools/*.yaml` is stripped here (that is S3); the fixture is inline.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from swimzh.boundary.curated_dto import FacilityDTO
from swimzh.build.seed import build_spine
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry, RosterEntry, ScheduleFreshness
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import (
    BasinKind,
    BasinSource,
    PoolIdentity,
    PoolKind,
    reconstruct_pool_id,
)
from swimzh.domain.person import Person
from swimzh.domain.query import SwimQuery, find_swim_options
from swimzh.domain.registry import Registry
from swimzh.providers.curated import _map_facility
from swimzh.storage import codec

ZURICH = ZoneInfo("Europe/Zurich")

# The allowlist end-state: facility_id + basins carrying only the crosswalk binding. No address,
# no source, no rules, no physicals — everything else is sourced or a recorded drop.
_STRIPPED_CITY = {
    "facility_id": "hallenbad-city",
    "basins": [
        {
            "basin_id": "city-schwimmer",
            "name": "Schwimmerbecken",
            "lane_plan_source": {"url": "https://example.test/city-schwimmerbecken.pdf"},
        }
    ],
}
# The WFS roster row: address (authoritative) + `infrastruktur` prose (basin physicals source).
_ROSTER_ADDRESS = "Sihlstrasse 71, 8001 Zürich"
_PROSE = "Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C, Nichtschwimmerbecken 10,5 x 7 m 30°C"


def _entry(kind: PoolKind) -> PoolCatalogEntry:
    return PoolCatalogEntry(
        pool_id="hallenbad-city",
        name="Hallenbad City",
        kind=kind,
        address=_ROSTER_ADDRESS,
        geo=GeoPoint(lat=47.3739, lon=8.5320),
        url=None,
        description=_PROSE,
        phone=None,
        poi_id="hb001",
    )


def _build(kind: PoolKind):  # type: ignore[no-untyped-def]
    dto = FacilityDTO.model_validate(_STRIPPED_CITY)
    identity = PoolIdentity(
        facility_id=reconstruct_pool_id("hallenbad-city"), name="Hallenbad City", kind=kind
    )
    facility = _map_facility(dto, identity)
    spine = build_spine((_entry(kind),), (facility,), Registry([identity]))
    return spine.pools[0]


def test_stripped_blob_validates_with_optional_fields() -> None:
    dto = FacilityDTO.model_validate(_STRIPPED_CITY)
    assert dto.address is None  # omitted → sourced later, never ""
    assert dto.source is None
    assert dto.basins[0].rules == []  # no schedule in a binding-only file
    assert dto.basins[0].lane_plan_source is not None  # the kept crosswalk binding


def test_address_and_physicals_come_from_the_wfs_roster() -> None:
    row = _build(PoolKind.INDOOR)
    built = codec.loads(row.facility_doc)

    # (2) address is the roster's, never the omitted-curated "".
    assert built.address == _ROSTER_ADDRESS

    basin = built.basins[0]
    # (3) physicals sourced from the prose via apply_physicals (the location-only path is not
    #     enough — a curated facility takes the codec.dumps branch).
    assert basin.kind is BasinKind.LAP
    assert basin.dimensions is not None and basin.dimensions.length_m == Decimal("50")
    assert basin.lanes == 6
    assert basin.physical_source is BasinSource.PARSED_PROSE  # honest "auto-extracted" caveat
    # The kept crosswalk binding survives the build untouched.
    assert basin.lane_plan_source is not None
    assert basin.lane_plan_source.url == "https://example.test/city-schwimmerbecken.pdf"


def test_indoor_stripped_pool_is_awaiting_scrape() -> None:
    row = _build(PoolKind.INDOOR)
    assert codec.schedule_freshness(row.facility_doc) is ScheduleFreshness.AWAITING_SCRAPE


def test_school_stripped_pool_is_no_source() -> None:
    row = _build(PoolKind.SCHOOL)
    assert codec.schedule_freshness(row.facility_doc) is ScheduleFreshness.NO_SOURCE


def test_swim_reports_freshness_never_closed_for_a_stripped_pool() -> None:
    # (4) /swim for a non-scraped pool: its freshness status, NOT "closed", no option, no error.
    row = _build(PoolKind.INDOOR)
    facility = codec.loads(row.facility_doc)
    roster = (
        RosterEntry(entry=_entry(PoolKind.INDOOR), freshness=ScheduleFreshness.AWAITING_SCRAPE),
    )
    calendar = ZurichCalendar(public_holidays={}, school_holidays=[], known_years=[2026])
    result = find_swim_options(
        SwimQuery(
            person=Person(gender=None, age=None), at=datetime(2026, 3, 11, 14, 0, tzinfo=ZURICH)
        ),
        (facility,),
        calendar,
        roster,
    )
    assert result.options == ()  # no rule → no option
    mine = [s for s in result.statuses if s.facility_name == "Hallenbad City"]
    assert mine and mine[0].status == "awaiting_scrape"
    assert all(s.status != "closed" for s in result.statuses)  # schedule-less is never "closed"
