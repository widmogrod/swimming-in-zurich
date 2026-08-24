"""Regenerate the committed iOS fixtures — OFFLINE and deterministic.

`swift test` and `xcodebuild test` run on a fresh checkout with no `gold.sqlite` (it is
git-ignored, and building one needs the network), so the Swift side ships two committed
artifacts:

* ``apps/ios/Sources/SwimZHKit/Resources/ios.sqlite`` — a real pre-resolved export, built
  from the SAME cassette-replayed gold store the Python suite serves from, over a horizon
  long enough to cover every date the golden answers fixture asks about. It is a package
  resource, so `Bundle.module` finds it under `swift test` on the host and inside the app
  bundle on device: one file, one code path, no test-only store to drift.
* ``apps/ios/Tests/SwimZHKitTests/Fixtures/haversine.json`` — coordinate pairs and the
  distance `domain/geo.haversine_km` computes for them, which the Swift port must reproduce
  to 1e-6 km (plan S2 acceptance 4).

The store is NOT staleness-gated by a Python test, because the thing that must not drift is
the ANSWERS, and those are gated twice already: `tests/etl/test_ios_export.py` proves the
export equals `find_swim_options` for every pool on every date, and the Swift golden test
replays `tests/fixtures/ios_parity/answers.json` against this very file. A store that fell
behind the domain fails the Swift golden test loudly.

Run it with ``make ios-fixtures``.
"""

from __future__ import annotations

import json
import sys
from datetime import date, time
from pathlib import Path
from typing import cast

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tests.pipeline_clients import recorded_build_clients  # noqa: E402

from swimzh.cli import build  # noqa: E402
from swimzh.domain.access import (  # noqa: E402
    ACCESS_TYPES,
    REPRESENTATIVE_ACCESS,
    ClubReserved,
    PublicSwim,
    SchoolReserved,
)
from swimzh.domain.geo import GeoPoint, haversine_km  # noqa: E402
from swimzh.domain.lane_plan import (  # noqa: E402
    LaneAvailability,
    LanePlan,
    LaneReservation,
    LaneSlotAvailability,
    PlanConfidence,
    PlanCoverage,
    PublicWindow,
    best_public_time,
    club_roster,
    lane_availability_at,
    lane_availability_timeline,
    lane_day_view,
    owner_label,
)
from swimzh.domain.models import Facility  # noqa: E402
from swimzh.domain.schedule import TimeRange, Weekday  # noqa: E402
from swimzh.etl.ios_export import _strip_doc, export_ios  # noqa: E402
from swimzh.storage.sqlite_repo import GoldRepository, open_db  # noqa: E402

#: The horizon start the golden answers fixture was generated for
#: (`tests/etl/test_ios_export.TODAY`). Fixing it pins the HORIZON — which dates the store
#: answers for — and therefore the sessions, day rows, notices and warnings the Swift golden
#: test replays.
#:
#: It does NOT make the file reproducible, and the earlier claim that it did ("byte-comparable
#: apart from `meta.built_at`") was wrong twice over. `built_at` is the small mechanism; the
#: real one is `meta.gold_valid_as_of`, which is `max(facility.provenance.valid_as_of)`
#: (`etl/ios_export._gold_valid_as_of`). The cassette-replayed build stamps provenance with
#: the WALL-CLOCK day, so every `pool.valid_as_of` cell moves when the calendar does — and
#: `_content_hash` covers those rows, so `meta.content_hash` moves with them. Measured: two
#: runs a day apart produced `e41efe27…` and `ec2b9985…` from identical inputs.
#:
#: That is cosmetic churn in a committed binary, not a correctness problem: what must not
#: drift is the ANSWERS, and those are gated twice — by `tests/etl/test_ios_export.py` and by
#: the Swift golden test. If the churn becomes annoying the fix is to pin the provenance date
#: for the OFFLINE build (an export/build change, deliberately NOT made here), never to relax
#: either gate.
TODAY = date(2026, 8, 23)

#: Long enough to cover the golden fixture's last date (2027-01-05) with room to spare, and
#: short enough that the committed store stays under 2 MB. The RELEASE store is the full
#: 400-day one `make ios-export` builds from live gold; this is the offline stand-in.
DAYS = 140

