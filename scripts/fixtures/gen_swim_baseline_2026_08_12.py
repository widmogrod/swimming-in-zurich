"""Replay `apps/web/tests/fixtures/swim_baseline_2026-08-12.json` — lane-stack-board S1.

WHAT IT IS
    Every `/swim` option the domain query produced at 2026-08-12T12:00 **before** S1's
    `_carry_bindings` change, as `(facility_id, basin_id, start, end, access)` tuples read
    from a fresh offline `build`. `test_lane_basin_options.py` asserts containment against
    it: nothing in the baseline may be lost or drift, and everything gained must be a basin
    that declares a `lane_plan_source` on a facility that already had options.

WHY IT IS NOT A "REGENERATE" SCRIPT
    The fixture is a FROZEN PRE-CHANGE REFERENCE. It is evidence precisely because the code
    that produced it did not contain `_carry_bindings`. Re-dumping it from the working tree
    would turn "S1 added only lane-bound basins" into "the code equals itself" — a test that
    can never fail. So this script does not read the working tree at all: it extracts commit
    `8b7f954` (the last commit before S1) with `git archive`, imports the pipeline FROM THERE,
    and dumps. Success looks like "reproduced EXACTLY"; a difference is a finding, not a
    refresh, and writing it needs `--force` and a reason.

    `8b7f954` is `plan(lane-stack-board): start implementation` — the parent of `659c76a`
    (`feat(lane-stack-board): S1 …`), i.e. the tree S1 was written against.

USAGE
    uv run python scripts/fixtures/gen_swim_baseline_2026_08_12.py            # verify
    uv run python scripts/fixtures/gen_swim_baseline_2026_08_12.py --check    # verify, CI-style
    uv run python scripts/fixtures/gen_swim_baseline_2026_08_12.py --force    # rewrite (rare!)

    Offline: the build is driven by `tests.pipeline_clients.recorded_build_clients()`, so
    every WFS layer, pool page, price page and Belegungsplan comes from a committed fixture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Runnable as a plain script (`python scripts/fixtures/<this>.py`) as well as importable as
# `scripts.fixtures.<this>` — the sandbox imports it by module path.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The tree S1 was written against — the parent of the S1 commit. See the module docstring.
FROZEN_COMMIT = "8b7f954"

# Wednesday 2026-08-12 12:00 Europe/Zurich, the instant the baseline was measured at. Oerlikon
# is shut that day, which is why the baseline is per-date and asserts no store-wide total.
AT_ISO = "2026-08-12T12:00"

FIXTURE_NAME = "swim_baseline_2026-08-12.json"


def dump() -> dict[str, Any]:
    """Runs INSIDE the archived tree (see `_pre_change_tree`), never in the working tree.

    Mirrors `apps/web/tests/conftest.py::gold_db` — one offline atomic `build` — and then the
    same `find_swim_options` call the test makes, so the baseline and the assertion are
    produced by one code path rather than two that must be kept in step.
    """
    import tempfile
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from apps.web.services.gold_store import GoldSwimStore
    from tests.pipeline_clients import recorded_build_clients

    from swimzh.cli import build
    from swimzh.domain.person import Gender, Person
    from swimzh.domain.query import SwimQuery, find_swim_options

    at = datetime.fromisoformat(AT_ISO).replace(tzinfo=ZoneInfo("Europe/Zurich"))
    with tempfile.TemporaryDirectory(prefix="swimzh-gold-") as tmp:
        db = Path(tmp) / "gold.sqlite"
        code = build(db_path=db, data_dir=Path("data"), clients=recorded_build_clients())
        if code != 0:
            raise SystemExit(f"the archived tree's atomic build failed with exit {code}")
        store = GoldSwimStore.open(db)
        result = find_swim_options(
            SwimQuery(person=Person(gender=Gender.FEMALE, age=34), at=at),
            store.facilities(),
            store.calendar(),
        )
    options = sorted(
        [
            str(o.facility_id),
            str(o.basin_id),
            o.session.time.start.strftime("%H:%M"),
            o.session.time.end.strftime("%H:%M"),
            type(o.session.access).__name__,
        ]
        for o in result.options
    )
    return {"at": at.isoformat(), "options": options}


def main(argv: list[str] | None = None) -> int:
    from scripts.fixtures import _pre_change_tree as frozen

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default=FROZEN_COMMIT, help="the pre-change commit to replay")
    parser.add_argument("--check", action="store_true", help="exit non-zero on any difference")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the committed fixture — only with a known reason for the difference",
    )
    args = parser.parse_args(argv)

    payload = frozen.dump_at_commit(args.commit, "scripts.fixtures.gen_swim_baseline_2026_08_12")
    return frozen.write_frozen(
        frozen.FIXTURES / FIXTURE_NAME, payload, force=args.force, check=args.check
    )


if __name__ == "__main__":
    sys.exit(main())
