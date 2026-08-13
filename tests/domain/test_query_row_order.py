"""Rule O1 at the domain level: a status ranks on geography, exactly like an option.

The defect this pins (board-order-and-defects S2): `FacilityStatus` carried no distance and
the status list was never sorted, so a pool's position on the board was decided by whether it
happened to be open that day rather than by where it is.

The tests are synthetic on purpose. `find_swim_options` builds statuses in **two** places —
inside the facility loop (a pool that is closed today) and in `_schedule_less_statuses`, which
runs outside it and reads `RosterEntry`, not `Facility`. Against real data the two halves land
in mostly-separate distance bands, so a fix applied to only the easy half still LOOKS ordered.
The facilities and roster entries below are placed so the two halves must INTERLEAVE: nothing
here passes unless both halves rank on the same key.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from swimzh.domain.access import PublicSwim
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import PoolCatalogEntry, RosterEntry, ScheduleFreshness
from swimzh.domain.geo import GeoPoint, haversine_km
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import QueryResult, SwimQuery, find_swim_options
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday

ZURICH = ZoneInfo("Europe/Zurich")
ADULT = Person(gender=Gender.MALE, age=40)

#: The place the UI actually sends (`PLACE_PRESETS[0]`, Zürich HB).
HB = GeoPoint(47.3779, 8.5403)

# Four positions due north of HB, ~1.1 km apart. Named by how far they are, because the whole
# point of these tests is which row sits where.
NEAR = GeoPoint(47.3879, 8.5403)
MID = GeoPoint(47.3979, 8.5403)
FAR = GeoPoint(47.4079, 8.5403)
FARTHEST = GeoPoint(47.4179, 8.5403)

# The queried moment: a Wednesday. `MONDAY_ONLY` below is therefore closed on it.
WEDNESDAY = datetime(2026, 8, 12, 12, 0, tzinfo=ZURICH)
MONDAY = datetime(2026, 8, 10, 12, 0, tzinfo=ZURICH)

MONDAY_ONLY = ScheduleRule(
    weekdays=frozenset({Weekday.MONDAY}),
    time=TimeRange(time(6, 0), time(22, 0)),
    access=PublicSwim(),
)


def _facility(pool_id: str, name: str, geo: GeoPoint | None) -> Facility:
    """A pool open on MONDAYS ONLY — so the Wednesday query reports it `closed`, taking the
    in-loop status branch, while the Monday query yields options for the same pool."""
    return Facility(
        identity=PoolIdentity(facility_id=PoolId(pool_id), name=name, kind=PoolKind.INDOOR),
        address="Teststrasse 1, Zürich",
        provenance=Provenance(source="test", curated=True),
        geo=geo,
        basins=(
            Basin(basin_id=BasinId(f"{pool_id}-main"), name="Hauptbecken", rules=(MONDAY_ONLY,)),
        ),
    )


def _roster_entry(pool_id: str, name: str, geo: GeoPoint | None) -> RosterEntry:
    """A roster pool with NO schedule — the `_schedule_less_statuses` half, built from a
    `PoolCatalogEntry` outside the facility loop."""
    return RosterEntry(
        entry=PoolCatalogEntry(
            pool_id=pool_id,
            name=name,
            kind=PoolKind.OUTDOOR,
            address="",
            geo=geo,
            url=None,
            description=None,
            phone=None,
        ),
        freshness=ScheduleFreshness.NO_SOURCE,
    )


# The two halves, deliberately interleaved by distance: closed, schedule-less, closed,
# schedule-less. Sorting only the in-loop half cannot produce the expected order.
CLOSED_NEAR = _facility("closed-near", "Bad Near", NEAR)
CLOSED_FAR = _facility("closed-far", "Bad Far", FAR)
LESS_MID = _roster_entry("less-mid", "Bad Mid", MID)
LESS_FARTHEST = _roster_entry("less-farthest", "Bad Farthest", FARTHEST)


def _answer(
    facilities: tuple[Facility, ...],
    roster: tuple[RosterEntry, ...],
    *,
    at: datetime = WEDNESDAY,
    near: GeoPoint | None = HB,
) -> QueryResult:
    return find_swim_options(
        SwimQuery(person=ADULT, at=at, near=near),
        facilities,
        ZurichCalendar(public_holidays={}, school_holidays=(), known_years=(2026,)),
        roster,
    )


def test_both_status_sources_interleave_by_distance() -> None:
    """AC1/AC2: the two halves of the status list rank on ONE key.

    The expected order alternates between the halves, so this fails if either half is left
    unranked — including the `_schedule_less_statuses` half, which is the one a fix naturally
    misses because it never sees a `Facility`.
    """
    result = _answer((CLOSED_NEAR, CLOSED_FAR), (LESS_MID, LESS_FARTHEST))

    assert [s.facility_name for s in result.statuses] == [
        "Bad Near",  # in-loop closed
        "Bad Mid",  # schedule-less
        "Bad Far",  # in-loop closed
        "Bad Farthest",  # schedule-less
    ]


def test_every_status_carries_the_distance_its_geo_implies() -> None:
    """AC2: no geo-bearing facility ships `distance_km: None`, from EITHER source, and the
    number is the same haversine an option would carry — not a re-derivation."""
    result = _answer((CLOSED_NEAR, CLOSED_FAR), (LESS_MID, LESS_FARTHEST))
    by_name = {s.facility_name: s.distance_km for s in result.statuses}

    assert by_name == {
        "Bad Near": haversine_km(HB, NEAR),
        "Bad Mid": haversine_km(HB, MID),
        "Bad Far": haversine_km(HB, FAR),
        "Bad Farthest": haversine_km(HB, FARTHEST),
    }


def test_a_closed_pool_carries_the_distance_its_own_option_carries_when_open() -> None:
    """AC4, at the domain level: the same pool, the same place, two days — one number.

    This is the property that makes the board stable across a date change; asserting the two
    values independently against a constant would not.
    """
    closed = _answer((CLOSED_NEAR,), ()).statuses
    options = _answer((CLOSED_NEAR,), (), at=MONDAY).options

    assert [s.facility_name for s in closed] == ["Bad Near"]
    assert options and {o.facility_name for o in options} == {"Bad Near"}
    assert closed[0].distance_km == options[0].distance_km


def test_a_pool_without_geo_keeps_none_and_sorts_last_by_name() -> None:
    """O4: an unknown position is not zero. It sorts LAST within the group, by name — absence
    must never outrank a real, worse value, and it must never be fabricated as 0.0."""
    no_geo_z = _facility("no-geo-z", "Zed Bad", None)
    no_geo_a = _roster_entry("no-geo-a", "Aare Bad", None)
    result = _answer((CLOSED_FAR, no_geo_z), (no_geo_a,))

    assert [s.facility_name for s in result.statuses] == [
        "Bad Far",  # the only pool whose position is known
        "Aare Bad",  # then the unknowns, by name
        "Zed Bad",
    ]
    unknown = [s for s in result.statuses if s.facility_name in {"Aare Bad", "Zed Bad"}]
    assert [s.distance_km for s in unknown] == [None, None]
    # The specific mis-fix O4 forbids: a `0.0` would have sorted these two FIRST, in front of
    # the pool we can actually locate.
    assert all(s.distance_km != 0 for s in unknown)


def test_two_pools_the_same_distance_away_are_ordered_by_name() -> None:
    """The second half of the key. Ties are real — the served answer has several pairs a few
    metres apart — and the tie-break has to be something a reader can predict, so it is the
    name. Asserted at the domain level because the wire rounds to 2 dp and would manufacture
    ties that are not ties, hiding a missing tie-break behind rounding.
    """
    result = _answer(
        (_facility("tie-z", "Zed Bad", MID), _facility("tie-a", "Aare Bad", MID)),
        (_roster_entry("tie-m", "Mittel Bad", MID),),
    )

    assert [s.facility_name for s in result.statuses] == ["Aare Bad", "Mittel Bad", "Zed Bad"]
    assert len({s.distance_km for s in result.statuses}) == 1


def test_a_query_with_no_place_leaves_every_status_unranked_and_ordered_by_name() -> None:
    """No `near` means no distance is knowable for ANY pool — so the fallback is name order,
    not the arbitrary iteration order the defect shipped."""
    result = _answer((CLOSED_FAR, CLOSED_NEAR), (LESS_MID,), near=None)

    assert [s.facility_name for s in result.statuses] == ["Bad Far", "Bad Mid", "Bad Near"]
    assert all(s.distance_km is None for s in result.statuses)
