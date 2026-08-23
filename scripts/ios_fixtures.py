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
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tests.pipeline_clients import recorded_build_clients  # noqa: E402

from swimzh.cli import build  # noqa: E402
from swimzh.domain.geo import GeoPoint, haversine_km  # noqa: E402
from swimzh.etl.ios_export import export_ios  # noqa: E402
from swimzh.storage.sqlite_repo import open_db  # noqa: E402

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
        print(f"{STORE.relative_to(_ROOT)}: {result}")
    finally:
        gold.unlink(missing_ok=True)


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


def main() -> int:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    _write_store()
    _write_haversine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