STORE = _ROOT / "apps" / "ios" / "Sources" / "SwimZHKit" / "Resources" / "ios.sqlite"
HAVERSINE = _ROOT / "apps" / "ios" / "Tests" / "SwimZHKitTests" / "Fixtures" / "haversine.json"
LANE_PLANS = _ROOT / "apps" / "ios" / "Tests" / "SwimZHKitTests" / "Fixtures" / "lane_plans.json"
ACCESS = _ROOT / "apps" / "ios" / "Tests" / "SwimZHKitTests" / "Fixtures" / "access_types.json"

#: The four times of day every (basin, weekday) case is asked about (S3b acceptance 3).
#:
#: Not evenly spaced, and not arbitrary: 06:30 is inside the early club hour most sheets open
#: with, 09:00 lands ON a boundary (half-open, so it must belong to the LATER block and to
#: exactly one), 13:00 sits in the midday public run, and 20:30 is late enough to fall outside
#: some plans entirely — which is the case that proves an absent split reads as "nothing
#: known", never as "no lanes free".
_LANE_TIMES: tuple[str, ...] = ("06:30", "09:00", "13:00", "20:30")

#: The session window the timeline and the bounded best-public search are asked for. Wider
#: than most sheets, so the clip is exercised at both ends.
_LANE_WITHIN: tuple[str, str] = ("07:00", "21:00")

#: Pairs chosen to exercise the formula, not just to agree near the origin: two Zürich pools
#: a few km apart, a ten-metre pair (where the small-angle terms dominate and a 1e-6 km
#: tolerance is a tenth of the distance itself), an identical pair (which must be exactly 0),
#: an antipodal-ish pair and a pole-crossing pair.
_PAIRS: tuple[tuple[str, tuple[float, float], tuple[float, float]], ...] = (
    ("hallenbad-city to oerlikon", (47.3739, 8.5310), (47.4103, 8.5498)),
    ("identical points", (47.3739, 8.5310), (47.3739, 8.5310)),
    ("ten metres apart", (47.3739, 8.5310), (47.37397, 8.53110)),
    ("across the equator", (-33.8688, 151.2093), (47.3769, 8.5417)),
    ("over the pole", (89.9, 0.0), (89.9, 180.0)),
    ("date line", (0.0, 179.9), (0.0, -179.9)),
)


def _write_store() -> None:
    gold = STORE.parent / "gold.build.sqlite"
    try:
        code = build(db_path=gold, data_dir=_ROOT / "data", clients=recorded_build_clients())
        if code != 0:
            raise SystemExit(f"offline gold build failed with {code}")
        with open_db(gold) as conn:
            result = export_ios(conn, STORE, today=TODAY, days=DAYS)
            # From the SAME build, so the lane fixture and the bundled store can never
            # describe different plans: one is the export of what the other derives from.
            _write_lane_plans(GoldRepository(conn).load_all())
        print(f"{STORE.relative_to(_ROOT)}: {result}")
    finally:
        gold.unlink(missing_ok=True)


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _at(value: str) -> time:
    return time.fromisoformat(value)


def _availability_doc(availability: LaneAvailability) -> dict[str, object]:
    return {
        "lane_count": availability.lane_count,
        "public_lanes": availability.public_lanes,
        "reserved_lanes": availability.reserved_lanes,
        # The OWNER LABELS, not the access objects: `lane_day.strips` carries
        # `owner_label(access)` and nothing else, so the label is the only thing the client
        # can possibly reproduce — and asserting against the object would be asserting
        # against data the export deliberately does not ship.
        "owners": [owner_label(o) for o in availability.owners],
        "public_until": (
            _hhmm(availability.public_until) if availability.public_until is not None else None
        ),
        "partial": availability.partial,
    }


def _segment_doc(segment: LaneSlotAvailability) -> dict[str, object]:
    return {
        "start": _hhmm(segment.time.start),
        "end": _hhmm(segment.time.end),
        "availability": _availability_doc(segment.availability),
    }


def _public_window_doc(window: PublicWindow | None) -> dict[str, object] | None:
    if window is None:
        return None
    return {
        "start": _hhmm(window.time.start),
        "end": _hhmm(window.time.end),
        "public_lanes": window.public_lanes,
    }


