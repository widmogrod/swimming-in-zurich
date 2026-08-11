"""Re-derive the `lane_day_view` + `lane_best_public` in `swim_day.json` — lane-stack-board S4.

WHAT IT IS
    `apps/web/tests/fixtures/swim_day.json` is HAND-AUTHORED (its `_provenance` says so): an
    illustrative `/swim` answer the TypeScript block suites and the two dev preview routes
    render. S4 needed a per-lane day view on it, and rather than invent one, derived it
    MECHANICALLY from the file's own pre-existing `lane_timeline` — which is why the stack's
    lane counts and the timeline's counts agree exactly, in the fixture as in real data.

    This script is that derivation, committed. Unlike its two frozen siblings in this
    directory it IS a plain regenerator: the input is the same file's `lane_timeline`, not a
    past commit, so re-running it can only ever restate what the timeline already says. It
    cannot launder a code change into a fixture, because no product code takes part.

THE DERIVATION, in one paragraph
    Take the timeline segments of every session of the target basin, in time order. In a
    segment reporting `public_lanes = k` of `lane_count = n`, lanes 1..k are public and lanes
    k+1..n are reserved — the lowest-numbered lanes are the public ones, a convention chosen
    once so the picture is stable rather than arbitrary. A reserved hold carries its lane's
    owner from `OWNERS` below. Adjacent holds of one lane that agree on access and owner are
    merged, so a lane reads as few long bars rather than one bar per timeline boundary.
    Finally each session's `lane_best_public` is the LONGEST window, inside that session's own
    hours, at that session's peak public-lane count.

THE CLUB NAMES ARE INVENTED
    `OWNERS` is fiction. No lane owner in this fixture was scraped from a Belegungsplan, and
    none may be read as a fact about a real Zürich club. They exist so the renderer has a name
    to lay out and a test has a string to assert. Keep them obviously synthetic.

USAGE
    uv run python scripts/fixtures/derive_swim_day_lane_view.py           # rewrite in place
    uv run python scripts/fixtures/derive_swim_day_lane_view.py --check   # verify only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "apps" / "web" / "tests" / "fixtures" / "swim_day.json"

# The one basin in this fixture that publishes a lane split.
FACILITY = "Hallenbad Oerlikon"
BASIN = "50m-Becken"

# The weekday the day view is stamped with. `swim_day.json` is a hand-authored answer with no
# date of its own, so this is a declaration, not a derivation: 2 = Wednesday, matching the
# `lane_day_view.weekday` the fixture has carried since S4.
WEEKDAY = 2

# INVENTED club names, one per lane that is ever reserved here. See the docstring: these are
# not real bookings by real clubs. Lanes absent from this map are never reserved.
OWNERS: dict[int, str] = {
    5: "SV Limmat",
    6: "Schule Liguster",
    7: "Wasserball ZH",
    8: "SC Oerlikon",
}

PUBLIC = "PublicSwim"
RESERVED = "ClubReserved"


def _to_min(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _segments(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every timeline segment of the target basin's sessions, in time order.

    The day view spans the whole weekday, not one session: two sessions of one basin share a
    row canvas on the board, and `drawLaneStack` clips the stack to the session it is drawing.
    """
    segments = [seg for o in options for seg in o["lane_timeline"]["segments"]]
    return sorted(segments, key=lambda s: _to_min(s["start"]))


def _strips(segments: list[dict[str, Any]], lane_count: int) -> list[dict[str, Any]]:
    strips: list[dict[str, Any]] = []
    for lane in range(1, lane_count + 1):
        holds: list[dict[str, Any]] = []
        for seg in segments:
            is_public = lane <= seg["public_lanes"]
            hold = {
                "start": seg["start"],
                "end": seg["end"],
                "access": PUBLIC if is_public else RESERVED,
                "owner": None if is_public else OWNERS[lane],
            }
            previous = holds[-1] if holds else None
            # Merge with the hold before it when nothing about the lane actually changed at
            # that boundary — a timeline boundary is a change in the COUNT, which need not be
            # a change for this particular lane.
            if (
                previous is not None
                and previous["end"] == hold["start"]
                and previous["access"] == hold["access"]
                and previous["owner"] == hold["owner"]
            ):
                previous["end"] = hold["end"]
            else:
                holds.append(hold)
        strips.append({"lane": lane, "segments": holds})
    return strips


def _best_public(segments: list[dict[str, Any]], start: str, end: str) -> dict[str, Any] | None:
    """The longest window at the peak public-lane count, WITHIN [start, end).

    Bounded by the session's own hours on purpose: an unbounded window is the S2 defect — 346
    of 672 options once advertised a best window outside the session they belonged to.
    """
    lo, hi = _to_min(start), _to_min(end)
    inside = [s for s in segments if _to_min(s["start"]) >= lo and _to_min(s["end"]) <= hi]
    if not inside:
        return None
    peak = max(s["public_lanes"] for s in inside)
    best: dict[str, Any] | None = None
    run: dict[str, Any] | None = None
    for seg in inside:
        if seg["public_lanes"] != peak:
            run = None
            continue
        if run is not None and run["end"] == seg["start"]:
            run["end"] = seg["end"]
        else:
            run = {"start": seg["start"], "end": seg["end"], "public_lanes": peak}
        span = _to_min(run["end"]) - _to_min(run["start"])
        if best is None or span > _to_min(best["end"]) - _to_min(best["start"]):
            best = dict(run)
    return best


def derive(document: dict[str, Any]) -> dict[str, Any]:
    """`document` with the target basin's options given a lane day view. Pure — returns a new
    document rather than mutating, so `--check` can compare without side effects."""
    document = json.loads(json.dumps(document))
    targets = [
        o
        for o in document["options"]
        if o.get("facility") == FACILITY and o.get("basin") == BASIN and o.get("lane_timeline")
    ]
    if not targets:
        raise SystemExit(f"no {FACILITY} / {BASIN} option with a lane_timeline in {FIXTURE.name}")

    segments = _segments(targets)
    lane_counts = {seg["lane_count"] for seg in segments}
    if len(lane_counts) != 1:
        raise SystemExit(f"the basin's timeline disagrees about its lane count: {lane_counts}")
    lane_count = lane_counts.pop()
    always_public = min(seg["public_lanes"] for seg in segments)
    missing = [lane for lane in range(always_public + 1, lane_count + 1) if lane not in OWNERS]
    if missing:
        raise SystemExit(f"lanes {missing} can be reserved but have no owner in OWNERS")

    day_view = {
        "weekday": WEEKDAY,
        "lane_count": lane_count,
        "strips": _strips(segments, lane_count),
    }
    for option in targets:
        # Every session of the basin shares ONE day view — it is a property of the basin's
        # weekday, not of the session — and each gets its own window-bounded best-public.
        option["lane_day_view"] = json.loads(json.dumps(day_view))
        option["lane_best_public"] = _best_public(segments, option["start"], option["end"])
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only; do not write")
    args = parser.parse_args(argv)

    raw = FIXTURE.read_text(encoding="utf-8")
    current = json.loads(raw)
    derived = derive(current)

    if derived == current:
        print(f"{FIXTURE.name}: the lane day view already matches its own lane_timeline.")
        return 0
    if args.check:
        print(f"{FIXTURE.name}: the lane day view DISAGREES with its own lane_timeline.")
        return 1
    FIXTURE.write_text(json.dumps(derived, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{FIXTURE.name}: rewritten from its own lane_timeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
