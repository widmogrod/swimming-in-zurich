"""Replay `apps/web/tests/fixtures/swim_lane_fields_pre_s2.json` — lane-stack-board S2.

WHAT IT IS
    The `lane_availability` + `lane_timeline` that two plan-bearing `/swim` options carried
    at commit `659c76a` (S1), before any S2 code existed. `test_lane_day_view.py`'s AC5 test
    asserts those two fields are still byte-identical today: S2 added `lane_day_view` and
    `lane_best_public` beside them, and `poolrank.ts` / `insightbar.ts` read the OLD pair.

    Two captures on purpose — Hallenbad City's single all-day session, and Hallenbad
    Leimbach's TWO sessions on 2026-05-05 — so a change that happens to preserve a
    day-spanning session cannot pass while breaking a split one. That is exactly the gap the
    best-public defect lived in.

WHY IT IS NOT A "REGENERATE" SCRIPT
    Same reason as its S1 sibling, and the fixture says so in its own `_note`: it is a FROZEN
    PRE-CHANGE REFERENCE. Re-dumping it from the working tree would replace "S2 left these
    two fields alone" with "the code equals itself". So this script never reads the working
    tree's `src/` or `apps/`: it extracts `659c76a` with `git archive`, serves `/swim` from
    THAT tree, and compares. "reproduced EXACTLY" is the expected outcome; a difference is a
    finding to investigate, and overwriting takes `--force`.

USAGE
    uv run python scripts/fixtures/gen_swim_lane_fields_pre_s2.py            # verify
    uv run python scripts/fixtures/gen_swim_lane_fields_pre_s2.py --check    # verify, CI-style
    uv run python scripts/fixtures/gen_swim_lane_fields_pre_s2.py --force    # rewrite (rare!)

    Offline throughout: `tests.pipeline_clients.recorded_build_clients()` replays every
    provider response from a committed fixture, so no network is touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The S1 commit — the last tree in which no S2 code existed. The committed fixture records
# this same sha in `generated_at_commit`, and the AC5 test asserts it, so the two cannot drift.
FROZEN_COMMIT = "659c76a"

FIXTURE_NAME = "swim_lane_fields_pre_s2.json"

# (at, facility, basin) — the two sessions captured, and why each one is here. See the docstring.
CAPTURES: tuple[tuple[str, str, str], ...] = (
    ("2026-08-12T12:00", "Hallenbad City", "Schwimmerbecken"),
    ("2026-05-05T12:00", "Hallenbad Leimbach", "25m-Becken"),
)

# The prose the fixture carries about itself. Kept here so a regenerated file cannot quietly
# lose the warning that makes it a frozen reference rather than a snapshot.
NOTE = (
    "FROZEN pre-change reference for lane-stack-board S2 AC5: the lane_availability + "
    "lane_timeline every plan-bearing /swim option carried at commit 659c76a (S1), BEFORE any "
    "S2 code existed. Never regenerate it to make a test pass — that would turn the reference "
    "into a copy of the code under test. Two captures on purpose: City is a single all-day "
    "session, Leimbach 2026-05-05 is TWO sessions, so a change that only holds for a "
    "day-spanning session cannot slip through."
)
RECIPE = (
    "uv run python scripts/fixtures/gen_swim_lane_fields_pre_s2.py — extracts commit 659c76a "
    "with `git archive`, builds a gold DB from that tree via "
    "swimzh.cli.build(data_dir=data/, clients=tests.pipeline_clients.recorded_build_clients()), "
    "GETs /swim?at=<at>&gender=female&age=34&eligible_only=false for each capture below, and "
    "keeps start/end/lane_availability/lane_timeline of the named facility+basin. It VERIFIES "
    "by default and refuses to overwrite without --force."
)


def dump() -> dict[str, Any]:
    """Runs INSIDE the archived tree (see `_pre_change_tree`), never in the working tree.

    Goes through the HTTP surface rather than the domain query — unlike its S1 sibling —
    because AC5 is a claim about what the WIRE carries, and `lane_availability` /
    `lane_timeline` are DTO fields serialised by `apps/web/api/swim/model.py`.
    """
    import os
    import tempfile

    from fastapi.testclient import TestClient
    from tests.pipeline_clients import recorded_build_clients

    from swimzh.cli import build

    with tempfile.TemporaryDirectory(prefix="swimzh-gold-") as tmp:
        db = Path(tmp) / "gold.sqlite"
        code = build(db_path=db, data_dir=Path("data"), clients=recorded_build_clients())
        if code != 0:
            raise SystemExit(f"the archived tree's atomic build failed with exit {code}")
        os.environ["SWIMZH_GOLD_DB"] = str(db)
        # Imported only now: the app fails fast at import/startup without a built store.
        from apps.web.main import app

        captures = []
        with TestClient(app) as client:
            for at, facility, basin in CAPTURES:
                response = client.get(
                    "/swim",
                    params={"at": at, "gender": "female", "age": 34, "eligible_only": "false"},
                )
                if response.status_code != 200:
                    raise SystemExit(f"/swim @ {at} returned {response.status_code}")
                options = [
                    {
                        "start": o["start"],
                        "end": o["end"],
                        "lane_availability": o["lane_availability"],
                        "lane_timeline": o["lane_timeline"],
                    }
                    for o in response.json()["options"]
                    if o["facility"] == facility and o["basin"] == basin
                ]
                if not options:
                    raise SystemExit(f"no option served for {facility} / {basin} @ {at}")
                captures.append(
                    {"at": at, "basin": basin, "facility": facility, "options": options}
                )

    return {
        "_note": NOTE,
        "_recipe": RECIPE,
        "captures": captures,
        "generated_at_commit": FROZEN_COMMIT,
    }


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

    payload = frozen.dump_at_commit(args.commit, "scripts.fixtures.gen_swim_lane_fields_pre_s2")
    return frozen.write_frozen(
        frozen.FIXTURES / FIXTURE_NAME, payload, force=args.force, check=args.check
    )


if __name__ == "__main__":
    sys.exit(main())