def _lane_case(basin_id: str, plan: LanePlan, weekday: Weekday) -> dict[str, object]:
    """One (basin, weekday) case: the exported row, and what `lane_plan.py` derives from it.

    The INPUT half goes through the export's own `_strip_doc`, so the fixture states the exact
    bytes the client will read rather than an idealised shape; the EXPECTED half is computed by
    the domain functions from the original `LanePlan`. That is what makes this an oracle rather
    than a mirror: the two halves come from different code, and the Swift port has to agree with
    the domain across the export's own serialisation.

    The roster is FILTERED to this weekday. `club_roster` spans the whole plan because a
    `LanePlan` carries every weekday, while a `lane_day` row is one weekday by construction —
    so the equality the client can be held to is Python's roster restricted to its own day.
    """
    view = lane_day_view(plan, weekday)
    within = TimeRange(_at(_LANE_WITHIN[0]), _at(_LANE_WITHIN[1]))
    return {
        "basin_id": basin_id,
        "weekday": int(weekday),
        "lane_count": view.lane_count,
        "strips": [_strip_doc(strip) for strip in view.strips],
        "unresolved_lanes": sorted(plan.coverage.unresolved_lanes),
        "confidence": plan.coverage.confidence.value,
        "at": [
            {
                "time": moment,
                "availability": _availability_doc(lane_availability_at(plan, weekday, _at(moment))),
            }
            for moment in _LANE_TIMES
        ],
        "timeline": {
            "within": list(_LANE_WITHIN),
            "segments": [
                _segment_doc(segment)
                for segment in lane_availability_timeline(plan, weekday, within).segments
            ],
        },
        "best_public_day": _public_window_doc(best_public_time(plan, weekday)),
        "best_public_within": _public_window_doc(best_public_time(plan, weekday, within)),
        "roster": [
            {
                "club": slot.club,
                "weekday": int(slot.weekday),
                "start": _hhmm(slot.time.start),
                "end": _hhmm(slot.time.end),
                "lanes": list(slot.lanes),
            }
            for slot in club_roster(plan)
            if slot.weekday == weekday
        ],
    }


#: A plan the CITY DOES NOT HAVE, and the reason this fixture is not drawn from gold alone.
#:
#: `partial` is a rendered field on both `LaneAvailabilityOut` and `LaneTimelineSegmentOut`, and
#: it is derived from `PlanCoverage.unresolved_lanes` — but every one of the six basins that
#: carries a parsed Belegungsplan today resolved COMPLETELY, so a fixture built only from real
#: data would assert `partial == false` everywhere and prove nothing about the flag. Lane 4 here
#: is unreadable, so `partial` is true at every instant NO hold covers it and false at 13:00,
#: where a school block does — the discrimination the real data cannot make, inside one basin.
_SYNTHETIC_BASIN = "synthetic-partial-4"


def _synthetic_plan() -> LanePlan:
    return LanePlan(
        lane_count=4,
        reservations=(
            LaneReservation(
                weekdays=frozenset(Weekday),
                time=TimeRange(_at("06:00"), _at("12:00")),
                lanes=frozenset({1, 2}),
                access=PublicSwim(),
            ),
            # Adjacent to the block above on lanes 1-2, so `public_until` must MERGE the two
            # and answer 14:00 at 07:15 rather than 12:00.
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(_at("12:00"), _at("14:00")),
                lanes=frozenset({1, 2, 3}),
                access=PublicSwim(),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(_at("06:00"), _at("09:00")),
                lanes=frozenset({3}),
                access=ClubReserved(club="ASVZ"),
            ),
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY, Weekday.THURSDAY}),
                time=TimeRange(_at("09:00"), _at("11:00")),
                lanes=frozenset({3}),
                access=SchoolReserved(),
            ),
            # The one block that COVERS the unresolved lane, so `partial` is false at 13:00
            # and true at the other three probes. Without it the flag would be constant for
            # this basin and the fixture would prove only that it can be true.
            LaneReservation(
                weekdays=frozenset({Weekday.TUESDAY}),
                time=TimeRange(_at("12:30"), _at("13:30")),
                lanes=frozenset({4}),
                access=SchoolReserved(),
            ),
        ),
        valid_from=None,
        coverage=PlanCoverage(
            confidence=PlanConfidence.PARTIAL,
            cells_total=100,
            cells_resolved=75,
            unresolved_lanes=frozenset({4}),
        ),
    )


def lane_plans_doc(facilities: tuple[Facility, ...]) -> dict[str, object]:
    """The lane-plan fixture as a document, WITHOUT writing it.

    Split out from the writer so `apps/web/tests/test_ios_fixture_contracts.py` can recompute it
    from the same cassette-replayed gold build the web suite already has and fail when the
    committed copy has fallen behind `swimzh.domain.lane_plan`. Without that, editing the domain
    left the Swift fixture stale, the Swift test green against it, and the two copies drifting
    together — the exact hole `apps/web/tests/test_field_coverage_contract.py` was added to
    close one slice earlier.
    """
    cases: list[dict[str, object]] = []
    for facility in facilities:
        for basin in facility.basins:
            plan = basin.lane_plan
            if not isinstance(plan, LanePlan):
                continue
            cases.extend(_lane_case(str(basin.basin_id), plan, weekday) for weekday in Weekday)
    cases.extend(_lane_case(_SYNTHETIC_BASIN, _synthetic_plan(), weekday) for weekday in Weekday)
    return {
        "_note": (
            "GENERATED from swimzh.domain.lane_plan by scripts/ios_fixtures.py — do "
            "NOT hand-edit. The INPUT half (`strips`) is written by the export's own "
            "`_strip_doc`; the EXPECTED half is computed by the domain functions from "
            "the original LanePlan. Replayed by the Swift LanePlanTests. Regenerate "
            "with `make ios-fixtures`."
        ),
        "synthetic_basin_id": _SYNTHETIC_BASIN,
        "cases": cases,
    }


def _write_lane_plans(facilities: tuple[Facility, ...]) -> None:
    doc = lane_plans_doc(facilities)
    LANE_PLANS.parent.mkdir(parents=True, exist_ok=True)
    LANE_PLANS.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cases = cast(list[dict[str, object]], doc["cases"])
    basins = {case["basin_id"] for case in cases}
    print(f"{LANE_PLANS.relative_to(_ROOT)}: {len(cases)} cases over {len(basins)} basins")


def _write_haversine() -> None:
    cases = [
        {
            "name": name,
            "a": {"lat": a[0], "lon": a[1]},
            "b": {"lat": b[0], "lon": b[1]},
            "km": haversine_km(GeoPoint(lat=a[0], lon=a[1]), GeoPoint(lat=b[0], lon=b[1])),
        }
        for name, a, b in _PAIRS
    ]
    HAVERSINE.parent.mkdir(parents=True, exist_ok=True)
    HAVERSINE.write_text(
        json.dumps(
            {
                "_note": (
                    "GENERATED from swimzh.domain.geo.haversine_km by scripts/ios_fixtures.py "
                    "— do NOT hand-edit. Replayed by the Swift GeoTests, which must agree to "
                    "1e-6 km. Regenerate with `make ios-fixtures`."
                ),
                "tolerance_km": 1e-6,
                "cases": cases,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{HAVERSINE.relative_to(_ROOT)}: {len(cases)} pairs")


def access_types_doc() -> dict[str, object]:
    """The access-types explainer, generated from `domain.access.ACCESS_TYPES`.

    The phone ships its own copy of this prose (it has no network, and `/access-types` is a web
    endpoint), so without a generated contract the two would drift the first time either was
    edited — and the drift would be invisible, because both sides would still be self-consistent.
    The CLASS NAME rides along beside the key: it is what `session.access_kind` carries, and
    therefore the only thing the client can join on.

    Pure, and separate from the writer, so `apps/web/tests/test_ios_fixture_contracts.py` can
    recompute it and fail when the committed copy is stale. It reads `swimzh.domain.access` and
    nothing else, so that gate needs no gold DB and no build.
    """
    cases = [
        {
            "class_name": type(access).__name__,
            "key": info.key,
            "label": info.label,
            "description": info.description,
        }
        for access, info in zip(REPRESENTATIVE_ACCESS, ACCESS_TYPES, strict=True)
    ]
    return {
        "_note": (
            "GENERATED from swimzh.domain.access.ACCESS_TYPES by scripts/ios_fixtures.py "
            "— do NOT hand-edit. Replayed by the Swift AccessExplainerTests, which "
            "asserts the phone's copy of this prose has not drifted from the domain's. "
            "Regenerate with `make ios-fixtures`."
        ),
        "types": cases,
    }


def _write_access_types() -> None:
    doc = access_types_doc()
    ACCESS.parent.mkdir(parents=True, exist_ok=True)
    ACCESS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    types = cast(list[dict[str, object]], doc["types"])
    print(f"{ACCESS.relative_to(_ROOT)}: {len(types)} access types")


def main() -> int:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    _write_store()
    _write_haversine()
    _write_access_types()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
